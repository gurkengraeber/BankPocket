"""Gemeinsame Typen für alle Datenquellen."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..models import Transaction


@dataclass
class FetchedHolding:
    symbol: str  # ISIN
    name: str
    menge: Decimal
    kurs: Decimal | None
    wert: Decimal
    datum: date
    einstand: Decimal | None = None  # durchschnittlicher Kaufkurs je Stück, falls die Quelle ihn nennt
    kurse: list | None = None  # Kursverlauf als [(Tag, Kurs)], falls die Quelle ihn liefert


@dataclass
class FetchedAccount:
    kontonummer: str
    name: str
    typ: str  # giro | spar | depot | kreditkarte
    iban: str | None = None
    unterkonto: str | None = None
    waehrung: str = "EUR"
    saldo: Decimal | None = None
    saldo_datum: date | None = None
    transaktionen: list[Transaction] = field(default_factory=list)
    holdings: list[FetchedHolding] | None = None  # None = kein Depot


@dataclass
class FetchResult:
    konten: list[FetchedAccount]
    client_data: bytes | None = None  # Sitzungsdaten, die beim nächsten Abruf wiederverwendet werden
    tan_verfahren: str | None = None
    tan_verfahren_name: str | None = None
    tan_medium: str | None = None
    freigabe_erfolgt: bool = False  # starke Authentifizierung durchgeführt
    kurse: dict[str, list] | None = None  # Kursverläufe {ISIN: [(Tag, Kurs)]} für Wertpapiere anderer Depots


class FetchError(Exception):
    """Fehler mit verständlicher Meldung für die Oberfläche."""

    def __init__(self, meldung: str, client_data: bytes | None = None):
        super().__init__(meldung)
        self.meldung = meldung
        self.client_data = client_data


class PinFalsch(FetchError):
    pass


class ZugangGesperrt(FetchError):
    pass


class FreigabeNoetig(FetchError):
    pass


class AuswahlNoetig(FetchError):
    pass


class Abgebrochen(FetchError):
    pass


class Interaktion:
    """Austausch zwischen einem laufenden Abruf (Hintergrund-Thread) und der Web-Oberfläche.

    Der Abruf meldet seinen Zustand (z. B. „Bitte in der App freigeben“), die Oberfläche fragt ihn
    regelmäßig ab und kann Eingaben zurückgeben (TAN, gewähltes TAN-Verfahren, „habe freigegeben“).
    """

    def __init__(self, interaktiv: bool):
        self.interaktiv = interaktiv
        self.abbruch = threading.Event()
        self._eingaben: queue.Queue[dict] = queue.Queue()
        self._lock = threading.Lock()
        self._zustand: dict = {"phase": "start", "text": "Starte …"}

    def melden(self, phase: str, text: str = "", **extra) -> None:
        with self._lock:
            self._zustand = {"phase": phase, "text": text, **extra}

    def zustand(self) -> dict:
        with self._lock:
            return dict(self._zustand)

    def eingabe(self, daten: dict) -> None:
        self._eingaben.put(daten)

    def abbrechen(self) -> None:
        self.abbruch.set()
        self._eingaben.put({"abbrechen": True})

    def warte_auf_eingabe(self, timeout: float) -> dict | None:
        try:
            daten = self._eingaben.get(timeout=max(timeout, 0))
        except queue.Empty:
            return None
        if daten.get("abbrechen"):
            raise Abgebrochen("Abruf abgebrochen")
        return daten

    def warten(self, sekunden: float) -> None:
        """Unterbrechbares Warten (Abbruch über die Oberfläche)."""
        if self.abbruch.wait(sekunden):
            raise Abgebrochen("Abruf abgebrochen")
