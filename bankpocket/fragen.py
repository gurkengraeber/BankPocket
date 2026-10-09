"""Fragen an die eigenen Zahlen in normaler Sprache – ohne dass Finanzdaten das Haus verlassen.

Die KI bekommt nur die Frage, das heutige Datum und die Namen der Kategorien. Sie übersetzt die Frage in einen
kleinen Auftrag („Summe der Ausgaben für Lebensmittel, 1.7.–30.9.“). Gerechnet wird danach hier auf dem Server;
Beträge, Buchungen, Empfänger und Kontostände werden nie gesendet, und auch die Antwort entsteht lokal.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from . import ki
from .analysen import _monatssummen
from .contracts import add_months
from .service import euro

ARTEN = ("summe", "durchschnitt", "verlauf", "groesste", "vergleich", "empfaenger", "kategorien")
RICHTUNGEN = {"ausgabe": "Ausgaben", "einnahme": "Einnahmen", "gespart": "Gespartes"}

SYSTEM = """Du übersetzt Fragen zu privaten Finanzen in einen Auftrag für eine Auswertung. Du bekommst keine \
Finanzdaten und rechnest nichts aus – du wählst nur aus, was ausgewertet werden soll.
Antworte ausschließlich mit JSON in dieser Form:
{"art": "summe|durchschnitt|verlauf|groesste|vergleich|empfaenger|kategorien|unklar",
 "richtung": "ausgabe|einnahme|gespart",
 "kategorie": "Name genau wie in der Liste oder null",
 "suchtext": "Name eines Händlers oder Empfängers aus der Frage, sonst null",
 "von": "JJJJ-MM-TT", "bis": "JJJJ-MM-TT",
 "vergleich_von": "JJJJ-MM-TT oder null", "vergleich_bis": "JJJJ-MM-TT oder null",
 "anzahl": 5}
