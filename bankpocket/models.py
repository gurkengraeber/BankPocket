from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

MONATE = {"monatlich": 1, "quartalsweise": 3, "halbjaehrlich": 6, "jaehrlich": 12}
WOCHEN_TAGE = {"woechentlich": 7, "zweiwoechentlich": 14, "halbmonatlich": 15, "vierwoechentlich": 28}  # Rhythmen in Tagen statt Monaten


def monatsbetrag(betrag: Decimal, turnus: str) -> Decimal:
    """Betrag auf einen Monat umgerechnet – wöchentlich sind das 52/12, alle zwei Wochen 26/12 Zahlungen."""
    if turnus == "halbmonatlich":
        return abs(betrag) * 2
    if turnus in WOCHEN_TAGE:
        return abs(betrag) * Decimal(365) / Decimal(12 * WOCHEN_TAGE[turnus])
    return abs(betrag) / MONATE[turnus]


@dataclass(frozen=True)
class Transaction:
    buchungsdatum: date
    betrag: Decimal
    gegenpartei: str = ""
    verwendungszweck: str = ""
    iban_gegenpartei: str = ""
    glaeubiger_id: str = ""
    mandatsreferenz: str = ""
    saldo: Decimal | None = None  # Kontostand nach der Buchung, falls der Export ihn liefert
    rohdaten: str = field(default="", compare=False)  # Originalzeile als JSON (für spätere Neu-Auswertung)
    buchungstext: str = field(default="", compare=False)  # z. B. „Lastschrift“, „Gehalt/Rente“
    kategorie: str = field(default="", compare=False)  # Vorgabe der Quelle oder des Nutzers
    intern: bool = field(default=False, compare=False)  # Umbuchung zwischen eigenen Konten
    extern_id: str = field(default="", compare=False)  # stabile ID der Quelle (Splitwise, Trade Republic)
    geloescht: bool = field(default=False, compare=False)  # in der Quelle gelöscht → hier entfernen


@dataclass
class Contract:
    name: str
    kategorie: str
    turnus: str  # monatlich | quartalsweise | halbjaehrlich | jaehrlich
    erwarteter_betrag: Decimal  # zuletzt gezahlter Betrag
    naechste_faelligkeit: date
    typ: str  # ausgabe | einnahme
    status: str  # aktiv | ueberfaellig | inaktiv
    quelle: str = "auto"
    schluessel: str = ""  # stabile Kennung der Gruppe, damit Nutzeränderungen Re-Imports überleben
    tage_ueberfaellig: int = 0
    methode: str = ""  # sepa | gegenpartei | paypal
    vorkommen: int = 0
    sicherheit: int = 0  # 0–100: wie sicher die Erkennung ist (für die Nachfrage beim Nutzer)
    betrag_gestiegen: bool = False
    vorheriger_betrag: Decimal | None = None
    transaktionen: list[Transaction] = field(default_factory=list, repr=False)

    @property
    def monatlich(self) -> Decimal:
        """Betrag auf einen Monat umgerechnet (für Ø Ausgaben/Monat)."""
        return monatsbetrag(self.erwarteter_betrag, self.turnus)
