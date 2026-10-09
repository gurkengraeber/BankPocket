"""CSV-Exporte von N26 und Revolut (erfundene Beispieldaten) und gemischte Zahlenformate."""
from datetime import date
from decimal import Decimal

from bankpocket.csv_import import parse_amount, parse_date, parse_transactions

N26 = """"Booking Date","Value Date","Partner Name","Partner Iban",Type,"Payment Reference","Account Name","Amount (EUR)","Original Amount","Original Currency","Exchange Rate"
2026-09-28,2026-09-28,Musterfirma AG,DE02100100100006820101,Income,Gehalt September,Hauptkonto,2500.00,,,
2026-09-15,2026-09-15,Streamflix GmbH,DE02120300000000202051,Direct Debit,Abo September,Hauptkonto,-12.99,,,
"""

N26_DEUTSCH = """"Buchungsdatum","Wertstellung","Partnername","Partner IBAN","Typ","Zahlungsreferenz","Kontoname","Betrag (EUR)"
2026-09-15,2026-09-15,Streamflix GmbH,DE02120300000000202051,Lastschrift,Abo September,Hauptkonto,"-1,012.99"
"""

REVOLUT = """Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance
CARD_PAYMENT,Current,2026-09-14 08:01:02,2026-09-15 10:23:45,Streamflix,-12.99,0.00,EUR,COMPLETED,987.01
TOPUP,Current,2026-09-20 09:00:00,2026-09-20 09:00:05,Top-Up by *1234,100.00,0.50,EUR,COMPLETED,1086.51
CARD_PAYMENT,Current,2026-09-21 12:00:00,,Bäckerei,-3.20,0.00,EUR,PENDING,
CARD_PAYMENT,Current,2026-09-22 12:00:00,2026-09-22 12:05:00,Laden,-5.00,0.00,EUR,REVERTED,
"""


def test_n26_export_mit_komma_wird_erkannt():
    # Trennzeichen „;“ ist die Voreinstellung der App – die Komma-Datei muss trotzdem laufen
    gehalt, abo = parse_transactions(N26.encode(), ";")
    assert (gehalt.buchungsdatum, gehalt.betrag, gehalt.gegenpartei) == (date(2026, 9, 28), Decimal("2500.00"), "Musterfirma AG")
    assert (gehalt.verwendungszweck, gehalt.iban_gegenpartei, gehalt.buchungstext) == (
        "Gehalt September", "DE02100100100006820101", "Income")
    assert (abo.betrag, abo.gegenpartei) == (Decimal("-12.99"), "Streamflix GmbH")


def test_n26_deutsche_spaltennamen_und_tausendertrenner_mit_komma():
    [t] = parse_transactions(N26_DEUTSCH.encode(), ";")
    assert (t.buchungsdatum, t.betrag, t.gegenpartei, t.buchungstext) == (
        date(2026, 9, 15), Decimal("-1012.99"), "Streamflix GmbH", "Lastschrift")


def test_revolut_export_gebuehr_abgezogen_und_ungebuchtes_uebersprungen():
    abo, aufladung = parse_transactions(REVOLUT.encode(), ",")
    assert (abo.buchungsdatum, abo.betrag, abo.gegenpartei, abo.saldo) == (
        date(2026, 9, 15), Decimal("-12.99"), "Streamflix", Decimal("987.01"))
    assert (aufladung.buchungsdatum, aufladung.betrag) == (date(2026, 9, 20), Decimal("99.50"))  # 100,00 minus 0,50 Gebühr


def test_zahlen_und_datum_in_beiden_schreibweisen():
    assert parse_amount("-1.234,56") == Decimal("-1234.56")
    assert parse_amount("1,234.56") == Decimal("1234.56")
    assert parse_amount("-12,5") == Decimal("-12.5")
    assert parse_amount("-12.50") == Decimal("-12.50")
    assert parse_date("15.09.2026 10:23") == date(2026, 9, 15)
    assert parse_date("2026-09-15T10:23:45") == date(2026, 9, 15)
