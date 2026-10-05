"""CSV-Import für Bank-Exporte (Standard: ING-Girokonto-Export).

Das ING-Format hat einen Metadaten-Block vor der Kopfzeile, Semikolon als
Trenner, deutsche Zahlen ("-1.234,56") und Datumsangaben (TT.MM.JJJJ).
Spaltennamen werden über Aliase erkannt, damit auch ähnliche Exporte
(z. B. Consorsbank) mit `--delimiter`/Aliasen laufen.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import Transaction

ALIASES = {
    "datum": ["buchung", "buchungstag", "buchungsdatum", "datum"],
    "gegenpartei": ["auftraggeber/empfänger", "auftraggeber/empfaenger", "empfänger", "sender / empfänger",
                    "sender/empfänger", "sender / empfaenger", "empfänger/auftraggeber", "zahlungsempfänger",
                    "name zahlungsbeteiligter", "beguenstigter/zahlungspflichtiger",
                    "begünstigter/zahlungspflichtiger", "gegenpartei"],
    "zweck": ["verwendungszweck"],
    "buchungstext": ["buchungstext", "umsatzart", "buchungsart"],
    "betrag": ["betrag", "betrag (eur)", "umsatz"],
    "iban": ["iban", "iban zahlungsbeteiligter", "kontonummer/iban"],
    "glaeubiger": ["gläubiger-id", "glaeubiger-id", "gläubigeridentifikationsnummer"],
    "mandat": ["mandatsreferenz", "mandat"],
    "saldo": ["saldo", "kontostand"],
}

_RE_CID = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{3}\d{8,})\b")
_RE_MREF = re.compile(r"Mandats?-?ref(?:erenz)?\.?:?\s*([A-Za-z0-9\-_/.]{3,})", re.I)
_RE_CID_LABEL = re.compile(r"Gl[aä]ubiger-?ID:?\s*([A-Z]{2}\d{2}[A-Z0-9]{3}\d{8,})", re.I)
_RE_IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\s?[A-Z0-9]{0,4})\b")


def parse_amount(text: str) -> Decimal:
    t = text.strip().replace("€", "").replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation as e:
        raise ValueError(f"Ungültiger Betrag: {text!r}") from e


def parse_date(text: str) -> date:
    t = text.strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Ungültiges Datum: {text!r}")


def extract_sepa_ids(zweck: str) -> tuple[str, str]:
    """Gläubiger-ID und Mandatsreferenz aus dem Verwendungszweck ziehen."""
    cid = _RE_CID_LABEL.search(zweck) or _RE_CID.search(zweck)
    mref = _RE_MREF.search(zweck)
    return (cid.group(1).upper() if cid else "", mref.group(1) if mref else "")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _find_header(lines: list[str], delimiter: str) -> int:
    for i, line in enumerate(lines):
        cells = [c.strip().strip('"').lower() for c in line.split(delimiter)]
        if any(c in ALIASES["datum"] for c in cells) and any(c in ALIASES["betrag"] for c in cells):
            return i
    raise ValueError("Keine Kopfzeile mit Datum- und Betrag-Spalte gefunden")


def load_transactions(path: str | Path, delimiter: str = ";") -> list[Transaction]:
    return parse_transactions(Path(path).read_bytes(), delimiter)


def parse_transactions(raw: bytes, delimiter: str = ";") -> list[Transaction]:
    text = _decode(raw)
    lines = text.splitlines()
    start = _find_header(lines, delimiter)
    reader = csv.reader(io.StringIO("\n".join(lines[start:])), delimiter=delimiter)
    raw_header = [h.strip() for h in next(reader)]
    header = [h.lower() for h in raw_header]

    def col(key: str) -> int | None:
        # Bei doppelten Spaltennamen (ING: "Währung" 2x) zählt das erste Vorkommen.
        for alias in ALIASES[key]:
            if alias in header:
                return header.index(alias)
        return None

    idx = {k: col(k) for k in ALIASES}
    out: list[Transaction] = []
    for row in reader:
        if not row or all(not c.strip() for c in row):
            continue

        def get(key: str) -> str:
            i = idx[key]
            return row[i].strip() if i is not None and i < len(row) else ""

        zweck = get("zweck")
        cid, mref = get("glaeubiger"), get("mandat")
        if not (cid and mref):
            cid2, mref2 = extract_sepa_ids(zweck)
            cid, mref = cid or cid2, mref or mref2
        iban = get("iban")
        if not iban:
            m = _RE_IBAN.search(zweck)
            iban = m.group(1).replace(" ", "") if m else ""
        out.append(Transaction(
            buchungsdatum=parse_date(get("datum")),
            betrag=parse_amount(get("betrag")),
            gegenpartei=get("gegenpartei"),
            verwendungszweck=zweck,
            iban_gegenpartei=iban.replace(" ", ""),
            glaeubiger_id=cid,
            mandatsreferenz=mref,
            saldo=parse_amount(get("saldo")) if get("saldo") else None,
            buchungstext=get("buchungstext")[:80],
            rohdaten=json.dumps(list(zip(raw_header, row)), ensure_ascii=False),
        ))
    return out


# ---------- Depotübersicht (z. B. Consorsbank „Depotübersicht … Kompakt“) ----------
DEPOT_SPALTEN = {
    "name": ["name", "bezeichnung", "wertpapier"],
    "symbol": ["isin", "wkn"],
    "menge": ["stück/nominal", "stueck/nominal", "stück", "anzahl", "bestand"],
    "einstand": ["einstandskurs inkl. nk", "einstandskurs", "kaufkurs"],
    "kurs": ["kurs", "aktueller kurs"],
    "wert": ["gesamtwert", "kurswert", "wert"],
}
_RE_EXPORTDATUM = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")


def parse_depot(raw: bytes, delimiter: str = ";") -> dict | None:
    """Eine Depotübersicht lesen: {"datum", "positionen": [{name, symbol, menge, kurs, einstand, wert}]}.
    None, wenn die Datei keine Positionsliste ist (dann ist es ein normaler Kontoauszug)."""
    lines = _decode(raw).splitlines()
    kopf = None
    for i, line in enumerate(lines):
        zellen = [c.strip().strip('"').lower() for c in line.split(delimiter)]
        if (any(c in DEPOT_SPALTEN["menge"] for c in zellen) and any(c in DEPOT_SPALTEN["wert"] for c in zellen)
                and any(c in DEPOT_SPALTEN["symbol"] for c in zellen)):
            kopf = i
            break
    if kopf is None:
        return None
    reader = csv.reader(io.StringIO("\n".join(lines[kopf:])), delimiter=delimiter)
    header = [h.strip().lower() for h in next(reader)]

    def spalte(key: str) -> int | None:
        return next((header.index(a) for a in DEPOT_SPALTEN[key] if a in header), None)

    idx = {k: spalte(k) for k in DEPOT_SPALTEN}
    positionen = []
    for row in reader:
        def get(key: str) -> str:
            i = idx[key]
            return row[i].strip() if i is not None and i < len(row) else ""
        if not get("symbol") or not get("menge"):
            continue
        try:
            menge, wert = parse_amount(get("menge")), parse_amount(get("wert"))
            kurs = parse_amount(get("kurs")) if get("kurs") else None
            einstand = parse_amount(get("einstand")) if get("einstand") else None
        except ValueError:
            continue
        positionen.append({"name": get("name") or get("symbol"), "symbol": get("symbol"), "menge": menge, "kurs": kurs,
                           "einstand": einstand, "wert": wert})
    if not positionen:
        return None
    # Das Exportdatum steht im Kopf der Datei (z. B. „03.10.2026, 19:25:34“)
    datum = None
    for line in lines[:kopf]:
        m = _RE_EXPORTDATUM.search(line)
        if m:
            datum = parse_date(m.group(1))
            break
    return {"datum": datum, "positionen": positionen}
