"""Bankverbindungen (FinTS) einrichten, abrufen, Freigaben bestätigen."""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import bankliste
from ..db import Account, Connection
from ..fetchers.enablebanking import BANKEN as EB_BANKEN
from ..fetchers.fints_source import BANKEN
from .deps import get_ctx, get_db

router = APIRouter(prefix="/api")

FREIGABE_GUELTIG_TAGE = 90
# Weitere Quellen neben FinTS-Banken (Art → Anzeigename)
QUELLEN = {"trade_republic": "Trade Republic", "binance": "Binance", "splitwise": "Splitwise",
           "enablebanking": "Bank Norwegian"}
# Quellen, die unter anderem Namen in der Oberfläche erscheinen (Kachelfarbe, Kontoquelle)
BANK_FUER_QUELLE = {"enablebanking": "norwegian"}


class VerbindungIn(BaseModel):
    art: str = "fints"  # fints | trade_republic | binance | splitwise | enablebanking
    # bei fints: ing | consorsbank | andere (dann über BLZ aus der Bankliste); bei enablebanking: norwegian | consorsbank | n26 | revolut
    bank: str | None = None
    login: str = ""
    pin: str = ""  # bei enablebanking leer, wenn die Zugangsdaten einer bestehenden Verbindung mitgenutzt werden
    blz: str | None = None
    url: str | None = None
    name: str | None = None


def _handynummer(login: str) -> str:
    """Trade Republic erwartet die Handynummer mit Ländervorwahl (+49 …); 0170 … wird als deutsche Nummer gelesen."""
    login = re.sub(r"[\s/()-]", "", login)
    if login.startswith("00"):
        login = "+" + login[2:]
    elif login.startswith("0"):
        login = "+49" + login[1:]
    if not re.fullmatch(r"\+\d{8,15}", login):
        raise HTTPException(422, "Bitte die Handynummer deines Trade-Republic-Kontos mit Ländervorwahl angeben, "
                                 "z. B. +49 170 1234567.")
    return login


def _pruefen(body: VerbindungIn) -> tuple[str, str]:
    """Eingaben je Quelle prüfen und normalisieren → (login, pin)."""
    login, pin = body.login.strip(), body.pin.strip()
    if not pin:
        raise HTTPException(422, "Bitte die Zugangsdaten vollständig angeben.")
    if body.art == "trade_republic":
        login = _handynummer(login)
        if not re.fullmatch(r"\d{4}", pin):
            raise HTTPException(422, "Die Trade-Republic-PIN hat 4 Ziffern.")
    elif body.art == "binance":
        if len(login) < 20 or len(pin) < 20:
            raise HTTPException(422, "Bitte API-Key und Secret Key von Binance vollständig einfügen.")
    elif body.art == "enablebanking":
        if not re.fullmatch(r"[0-9a-fA-F-]{30,40}", login):
            raise HTTPException(422, "Bitte die Application-ID von Enable Banking einfügen (sieht aus wie 1a2b3c4d-…).")
        if "PRIVATE KEY" not in pin:
            raise HTTPException(422, "Bitte den privaten Schlüssel einfügen: den gesamten Inhalt der .pem-Datei "
                                     "von „BEGIN“ bis „END PRIVATE KEY“.")
    elif body.art == "splitwise":
        if len(pin) < 20:
            raise HTTPException(422, "Bitte den API-Schlüssel von Splitwise vollständig einfügen.")
    elif not login:
        raise HTTPException(422, "Bitte Login bzw. Zugangsnummer angeben.")
    return login, pin


class VerbindungPatch(BaseModel):
    login: str | None = None
    pin: str | None = None
    name: str | None = None


class EingabeIn(BaseModel):
    tan: str | None = None
    tan_verfahren: str | None = None
    tan_medium: str | None = None
    bestaetigt: bool | None = None
    code: str | None = None  # Enable Banking: eingefügte Rückkehr-Adresse oder Code


