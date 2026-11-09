"""Splitwise: wer wem was schuldet, als virtuelles Konto.

Saldo = Summe deiner Bilanzen mit allen Freunden (positiv: man schuldet dir Geld). Jede geteilte Ausgabe
wird mit deinem Anteil gebucht (gezahlt minus eigener Anteil) – so stimmen Ausgaben-Analysen auch dann,
wenn du für andere mitbezahlt hast.

API-Schlüssel: https://secure.splitwise.com/apps → „Register your application“ → „API key“.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import httpx

from ..contracts import categorize
from ..models import Transaction
from .base import FetchedAccount, FetchError, FetchResult, Interaktion, PinFalsch

BASIS = "https://secure.splitwise.com/api/v3.0"
SEITE = 100
CENT = Decimal("0.01")
KATEGORIEN = {
    "Groceries": "Lebensmittel", "Dining out": "Restaurants", "Liquor": "Restaurants", "Rent": "Miete",
    "Mortgage": "Miete", "Electricity": "Strom", "Heat/gas": "Strom", "Gas/fuel": "Tanken", "Parking": "Mobilität",
    "Bus/train": "Mobilität", "Taxi": "Mobilität", "Car": "Mobilität", "Plane": "Reisen", "Hotel": "Reisen",
    "Medical expenses": "Gesundheit", "Clothing": "Shopping", "Household supplies": "Shopping",
    "Electronics": "Shopping", "Furniture": "Shopping", "TV/Phone/Internet": "Internet & Telefon",
    "Insurance": "Versicherung", "Sports": "Fitness",
}


class SplitwiseSource:
    def __init__(self, *, pin: str, interaktion: Interaktion, letzte_buchung: dict[str, date] | None = None,
                 heute: date | None = None, http: httpx.Client | None = None, **_andere):
        self.key = pin
        self.ia = interaktion
        self.letzte_buchung = letzte_buchung or {}
        self.heute = heute or date.today()
        self.http = http or httpx.Client(timeout=20)

    def _get(self, pfad: str, params: dict | None = None) -> dict:
        r = self.http.get(f"{BASIS}{pfad}", params=params, headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code == 401:
            raise PinFalsch("Splitwise lehnt den API-Schlüssel ab – bitte neu eintragen. "
                            "Automatische Abrufe sind gestoppt.")
        if r.status_code >= 400:
            raise FetchError(f"Splitwise antwortet mit Fehler {r.status_code}.")
        return r.json()

    def abrufen(self) -> FetchResult:
        try:
            self.ia.melden("abruf", "Lade Splitwise …")
            meine_id = self._get("/get_current_user")["user"]["id"]
            freunde = self._get("/get_friends").get("friends", [])
            saldo = sum((Decimal(str(b["amount"])) for f in freunde for b in f.get("balance") or []
                         if b.get("currency_code") == "EUR"), Decimal(0))
            letzte = self.letzte_buchung.get("splitwise")
            # Ausgaben können nachträglich geändert werden – darum einen Monat Überlappung
            start = letzte - timedelta(days=30) if letzte else self.heute - timedelta(days=730)
            buchungen, offset = [], 0
            while True:
                seite = self._get("/get_expenses", {"dated_after": start.isoformat(), "limit": SEITE,
                                                    "offset": offset}).get("expenses", [])
                buchungen += [t for t in (self._buchung(e, meine_id) for e in seite) if t]
                if len(seite) < SEITE:
                    break
                offset += SEITE
        except httpx.HTTPError as e:
            raise FetchError(f"Splitwise nicht erreichbar: {e}") from e
        konto = FetchedAccount(kontonummer="splitwise", name="Splitwise", typ="virtuell", saldo=saldo.quantize(CENT),
                               saldo_datum=self.heute, transaktionen=buchungen)
        return FetchResult(konten=[konto])

    @staticmethod
    def _buchung(e: dict, meine_id: int) -> Transaction | None:
        if e.get("currency_code", "EUR") != "EUR":
            return None
        def uid(u: dict):
            return u.get("user_id") or (u.get("user") or {}).get("id")
        ich = next((u for u in e.get("users", []) if uid(u) == meine_id), None)
        netto = Decimal(str((ich or {}).get("net_balance") or 0)).quantize(CENT)
        geloescht = bool(e.get("deleted_at"))
        if not geloescht and (ich is None or netto == 0):
            return None
        andere = [((u.get("user") or {}).get("first_name") or "").strip() for u in e.get("users", []) if uid(u) != meine_id]
        zahlung = bool(e.get("payment"))
        return Transaction(
            buchungsdatum=date.fromisoformat(str(e["date"])[:10]), betrag=netto,
            gegenpartei=", ".join(n for n in andere if n) or "Splitwise", verwendungszweck=e.get("description") or "",
            buchungstext="Ausgleich" if zahlung else "Geteilte Ausgabe",
            # immer eine Ausgaben-Kategorie: +40 heißt „andere schulden dir ihren Anteil“, nicht Einnahme
            kategorie="Sonstiges" if zahlung else KATEGORIEN.get((e.get("category") or {}).get("name", ""))
            or categorize(e.get("description") or "", "", "ausgabe"),
            extern_id=f"splitwise-{e['id']}", geloescht=geloescht, rohdaten=json.dumps(e, default=str),
        )
