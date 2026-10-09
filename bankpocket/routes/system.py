"""Login, Hinweise, Push und Einstellungen."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import backup, version
from ..auth import COOKIE, SESSION_TAGE, erzeuge_token, pruefe_passwort, pruefe_token, session_secret
from ..db import Account, KeyValue, Notice, PushSubscription, TransactionRow, kv_get
from ..service import eigene_namen, eigene_namen_zuruecknehmen, markiere_interne_umbuchungen, sync_contracts
from .deps import get_ctx, get_db

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    passwort: str


class GelesenIn(BaseModel):
    ids: list[int] | None = None


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushAboIn(BaseModel):
    endpoint: str
    keys: PushKeys


class PushAboDel(BaseModel):
    endpoint: str


def angemeldet(request: Request, s: Session) -> bool:
    return pruefe_token(session_secret(s), request.cookies.get(COOKIE))


@router.get("/health")
def health():
    # version: Stand der Dateien auf dem Server, gestartet: Stand des laufenden Codes (weicht ab: Neustart steht aus)
    return {"ok": True, "version": version.gelesen(), "gestartet": version.GESTARTET}


@router.get("/auth")
def auth_status(request: Request, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    return {"aktiv": ctx.settings.auth, "passwort_gesetzt": bool(kv_get(s, "passwort_hash")),
            "angemeldet": (not ctx.settings.auth) or angemeldet(request, s)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, s: Session = Depends(get_db)):
    bremse = request.app.state.login_bremse
    if bremse.gesperrt():
        raise HTTPException(429, "Zu viele Fehlversuche – bitte 5 Minuten warten.")
    gespeichert = kv_get(s, "passwort_hash")
    if not gespeichert:
        raise HTTPException(409, "Noch kein Passwort gesetzt (python -m bankpocket.passwort).")
    if not pruefe_passwort(body.passwort, gespeichert):
        bremse.fehlversuch()
        raise HTTPException(401, "Passwort falsch.")
    bremse.erfolg()
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, erzeuge_token(session_secret(s)), max_age=SESSION_TAGE * 86400, httponly=True,
                        samesite="strict", secure=https, path="/")
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/hinweise")
def hinweise(s: Session = Depends(get_db)):
    rows = s.scalars(select(Notice).order_by(Notice.erstellt_am.desc(), Notice.id.desc()).limit(50))
    return [{"id": n.id, "art": n.art, "titel": n.titel, "text": n.text, "link": n.link,
             "erstellt_am": n.erstellt_am, "gelesen": n.gelesen} for n in rows]


@router.post("/hinweise/gelesen")
def hinweise_gelesen(body: GelesenIn, s: Session = Depends(get_db)):
    q = update(Notice).values(gelesen=True)
    if body.ids:
        q = q.where(Notice.id.in_(body.ids))
    s.execute(q)
    s.commit()
    return {"ok": True}


@router.get("/push")
def push_info(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    abos = len(list(s.scalars(select(PushSubscription.id))))
    return {"schluessel": ctx.notifier.public_key(), "abos": abos}


@router.post("/push/abo", status_code=201)
def push_abo(body: PushAboIn, s: Session = Depends(get_db)):
    abo = s.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if abo is None:
        abo = PushSubscription(endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth)
        s.add(abo)
    else:
        abo.p256dh, abo.auth = body.keys.p256dh, body.keys.auth
    s.commit()
    return {"ok": True}


@router.delete("/push/abo")
def push_abo_loeschen(body: PushAboDel, s: Session = Depends(get_db)):
    s.execute(delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    s.commit()
    return {"ok": True}


@router.post("/push/test")
def push_test(ctx=Depends(get_ctx)):
    gesendet = ctx.notifier._push_alle({"titel": "BankPocket", "text": "Push-Benachrichtigungen funktionieren.",
                                        "link": "#/einstellungen", "tag": "test"})
    return {"gesendet": gesendet}


@router.get("/einstellungen")
def einstellungen(request: Request, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    sched = getattr(request.app.state, "scheduler", None)
    return {"abrufzeiten": [z.strftime("%H:%M") for z in ctx.settings.abrufzeiten],
            "naechster_abruf": sched.naechster if sched else None,
            "automatisch": ctx.settings.scheduler,
            "produkt_id_gesetzt": bool(ctx.settings.fints_product_id),
            "eigene_namen": kv_get(s, "eigene_namen") or "",
            "sicherung": _sicherung(s, ctx)}


class EigeneNamen(BaseModel):
    namen: str = ""


@router.put("/einstellungen/eigene-namen")
def eigene_namen_setzen(body: EigeneNamen, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Eigener Name (mehrere mit Komma): Buchungen mit diesem Namen als Gegenseite gelten als Umbuchung."""
    namen = ", ".join(n.strip() for n in body.namen.replace("\n", ",").split(",") if n.strip())[:300]
    # Markierungen aus der Zeit vor dem Merker nachtragen: Umbuchung ohne Gegenbuchung, ohne eigene IBAN als
    # Gegenseite und mit dem bisherigen Namen – die kam über den Namen zustande.
    eigene_ibans = {i for i in s.scalars(select(Account.iban)) if i}
    for woerter in eigene_namen(s):
        for t in s.scalars(select(TransactionRow).where(
                TransactionRow.intern.is_(True), TransactionRow.intern_fix.is_(False),
                TransactionRow.intern_name.is_(False), TransactionRow.gegenbuchung_id.is_(None),
                func.lower(TransactionRow.gegenpartei).like(f"%{woerter[0]}%"))):
            if t.iban_gegenpartei not in eigene_ibans and set(woerter) <= set(
                    re.findall(r"[^\W\d_]+", (t.gegenpartei or "").lower())):
                t.intern_name = True
    s.flush()
    vorher = s.scalar(select(func.count()).select_from(TransactionRow).where(TransactionRow.intern.is_(True)))
    zurueck = eigene_namen_zuruecknehmen(s)
    kv = s.get(KeyValue, "eigene_namen")
    if kv:
        kv.value = namen
    else:
        s.add(KeyValue(key="eigene_namen", value=namen))
    s.flush()
    markiere_interne_umbuchungen(s)
    s.flush()
    sync_contracts(s, ctx.today())
    nachher = s.scalar(select(func.count()).select_from(TransactionRow).where(TransactionRow.intern.is_(True)))
    s.commit()
    return {"eigene_namen": namen, "neu_markiert": max(nachher - vorher, 0),
            "zurueckgenommen": max(vorher - nachher, 0) if zurueck else 0}


def _sicherung(s: Session, ctx) -> dict:
    return {**backup.stand(s), "passwort_gesetzt": bool(ctx.settings.backup_passwort),
            "ziel": ctx.settings.backup_ziel.split(":")[0] if ctx.settings.backup_ziel else None}


@router.post("/sicherung")
def sicherung_jetzt(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    backup.taeglich(ctx, erzwingen=True)
    s.expire_all()
    return _sicherung(s, ctx)