def _freigabe_faellig(c: Connection, ctx):
    if not c.letzte_freigabe or c.art not in ("fints", "enablebanking"):
        return None
    if c.art == "enablebanking" and c.client_data_enc:  # die Sitzung nennt ihr Ablaufdatum selbst
        try:
            bis = json.loads(ctx.vault.decrypt(c.client_data_enc)).get("valid_until")
            return datetime.fromisoformat(bis.replace("Z", "+00:00")).astimezone().date()
        except Exception:
            pass
    return (c.letzte_freigabe + timedelta(days=FREIGABE_GUELTIG_TAGE)).date()


def verbindung_out(s: Session, c: Connection, ctx) -> dict:
    live = ctx.manager.live(c.id)
    if c.status == "laeuft" and live and not live["laeuft"]:
        # Der Abruf ist fertig, seit wir gelesen haben: Lese-Snapshot beenden und Endstatus nachladen
        s.commit()
        s.refresh(c)
    konten = [{"id": a.id, "name": a.name, "gruppe": a.gruppe}
              for a in s.scalars(select(Account).where(Account.connection_id == c.id).order_by(Account.id))]
    return {
        "id": c.id, "art": c.art, "bank": c.bank, "name": c.name, "status": c.status, "meldung": c.meldung,
        "letzter_erfolg": c.letzter_erfolg, "letzter_versuch": c.letzter_versuch,
        "letzte_freigabe": c.letzte_freigabe,
        "freigabe_faellig_am": _freigabe_faellig(c, ctx),
        "tan_verfahren": c.tan_verfahren_name, "konten": konten, "live": live,
    }


def get_conn(s: Session, conn_id: int) -> Connection:
    c = s.get(Connection, conn_id)
    if not c:
        raise HTTPException(404, "Verbindung nicht gefunden")
    return c


def _rueckkehr_adresse(request: Request) -> str:
    """Enable Banking leitet nach der Freigabe auf diese Adresse zurück (muss dort eingetragen sein) und nimmt
    nur https. Ohne HTTPS dient https://localhost als Ziel: Die Seite lädt nicht, die Adresse wird eingefügt."""
    basis = str(request.base_url) if request.url.scheme == "https" else "https://localhost/"
    return basis + "api/enablebanking/callback"


@router.get("/banken")
def banken():
    return [{"id": k, **v} for k, v in BANKEN.items()]


@router.get("/banken/suche")
def banken_suche(q: str = ""):
    return bankliste.suche(q)


