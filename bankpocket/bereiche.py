"""Lebensbereiche: Was kostet meine Wohnung, mein Auto? Kategorien und Verträge zu einem Thema gebündelt."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analysen import _monatssummen
from .contracts import add_months
from .db import Bereich, ContractRow, TransactionRow
from .service import contract_status

MONATE = 12  # so viele Monatsbalken
FENSTER = 6  # Schnitt über so viele volle Monate, wenn nichts anderes gewählt ist

# Vorschläge zum Antippen: (Name, Symbol, Kategorien, Stichworte im Vertragsnamen oder in der Versicherungsart)
VORLAGEN = [
    ("Wohnung", "🏡", ["Miete", "Strom", "Internet & Telefon"], ["rundfunk", "beitragsservice", "hausrat", "wohngebäude", "gez"]),
    ("Auto", "🚗", ["Auto", "Tanken"], ["kfz", "kraftfahrt", "adac", "teilauto", "autoversicherung", "tüv"]),
    ("Gesundheit", "💊", ["Gesundheit", "Fitness"], ["krankenkasse", "krankenversicherung", "zahn", "auslandskranken"]),
]


def _liste(text: str) -> list:
    try:
        wert = json.loads(text or "[]")
        return wert if isinstance(wert, list) else []
    except ValueError:
        return []


def kopf(b: Bereich) -> dict:
    return {"id": b.id, "name": b.name, "emoji": b.emoji, "kategorien": _liste(b.kategorien), "vertraege": _liste(b.vertraege)}


def _gehoert(b: dict, t: TransactionRow, kat: str, eltern: dict[str, str]) -> bool:
    return t.contract_id in b["vertraege"] or kat in b["kategorien"] or eltern.get(kat) in b["kategorien"]


def auswertung(s: Session, bereich: Bereich, heute: date, fenster: int = FENSTER,
               summen: dict[date, dict] | None = None) -> dict:
    """Kosten je Monat über das letzte Jahr, der Schnitt der letzten `fenster` vollen Monate und woraus er sich
    zusammensetzt. Einnahmen in den gewählten Kategorien (z. B. Untermiete) mindern die Kosten.
    summen: Monatssummen zum Wiederverwenden, wenn mehrere Bereiche nacheinander ausgewertet werden."""
    summen = {} if summen is None else summen
    b = kopf(bereich)
    b["vertraege"] = set(b["vertraege"])
    start = heute.replace(day=1)
    # der Schnitt läuft über die letzten vollen Monate – aber nur über solche, in denen es schon Buchungen gab
    erste = s.scalar(select(TransactionRow.buchungsdatum).order_by(TransactionRow.buchungsdatum).limit(1))
    ab = max(add_months(start, -fenster), erste.replace(day=1) if erste else start)
    vertrag = {c.id: c for c in s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False))) if c.gilt}
    monate, posten = [], defaultdict(lambda: {"summe": Decimal(0), "anzahl": 0})
    for ms in (add_months(start, -i) for i in range(MONATE, -1, -1)):
        m = summen.get(ms) or summen.setdefault(ms, _monatssummen(s, ms, add_months(ms, 1)))
        summe = Decimal(0)
        for t, art, kat in m["belege"]:
            if art == "gespart" or not _gehoert(b, t, kat, m["eltern"]):
                continue
            betrag = -getattr(t, "mein_betrag", t.betrag)  # Ausgabe positiv, Einnahme negativ
            summe += betrag
            if ab <= ms < start:  # nur das gewählte Fenster, ohne den laufenden Monat
                c = vertrag.get(t.contract_id)
                schluessel = ("vertrag", c.id, c.name, c.kategorie) if c else ("kategorie", None, kat, kat)
                posten[schluessel]["summe"] += betrag
                posten[schluessel]["anzahl"] += 1
        monate.append({"monat": ms.strftime("%Y-%m"), "summe": summe})
    volle = [m for m in monate[:-1] if m["monat"] >= ab.strftime("%Y-%m")]
    teiler = max(len(volle), 1)
    laufend = [c for c in vertrag.values() if c.typ == "ausgabe" and contract_status(c, heute)[0] != "inaktiv"
               and (c.id in b["vertraege"] or c.kategorie in b["kategorien"])]
    return {**kopf(bereich), "monate": monate, "zeitraum": len(volle), "fenster": fenster,
            "von": volle[0]["monat"] if volle else None,
            "schnitt": sum((m["summe"] for m in volle), Decimal(0)) / teiler,
            "jahr": sum((m["summe"] for m in volle), Decimal(0)) * 12 / teiler,
            "fix_monatlich": sum((c.monatlich for c in laufend), Decimal(0)),
            "posten": sorted(({"art": art, "id": cid, "name": name, "kategorie": kat, "anzahl": v["anzahl"],
                               "summe": v["summe"], "schnitt": v["summe"] / teiler}
                              for (art, cid, name, kat), v in posten.items() if v["summe"]),
                             key=lambda p: -p["schnitt"])}


def buchungen(s: Session, bereich: Bereich, monat: date, monate: int = 1, kategorie: str | None = None) -> list[TransactionRow]:
    """Die Buchungen des Bereichs in einem Monat – oder, mit kategorie, die eines Postens über mehrere Monate
    (nur die, die nicht schon als Vertrag einzeln aufgeführt sind)."""
    b = kopf(bereich)
    start = monat.replace(day=1)
    m = _monatssummen(s, start, add_months(start, monate))
    vertrag = {c.id for c in s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False))) if c.gilt}
    treffer = [t for t, art, kat in m["belege"] if art != "gespart" and _gehoert(b, t, kat, m["eltern"])
               and (kategorie is None or (kat == kategorie and t.contract_id not in vertrag))]
    return sorted(treffer, key=lambda t: (t.buchungsdatum, t.id), reverse=True)


def vorlagen(s: Session, vorhandene: list[Bereich], kategorien: set[str]) -> list[dict]:
    """Bereiche zum Antippen – mit den Kategorien, die es gibt, und den Verträgen, die dem Namen nach dazugehören."""
    namen = {b.name.lower() for b in vorhandene}
    vertraege = [c for c in s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False), ContractRow.typ == "ausgabe")) if c.gilt]
    out = []
    for name, symbol, kats, worte in VORLAGEN:
        if name.lower() in namen:
            continue
        passend = [c.id for c in vertraege if any(w in f"{c.name} {c.art}".lower() for w in worte)]
        kats = [k for k in kats if k in kategorien]
        if kats or passend:
            out.append({"name": name, "emoji": symbol, "kategorien": kats, "vertraege": passend})
    return out
