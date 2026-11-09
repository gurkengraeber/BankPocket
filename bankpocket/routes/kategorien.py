"""Kategorien (eingebaut + eigene) und Regeln zur Kategorisierung."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import ki
from ..contracts import AUSGABEN_REGELN, EINNAHMEN_REGELN, FALLBACK, categorize, paypal_merchant, regeln_setzen
from ..db import (Account, Budget, ContractRow, KategorieRow, KiKategorieRow, RegelRow, TransactionRow, kv_get, kv_set,
                  oberkategorien)
from ..service import _to_dataclass, sync_contracts
from .deps import get_ctx, get_db

router = APIRouter(prefix="/api")
Typ = Literal["ausgabe", "einnahme"]


class KategorieIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    emoji: str = Field(default="🏷️", max_length=16)
    typ: Typ = "ausgabe"
    ober: str = ""  # als Unterkategorie von … anlegen


class KategoriePatch(BaseModel):
    """Symbol geht bei jeder Kategorie; umbenennen und unterordnen nur bei eigenen."""
    emoji: str | None = Field(None, min_length=1, max_length=16)
    name: str | None = Field(None, min_length=1, max_length=40)
    ober: str | None = None


EMOJI_SCHLUESSEL = "kategorie_emoji"  # eigene Symbole für eingebaute Kategorien, als JSON


def _emoji_eingebaut(s: Session) -> dict[str, str]:
    try:
        return json.loads(kv_get(s, EMOJI_SCHLUESSEL) or "{}")
    except ValueError:
        return {}


class RegelIn(BaseModel):
    stichwort: str = Field(min_length=2, max_length=80)
    kategorie: str
    typ: Typ = "ausgabe"
    anwenden: bool = True  # auch auf vorhandene Buchungen


def regeln_laden(s: Session) -> None:
    regeln_setzen([(r.stichwort, r.kategorie, r.typ) for r in s.scalars(select(RegelRow))])


def alle_kategorien(s: Session) -> dict[str, list[str]]:
    # Eigene Kategorien gelten in beide Richtungen: Wer „Anna“ für Geld von Anna anlegt, braucht sie auch für Geld an
    # Anna. Zuerst die der passenden Richtung, dann die übrigen.
    # Unterkategorien stehen direkt hinter ihrer Oberkategorie.
    eigene = list(s.scalars(select(KategorieRow).order_by(KategorieRow.name)))
    namen = {k.name for k in eigene} | set(AUSGABEN_REGELN) | set(EINNAHMEN_REGELN) | set(FALLBACK.values())
    kinder: dict[str, list[str]] = {}
    for k in eigene:
        if k.ober in namen and k.ober != k.name:
            kinder.setdefault(k.ober, []).append(k.name)
    unter = {n for liste in kinder.values() for n in liste}
    je = lambda typ: [k.name for k in eigene if k.typ == typ and k.name not in unter]  # noqa: E731
    mit_kindern = lambda liste: [n for k in liste for n in (k, *kinder.get(k, []))]  # noqa: E731
    return {
        "ausgabe": mit_kindern([*AUSGABEN_REGELN, *je("ausgabe"), *je("einnahme"), FALLBACK["ausgabe"]]),
        "einnahme": mit_kindern([*EINNAHMEN_REGELN, *je("einnahme"), *je("ausgabe"), FALLBACK["einnahme"]]),
    }


@router.get("/kategorien")
def kategorien(s: Session = Depends(get_db)):
    eigene = list(s.scalars(select(KategorieRow)))
    regeln = list(s.scalars(select(RegelRow).order_by(RegelRow.stichwort)))
    return {
        **alle_kategorien(s),
        "eigene": [{"name": k.name, "emoji": k.emoji, "typ": k.typ, "ober": k.ober or ""} for k in eigene],
        "emoji": {**_emoji_eingebaut(s), **{k.name: k.emoji for k in eigene}},
        "ober": oberkategorien(s),
        "regeln": [{"id": r.id, "stichwort": r.stichwort, "kategorie": r.kategorie, "typ": r.typ} for r in regeln],
        "eingebaut": {k: v for k, v in {**AUSGABEN_REGELN, **EINNAHMEN_REGELN}.items()},
    }


@router.post("/kategorien", status_code=201)
def kategorie_anlegen(body: KategorieIn, s: Session = Depends(get_db)):
    name = body.name.strip()
    vorhanden = alle_kategorien(s)
    if name.lower() in {k.lower() for k in (*vorhanden["ausgabe"], *vorhanden["einnahme"])}:
        raise HTTPException(409, "Diese Kategorie gibt es schon.")
    s.add(KategorieRow(name=name, emoji=body.emoji.strip() or "🏷️", typ=body.typ, ober=_ober_pruefen(s, name, body.ober)))
    s.commit()
    return {"name": name}


def _ober_pruefen(s: Session, name: str, ober: str) -> str:
    """Eine Ebene reicht: Oberkategorien sind selbst keine Unterkategorien, und wer Unterkategorien hat, bleibt oben."""
    ober = ober.strip()
    if not ober:
        return ""
    vorhanden = alle_kategorien(s)
    eltern = oberkategorien(s)
    if ober == name or ober not in (*vorhanden["ausgabe"], *vorhanden["einnahme"]):
        raise HTTPException(422, "Unbekannte Oberkategorie.")
    if ober in eltern:
        raise HTTPException(422, f"„{ober}“ ist selbst eine Unterkategorie.")
    if name in eltern.values():
        raise HTTPException(422, f"„{name}“ hat selbst Unterkategorien.")
    return ober


@router.patch("/kategorien/{name}")
def kategorie_aendern(name: str, body: KategoriePatch, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    k = s.get(KategorieRow, name)
    vorhanden = alle_kategorien(s)
    if not k and name not in (*vorhanden["ausgabe"], *vorhanden["einnahme"]):
        raise HTTPException(404, "Kategorie nicht gefunden")
    if body.emoji is not None:
        if k:
            k.emoji = body.emoji.strip()
        else:  # eingebaute Kategorie: eigenes Symbol merken
            kv_set(s, EMOJI_SCHLUESSEL, json.dumps({**_emoji_eingebaut(s), name: body.emoji.strip()}, ensure_ascii=False))
    if body.ober is not None or (body.name and body.name.strip() != name):
        if not k:
            raise HTTPException(422, "Eingebaute Kategorien lassen sich nicht umbenennen oder unterordnen.")
    if body.ober is not None:
        k.ober = _ober_pruefen(s, name, body.ober)
    neu = (body.name or "").strip()
    if k and neu and neu != name:
        if neu.lower() in {x.lower() for x in (*vorhanden["ausgabe"], *vorhanden["einnahme"])} - {name.lower()}:
            raise HTTPException(409, "Diese Kategorie gibt es schon.")
        # der Name ist der Schlüssel: neue Zeile anlegen und alles umhängen, was auf den alten Namen zeigt
        s.add(KategorieRow(name=neu, emoji=k.emoji, typ=k.typ, ober=k.ober))
        for modell in (TransactionRow, RegelRow, ContractRow, Budget, KiKategorieRow):
            s.execute(update(modell).where(modell.kategorie == name).values(kategorie=neu))
        s.execute(update(KategorieRow).where(KategorieRow.ober == name).values(ober=neu))
        s.delete(k)
        name = neu
    s.flush()
    regeln_laden(s)
    ki.laden(s)
    s.commit()
    return {"name": name}


@router.delete("/kategorien/{name}", status_code=204)
def kategorie_loeschen(name: str, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    k = s.get(KategorieRow, name)
    if not k:
        raise HTTPException(404, "Nur eigene Kategorien können gelöscht werden.")
    for r in s.scalars(select(RegelRow).where(RegelRow.kategorie == name)):
        s.delete(r)
    for t in s.scalars(select(TransactionRow).where(TransactionRow.kategorie == name)):
        t.kategorie = k.ober or None  # Unterkategorie: zurück zur Oberkategorie – sonst automatische Einordnung
    s.execute(update(KategorieRow).where(KategorieRow.ober == name).values(ober=""))
    s.delete(k)
    s.flush()
    regeln_laden(s)
    sync_contracts(s, ctx.today())
    s.commit()


@router.post("/regeln", status_code=201)
def regel_anlegen(body: RegelIn, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    stichwort = body.stichwort.strip().lower()
    if body.kategorie not in alle_kategorien(s)[body.typ]:
        raise HTTPException(422, "Unbekannte Kategorie.")
    regel = s.scalar(select(RegelRow).where(RegelRow.stichwort == stichwort, RegelRow.typ == body.typ))
    if regel:
        regel.kategorie = body.kategorie
    else:
        regel = RegelRow(stichwort=stichwort, kategorie=body.kategorie, typ=body.typ)
        s.add(regel)
    geaendert = 0
    if body.anwenden:
        for t in s.scalars(select(TransactionRow).where(TransactionRow.intern.is_(False))):
            if (t.betrag > 0) == (body.typ == "einnahme") and stichwort in f"{t.gegenpartei} {t.verwendungszweck}".lower():
                t.kategorie = body.kategorie
                geaendert += 1
    s.flush()
    regeln_laden(s)
    sync_contracts(s, ctx.today())  # Verträge übernehmen die neue Kategorie
    s.commit()
    return {"id": regel.id, "geaendert": geaendert}


@router.delete("/regeln/{regel_id}", status_code=204)
def regel_loeschen(regel_id: int, s: Session = Depends(get_db)):
    r = s.get(RegelRow, regel_id)
    if not r:
        raise HTTPException(404, "Regel nicht gefunden")
    s.delete(r)
    s.flush()
    regeln_laden(s)
    s.commit()


# ---------- Unklare Buchungen: was weder Regel noch KI einordnen konnte ----------
class UnklarIn(BaseModel):
    ids: list[int] = Field(min_length=1)
    kategorie: str | None = None
    umbuchung: bool = False  # stattdessen als Umbuchung zwischen eigenen Konten markieren
    merken: bool = False  # künftige Buchungen dieses Händlers genauso einordnen
    haendler: str = ""


def _unklare(s: Session) -> list[TransactionRow]:
    depots = set(s.scalars(select(Account.id).where(Account.typ == "depot")))
    manuell = set(s.scalars(select(Account.id).where(Account.quelle == "manuell")))
    return [t for t in s.scalars(select(TransactionRow).where(
                TransactionRow.intern.is_(False), TransactionRow.kategorie.is_(None), TransactionRow.betrag != 0)
                .order_by(TransactionRow.buchungsdatum.desc(), TransactionRow.id.desc()))
            if t.account_id not in depots
            and not (t.betrag > 0 and t.account_id in manuell)  # Einzahlungen/Bestände dort sind kein Einkommen
            and categorize(t.gegenpartei, t.verwendungszweck, "einnahme" if t.betrag > 0 else "ausgabe",
                           buchungstext=t.buchungstext) in FALLBACK.values()]


@router.get("/unklar")
def unklar(s: Session = Depends(get_db)):
    """Buchungen ohne Kategorie, nach Händler zusammengefasst – die häufigsten zuerst."""
    namen = dict(s.execute(select(Account.id, Account.name)).all())
    gruppen: dict[tuple[str, str], dict] = {}
    unklare = _unklare(s)
    for t in unklare:
        typ = "einnahme" if t.betrag > 0 else "ausgabe"
        haendler = (paypal_merchant(_to_dataclass(t)) or t.gegenpartei or "").strip()
        g = gruppen.setdefault((typ, haendler.lower() or f"#{t.id}"), {
            "haendler": haendler, "typ": typ, "anzahl": 0, "summe": 0, "ids": [], "art": t.buchungstext,
            "zweck": t.verwendungszweck[:120], "letzte": t.buchungsdatum, "konto": namen.get(t.account_id)})
        g["anzahl"] += 1
        g["summe"] += t.betrag
        g["ids"].append(t.id)
    # die meistgenutzten Kategorien als schnelle Auswahl – gezählt über alle Buchungen, wie sie angezeigt werden
    nutzung: dict[tuple[str, str], int] = {}
    for t in s.scalars(select(TransactionRow).where(TransactionRow.intern.is_(False))):
        typ = "einnahme" if t.betrag > 0 else "ausgabe"
        kategorie = t.kategorie or categorize(t.gegenpartei, t.verwendungszweck, typ, buchungstext=t.buchungstext)
        nutzung[(typ, kategorie)] = nutzung.get((typ, kategorie), 0) + 1
    alle = alle_kategorien(s)
    haeufig = {typ: [k for k in sorted(alle[typ], key=lambda k: -nutzung.get((typ, k), 0))
                     if k not in FALLBACK.values() and k != "Sparen"][:8] for typ in alle}
    from .. import umbuchungen
    from .konten import _kurz
    paare = [{"sicherheit": p, "abgang": _kurz(s, a), "zugang": _kurz(s, b)}
             for p, a, b in umbuchungen.offene_fragen(s)]
    return {"anzahl": len(unklare) + len(paare), "umbuchungen": paare, "gruppen": sorted(gruppen.values(), key=lambda g: (-g["anzahl"], g["summe"])),
            "haeufig": haeufig}


@router.post("/unklar")
def unklar_zuordnen(body: UnklarIn, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    rows = list(s.scalars(select(TransactionRow).where(TransactionRow.id.in_(body.ids))))
    if not rows:
        raise HTTPException(404, "Buchungen nicht gefunden")
    typ = "einnahme" if rows[0].betrag > 0 else "ausgabe"
    if body.umbuchung:
        for t in rows:
            t.intern, t.intern_fix = True, True
    else:
        if body.kategorie not in alle_kategorien(s)[typ]:
            raise HTTPException(422, "Unbekannte Kategorie.")
        for t in rows:
            t.kategorie = body.kategorie  # auch „Sonstiges“: bewusst gewählt gilt als erledigt
        stichwort = body.haendler.strip().lower()
        if body.merken and len(stichwort) >= 3 and body.kategorie not in FALLBACK.values():
            regel = s.scalar(select(RegelRow).where(RegelRow.stichwort == stichwort, RegelRow.typ == typ))
            if regel:
                regel.kategorie = body.kategorie
            else:
                s.add(RegelRow(stichwort=stichwort, kategorie=body.kategorie, typ=typ))
            s.flush()
            regeln_laden(s)
    sync_contracts(s, ctx.today())
    s.commit()
    return {"zugeordnet": len(rows), "offen": len(_unklare(s))}