Bedeutung von "art": summe = Gesamtbetrag im Zeitraum; durchschnitt = Betrag pro Monat; verlauf = Betrag je Monat; \
groesste = die größten einzelnen Buchungen; kategorien = wofür am meisten (Rangliste der Kategorien); empfaenger = bei wem am meisten (Rangliste der \
Händler/Empfänger); \
vergleich = zwei Zeiträume gegenüberstellen (zweiter Zeitraum in vergleich_von/vergleich_bis); unklar = die Frage \
lässt sich so nicht auswerten.
Zeiträume immer als ganze Tage. Ohne Angabe: die letzten drei vollen Monate. „Dieses Jahr“ = 1. Januar bis heute. \
Eine Kategorie nur setzen, wenn sie zur Frage passt; ein Händlername gehört in suchtext, nicht in kategorie."""


def _datum(wert, standard: date | None = None) -> date | None:
    try:
        return date.fromisoformat(str(wert)[:10])
    except ValueError:
        return standard


def auftrag_aus_antwort(text: str, kategorien: dict[str, list[str]], heute: date) -> dict | None:
    """Antwort der KI prüfen: nur bekannte Werte übernehmen, alles andere auf sichere Vorgaben setzen."""
    try:
        roh = json.loads(text)
    except ValueError:
        return None
    if not isinstance(roh, dict) or roh.get("art") not in ARTEN:
        return None
    richtung = roh.get("richtung") if roh.get("richtung") in RICHTUNGEN else "ausgabe"
    erlaubt = kategorien["einnahme" if richtung == "einnahme" else "ausgabe"]
    monatsanfang = heute.replace(day=1)
    von = _datum(roh.get("von"), add_months(monatsanfang, -3))
    bis = _datum(roh.get("bis"), monatsanfang - timedelta(days=1))
    if von > bis:
        von, bis = bis, von
    auftrag = {"art": roh["art"], "richtung": richtung, "von": von, "bis": min(bis, heute),
               "kategorie": roh.get("kategorie") if roh.get("kategorie") in erlaubt else None,
               "suchtext": (str(roh["suchtext"]).strip()[:60] or None) if roh.get("suchtext") else None,
               "anzahl": max(1, min(int(roh["anzahl"]), 20)) if str(roh.get("anzahl", "")).isdigit() else 5}
    if auftrag["art"] == "vergleich":
        auftrag["vergleich_von"], auftrag["vergleich_bis"] = _datum(roh.get("vergleich_von")), _datum(roh.get("vergleich_bis"))
        if not auftrag["vergleich_von"] or not auftrag["vergleich_bis"]:  # ohne zweiten Zeitraum: gleich lang davor
            laenge = auftrag["bis"] - auftrag["von"]
            auftrag["vergleich_bis"] = auftrag["von"] - timedelta(days=1)
            auftrag["vergleich_von"] = auftrag["vergleich_bis"] - laenge
    return auftrag


def _buchungen(s: Session, a: dict, von: date, bis: date) -> list[tuple]:
    """(Buchung, Betrag als positive Zahl, Kategorie) – dieselbe Zählweise wie in der Monatsanalyse."""
    such = (a["suchtext"] or "").lower()
    treffer = []
    m = _monatssummen(s, von, bis + timedelta(days=1))
    for t, art, kat in m["belege"]:
        kat = m["eltern"].get(kat, kat) if a["kategorie"] != kat else kat  # Unterkategorien zählen oben mit
        if art != a["richtung"] or (a["kategorie"] and kat != a["kategorie"]):
            continue
        if such and such not in f"{t.gegenpartei} {t.verwendungszweck}".lower():
            continue
        betrag = getattr(t, "mein_betrag", t.betrag)
        treffer.append((t, betrag if art == "einnahme" else -betrag, kat))  # eine Rückzahlung mindert die Ausgaben
    return treffer


def _zeitraum(von: date, bis: date) -> str:
    return f"{von:%d.%m.%Y} – {bis:%d.%m.%Y}"


def _name(t) -> str:
    return (t.gegenpartei or t.verwendungszweck or "Unbekannt").strip()[:60]


def ausfuehren(s: Session, a: dict) -> dict:
    """Den Auftrag lokal ausrechnen und die Antwort hier formulieren."""
    was = RICHTUNGEN[a["richtung"]] + (f" für {a['kategorie']}" if a["kategorie"] else "") \
        + (f" bei „{a['suchtext']}“" if a["suchtext"] else "")
    verstanden = f"{was} · {_zeitraum(a['von'], a['bis'])}"
    treffer = _buchungen(s, a, a["von"], a["bis"])
    kategorie_von = {t.id: kat for t, _, kat in treffer}
    treffer = [(t, b) for t, b, _ in treffer]
    summe = sum((b for _, b in treffer), Decimal(0))
    zeilen: list[dict] = []
    if a["art"] == "summe":
        antwort = f"{was}: {euro(summe)} in {len(treffer)} {'Buchung' if len(treffer) == 1 else 'Buchungen'}."
    elif a["art"] == "durchschnitt":
        monate = max(Decimal((a["bis"] - a["von"]).days + 1) / Decimal("30.44"), Decimal(1))
        antwort = f"{was}: im Schnitt {euro(summe / monate)} pro Monat (insgesamt {euro(summe)})."
    elif a["art"] == "verlauf":
        je_monat: dict[str, Decimal] = defaultdict(Decimal)
        m = a["von"].replace(day=1)
        while m <= a["bis"]:
            je_monat[m.strftime("%Y-%m")] += 0
            m = add_months(m, 1)
        for t, b in treffer:
            je_monat[t.buchungsdatum.strftime("%Y-%m")] += b
        zeilen = [{"label": k, "monat": k, "betrag": v} for k, v in sorted(je_monat.items())]
        antwort = f"{was} je Monat – insgesamt {euro(summe)}."
    elif a["art"] == "groesste":
        top = sorted(treffer, key=lambda p: -p[1])[:a["anzahl"]]
        zeilen = [{"label": f"{_name(t)} · {t.buchungsdatum:%d.%m.%Y}", "betrag": b, "buchung_id": t.id} for t, b in top]
        antwort = f"Die {len(top)} größten Buchungen – {was}." if top else f"Keine Buchungen gefunden – {was}."
    elif a["art"] in ("empfaenger", "kategorien"):
        je: dict[str, Decimal] = defaultdict(Decimal)
        for t, b in treffer:
            je[_name(t) if a["art"] == "empfaenger" else kategorie_von[t.id]] += b
        zeilen = [{"label": n, "betrag": v} for n, v in sorted(je.items(), key=lambda p: -p[1])[:a["anzahl"]]]
        wo = "bei diesen Empfängern" if a["art"] == "empfaenger" else "in diesen Kategorien"
        antwort = f"{was}: am meisten {wo} (insgesamt {euro(summe)})."
    else:  # vergleich
        vorher = sum((b for _, b, _ in _buchungen(s, a, a["vergleich_von"], a["vergleich_bis"])), Decimal(0))
        zeilen = [{"label": _zeitraum(a["von"], a["bis"]), "betrag": summe},
                  {"label": _zeitraum(a["vergleich_von"], a["vergleich_bis"]), "betrag": vorher}]
        diff = summe - vorher
        antwort = (f"{was}: {euro(abs(diff))} {'mehr' if diff > 0 else 'weniger'} als im Vergleichszeitraum"
                   + (f" ({diff / vorher:+.0%})." if vorher else "."))
    return {"antwort": antwort, "verstanden": verstanden, "zeilen": zeilen, "summe": summe, "anzahl": len(treffer)}


def fragen(ctx, s: Session, frage: str) -> dict:
    client = ki._client(ctx, s)
    if client is None:
        raise RuntimeError("Kein API-Schlüssel hinterlegt (Einstellungen → Kategorien mit KI).")
    kategorien = {typ: ki._kategorien(s, typ) for typ in ("ausgabe", "einnahme")}
    heute = ctx.today()
    gesendet = (f"Heute ist der {heute.isoformat()}.\nKategorien für Ausgaben: {', '.join(kategorien['ausgabe'])}\n"
                f"Kategorien für Einnahmen: {', '.join(kategorien['einnahme'])}\n\nFrage: {frage.strip()[:300]}")
    auftrag = auftrag_aus_antwort(client.chat(ki.MODELL, SYSTEM, gesendet), kategorien, heute)
    if auftrag is None:
        return {"antwort": "Das konnte ich nicht in eine Auswertung übersetzen. Frag nach Summen, Durchschnitt, "
                           "Verlauf, größten Buchungen oder einem Vergleich – mit Kategorie, Händler und Zeitraum.",
                "verstanden": None, "zeilen": [], "summe": None, "anzahl": 0}
    return ausfuehren(s, auftrag)