@router.get("/verbindungen")
def verbindungen(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    return [verbindung_out(s, c, ctx) for c in s.scalars(select(Connection).order_by(Connection.id))]


@router.post("/verbindungen", status_code=201)
def verbindung_anlegen(body: VerbindungIn, request: Request, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    vorhanden = None
    if body.art == "enablebanking" and not body.login.strip() and not body.pin.strip():
        # weitere Bank über dieselbe Enable-Banking-Anwendung: Application-ID und Schlüssel mitnutzen
        vorhanden = s.scalar(select(Connection).where(Connection.art == "enablebanking").order_by(Connection.id))
    if vorhanden:
        login, pin = ctx.vault.decrypt_str(vorhanden.login_enc), ctx.vault.decrypt_str(vorhanden.pin_enc)
    else:
        login, pin = _pruefen(body)
    if body.art == "enablebanking":
        art, blz = body.art, ""
        bank = body.bank if body.bank in EB_BANKEN else BANK_FUER_QUELLE[body.art]
        name, url = body.name or EB_BANKEN[bank], _rueckkehr_adresse(request)
    elif body.art in QUELLEN:
        art, name, blz, url = body.art, body.name or QUELLEN[body.art], "", ""
        bank = BANK_FUER_QUELLE.get(body.art, body.art)
    elif body.art != "fints":
        raise HTTPException(422, "Unbekannte Datenquelle.")
    elif body.bank in BANKEN:
        vorlage = BANKEN[body.bank]
        art, bank, blz, url, name = "fints", body.bank, vorlage["blz"], vorlage["url"], body.name or vorlage["name"]
    else:
        blz = re.sub(r"\s", "", body.blz or "")
        eintrag = bankliste.nach_blz(blz)
        url = (body.url or "").strip() or (eintrag["url"] if eintrag else "")
        if not re.fullmatch(r"\d{8}", blz) or not url.startswith("https://"):
            raise HTTPException(422, "Bank nicht gefunden – bitte BLZ und FinTS-Adresse (https://…) angeben.")
        name = body.name or (eintrag["name"] if eintrag else f"Bank {blz}")
        art, bank = "fints", bankliste.familie(name, url)
    c = Connection(art=art, bank=bank, name=name, blz=blz, server_url=url,
                   login_enc=ctx.vault.encrypt(login), pin_enc=ctx.vault.encrypt(pin))
    s.add(c)
    s.commit()
    ctx.manager.starten(c.id, interaktiv=True, erstverbindung=True)
    return {"id": c.id}


@router.get("/verbindungen/{conn_id}")
def verbindung(conn_id: int, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    return verbindung_out(s, get_conn(s, conn_id), ctx)


@router.post("/verbindungen/{conn_id}/abrufen")
def verbindung_abrufen(conn_id: int, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    c = get_conn(s, conn_id)
    if c.status in ("pin_falsch", "gesperrt"):
        raise HTTPException(409, "Bitte zuerst die Zugangsdaten prüfen.")
    return {"gestartet": ctx.manager.starten(conn_id, interaktiv=True, erstverbindung=c.letzter_erfolg is None)}


@router.post("/verbindungen/{conn_id}/eingabe")
def verbindung_eingabe(conn_id: int, body: EingabeIn, ctx=Depends(get_ctx)):
    if not ctx.manager.eingabe(conn_id, body.model_dump(exclude_none=True)):
        raise HTTPException(409, "Für diese Verbindung läuft gerade kein Abruf.")
    return {"ok": True}


@router.post("/verbindungen/{conn_id}/abbrechen")
def verbindung_abbrechen(conn_id: int, ctx=Depends(get_ctx)):
    return {"abgebrochen": ctx.manager.abbrechen(conn_id)}


@router.patch("/verbindungen/{conn_id}")
def verbindung_aendern(conn_id: int, body: VerbindungPatch, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    c = get_conn(s, conn_id)
    if body.name:
        c.name = body.name
    if body.login:
        login = _handynummer(body.login.strip()) if c.art == "trade_republic" else body.login.strip()
        c.login_enc = ctx.vault.encrypt(login)
        if not c.letzter_erfolg:
            c.client_data_enc = None  # Sitzungsdaten aus Fehlversuchen mit dem alten Login nicht weiterverwenden
    if body.pin:
        c.pin_enc = ctx.vault.encrypt(body.pin)
    if (body.login or body.pin) and c.status in ("pin_falsch", "gesperrt"):
        c.status, c.meldung = "neu", "Zugangsdaten geändert – bitte Abruf starten."
    s.commit()
    return verbindung_out(s, c, ctx)


@router.delete("/verbindungen/{conn_id}", status_code=204)
def verbindung_loeschen(conn_id: int, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    c = get_conn(s, conn_id)
    ctx.manager.abbrechen(conn_id)
    for a in s.scalars(select(Account).where(Account.connection_id == conn_id)):
        a.connection_id = None  # Konten und Historie bleiben erhalten
    s.delete(c)
    s.commit()


@router.get("/enablebanking/callback")
def enablebanking_rueckkehr(state: str = "", code: str = "", error: str = "", error_description: str = "",
                           ctx=Depends(get_ctx)):
    """Die Bank leitet hierher zurück; der Code geht an den wartenden Abruf, dann zurück in die App."""
    m = re.fullmatch(r"bp(\d+)-[0-9a-f]{12}", state)
    if m and code:
        # samt state weiterreichen: Der Abruf nimmt den Code nur an, wenn der state zu seiner Freigabe gehört
        ctx.manager.eingabe(int(m.group(1)), {"code": urlencode({"state": state, "code": code})})
    elif m and error:
        ctx.manager.eingabe(int(m.group(1)), {"code": urlencode({"state": state, "error": error,
                                                                "error_description": error_description})})
    ziel = f"/#/verbindung/{m.group(1)}" if m else "/"
    return RedirectResponse(ziel, status_code=303)


@router.post("/aktualisieren")
def aktualisieren(ctx=Depends(get_ctx)):
    return {"gestartet": ctx.manager.alle_starten()}
