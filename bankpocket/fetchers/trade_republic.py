"""Trade Republic über pytr (inoffizielle Schnittstelle): Verrechnungskonto mit Umsätzen und Depot.

Anmeldung wie im Web: Handynummer + 4-stellige PIN, dann Bestätigung in der Trade-Republic-App.
Die Sitzung wird verschlüsselt gespeichert und wiederverwendet; läuft sie ab, ist eine neue Anmeldung
nötig. Hintergrund-Abrufe fordern diese bewusst nicht selbst an (die App würde sonst zu zufälligen
Zeiten nachfragen) – stattdessen gibt es einen Hinweis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from ..models import Transaction
from .base import (FetchedAccount, FetchedHolding, FetchError, FetchResult, FreigabeNoetig, Interaktion, PinFalsch,
                   ZugangGesperrt)
from .fints_source import iban_gueltig

log = logging.getLogger(__name__)

CENT = Decimal("0.01")
ERSTABRUF_TAGE = 730
EMPFANG_TIMEOUT = 30  # Sekunden pro Timeline-Seite
FREMDE_HOECHSTENS = 40  # so viele Wertpapiere aus anderen Depots je Abruf nachschlagen
STORNIERT = {"CANCELED", "CANCELLED", "FAILED", "REJECTED", "DECLINED"}
# Ein- und Auszahlungen zwischen deinen Konten – keine Einnahmen/Ausgaben
UMBUCHUNG = {"INCOMING_TRANSFER", "INCOMING_TRANSFER_DELEGATION", "OUTGOING_TRANSFER", "OUTGOING_TRANSFER_DELEGATION",
             "PAYMENT_INBOUND", "PAYMENT_INBOUND_SEPA_DIRECT_DEBIT", "PAYMENT_INBOUND_GOOGLE_PAY",
             "PAYMENT_INBOUND_APPLE_PAY", "PAYMENT_INBOUND_CREDIT_CARD", "PAYMENT_OUTBOUND",
             "BANK_TRANSACTION_INCOMING", "BANK_TRANSACTION_OUTGOING", "ACCOUNT_TRANSFER_INCOMING",
             "ACCOUNT_TRANSFER_OUTGOING"}
SPAREN = {"SAVINGS_PLAN_EXECUTED", "SAVINGS_PLAN_INVOICE_CREATED", "TRADE_INVOICE", "ORDER_EXECUTED",
          "TRADING_SAVINGSPLAN_EXECUTED", "TRADING_TRADE_EXECUTED", "BENEFITS_SAVEBACK_EXECUTION",
          "BENEFITS_SPARE_CHANGE_EXECUTION", "PRIVATE_MARKETS_ORDER_CREATED", "SAVEBACK_AGGREGATE",
          "SPARE_CHANGE_AGGREGATE", "PRIVATE_MARKET_FUND_TRADE_EXECUTED"}
ERTRAEGE = {"INTEREST_PAYOUT", "INTEREST_PAYOUT_CREATED"}
DIVIDENDEN = {"CREDIT", "SSP_CORPORATE_ACTION_INVOICE_CASH", "SSP_CORPORATE_ACTION_CASH",
              "SSP_CORPORATE_ACTION_CASH_NON_DIVIDEND"}


def tr_umsatz(e: dict) -> Transaction | None:
    """Ein Timeline-Ereignis als Buchung auf dem Verrechnungskonto."""
    wert = (e.get("amount") or {}).get("value")
    if wert is None or not e.get("timestamp") or str(e.get("status", "")).upper() in STORNIERT:
        return None
    typ = str(e.get("eventType") or "").upper()
    kategorie = "Sparen" if typ in SPAREN else "Zinsen" if typ in ERTRAEGE else "Dividenden" if typ in DIVIDENDEN else ""
    return Transaction(
        buchungsdatum=date.fromisoformat(e["timestamp"][:10]), betrag=Decimal(str(wert)).quantize(CENT),
        gegenpartei=e.get("title") or "", verwendungszweck=e.get("subtitle") or "",
        buchungstext=e.get("eventType") or "", kategorie=kategorie, intern=typ in UMBUCHUNG,
        extern_id=f"tr-{e.get('id')}", rohdaten=json.dumps(e, default=str),
    )


def _pytr_api(**kwargs):
    from pytr.api import TradeRepublicApi
    return TradeRepublicApi(**kwargs)


class TradeRepublicSource:
    def __init__(self, *, login: str, pin: str, interaktion: Interaktion, client_data: bytes | None = None,
                 letzte_buchung: dict[str, date] | None = None, heute: date | None = None,
                 bei_freigabe: Callable[[str], None] | None = None, arbeitsordner: Path | str = "data",
                 verbindung_id: int = 0, api_factory: Callable | None = None,
                 fremde_wertpapiere: list[str] | None = None, **_andere):
        self.telefon, self.pin = login, pin
        self.ia = interaktion
        self.client_data = client_data
        self.letzte_buchung = letzte_buchung or {}
        self.heute = heute or date.today()
        self.bei_freigabe = bei_freigabe
        self.cookie_datei = Path(arbeitsordner) / f"tr-{verbindung_id}.cookies"
        self.api_factory = api_factory or _pytr_api
        self.angemeldet = False
        self.kurse: dict[str, list] = {}
        # ISINs aus Depots anderer Banken, die selbst keinen Kursverlauf liefern (ING, Consorsbank)
        self.fremde_wertpapiere = fremde_wertpapiere or []
        self.kurse_fremd: dict[str, list] = {}

    # ---------- Ablauf ----------
    def abrufen(self) -> FetchResult:
        import requests

        try:
            if self.client_data:
                self.cookie_datei.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.cookie_datei, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(self.client_data)
            self.ia.melden("verbinde", "Verbinde mit Trade Republic …")
            tr = self.api_factory(phone_no=self.telefon, pin=self.pin, locale="de", save_cookies=True,
                                  cookies_file=str(self.cookie_datei), use_v2_login=True)
            # pytr hält Abo-Zustand auf Klassenebene – pro Abruf frisch beginnen
            tr.subscriptions, tr._previous_responses = {}, {}
            if not (self.client_data and tr.resume_websession()):
                self._anmelden(tr)
            self.ia.melden("abruf", "Lade Depot und Umsätze …")
            positionen, cash, ereignisse, self.kurse = asyncio.run(self._laden(tr))
            tr.save_websession()
            sitzung = self.cookie_datei.read_bytes() if self.cookie_datei.exists() else None
            return FetchResult(konten=self._konten(positionen, cash, ereignisse), client_data=sitzung,
                               freigabe_erfolgt=self.angemeldet, kurse=self.kurse_fremd or None)
        except FetchError:
            raise
        except TimeoutError as e:
            raise FreigabeNoetig("Die Anmeldung wurde nicht in der Trade-Republic-App bestätigt.") from e
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status == 429:
                raise ZugangGesperrt("Trade Republic meldet zu viele Versuche – bitte später erneut anmelden.") from e
            raise FetchError(f"Trade Republic antwortet mit Fehler {status}.") from e
        except ValueError as e:  # pytr meldet Anmeldefehler als ValueError
            if "Too many" in str(e):
                raise ZugangGesperrt("Trade Republic meldet zu viele Versuche – bitte später erneut anmelden.") from e
            raise FetchError(f"Trade Republic: {e}") from e
        except (OSError, asyncio.TimeoutError) as e:
            raise FetchError(f"Trade Republic nicht erreichbar: {e}") from e
        finally:
            self.cookie_datei.unlink(missing_ok=True)

    def _anmelden(self, tr) -> None:
        import requests

        if not self.ia.interaktiv:
            raise FreigabeNoetig("Die Anmeldung bei Trade Republic ist abgelaufen – bitte in BankPocket neu anmelden.")
        try:
            sekunden = tr.initiate_weblogin()
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) in (400, 401, 403):
                raise PinFalsch("Trade Republic lehnt Handynummer oder PIN ab. Automatische Abrufe sind gestoppt.") from e
            raise
        if tr.weblogin_needs_authenticator:
            self.ia.melden("tan", "Gib den 6-stelligen Code aus deiner Authenticator-App ein (die App, die du bei "
                                  "Trade Republic für die Zwei-Faktor-Anmeldung eingerichtet hast, z. B. Google "
                                  "Authenticator oder dein Passwortmanager). In der Trade-Republic-App kommt dafür "
                                  "keine Meldung.")
            eingabe = self.ia.warte_auf_eingabe(sekunden)
            code = str((eingabe or {}).get("tan", "")).strip()
            if not code:
                raise FreigabeNoetig("Es wurde kein Code eingegeben.")
            tr.complete_weblogin(code)
            self._app_bestaetigung_abwarten(tr, sekunden)
        else:
            self.ia.melden("freigabe", "Bitte bestätige die Anmeldung in der Trade-Republic-App.",
                           manuell_bestaetigen=False, sekunden=sekunden)
            tr.complete_weblogin()  # wartet, bis du in der App bestätigst (oder die Frist abläuft)
        self.angemeldet = True
        self.ia.melden("abruf", "Angemeldet – lade Daten …")

    def _app_bestaetigung_abwarten(self, tr, sekunden: int) -> None:
        """Nach dem Authenticator-Code kann Trade Republic zusätzlich die Bestätigung in der App verlangen. Ohne sie
        ist die Sitzung nicht gültig und der Abruf endet mit Fehler 401."""
        stand_lesen = getattr(tr, "_get_weblogin_process", None)
        if stand_lesen is None:
            return
        stand = stand_lesen(quiet=True) or {}
        log.info("Trade Republic nach dem Code: Status %s, verlangt %s", stand.get("status"), stand.get("requiredAction"))
        if stand.get("status") != "PENDING":
            return
        self.ia.melden("freigabe", "Code angenommen – bitte bestätige die Anmeldung jetzt noch in der Trade-Republic-App.",
                       manuell_bestaetigen=False, sekunden=sekunden)
        tr._await_weblogin_confirmation()  # wartet, bis du in der App bestätigst (oder die Frist abläuft)
        tr.save_websession()

    # ---------- Daten ----------
    async def _laden(self, tr):
        try:
            positionen, cash = await self._portfolio(tr)
            ereignisse = await self._timeline(tr, self._startdatum())
            try:
                kurse = await self._kursverlaeufe(tr, positionen)
            except Exception:  # noqa: BLE001 – der Kursverlauf ist Beiwerk und darf den Abruf nie scheitern lassen
                log.warning("Kursverläufe konnten nicht geladen werden", exc_info=True)
                kurse = {}
            try:
                eigene = {p.get("instrumentId") for p in positionen}
                self.kurse_fremd = await self._fremde_kurse(tr, [i for i in self.fremde_wertpapiere if i not in eigene])
            except Exception:  # noqa: BLE001 – ebenfalls nur Beiwerk
                log.warning("Kursverläufe für fremde Depots konnten nicht geladen werden", exc_info=True)
            return positionen, cash, ereignisse, kurse
        finally:
            await tr.close()

    async def _portfolio(self, tr) -> tuple[list[dict], list[dict]]:
        from pytr.portfolio import Portfolio

        pf = Portfolio(tr, lang="de")
        await pf.portfolio_loop()
        return pf.positions, pf.cash

    async def _kursverlaeufe(self, tr, positionen: list[dict]) -> dict[str, list[tuple[date, Decimal]]]:
        """Tageskurse des letzten Jahres je Position – für den Wertverlauf einzelner ETFs und Aktien."""
        abos = {}
        for p in positionen:
            if p.get("exchangeIds") and Decimal(str(p.get("netSize") or 0)) > 0:
                abo = await tr.subscribe({"type": "aggregateHistoryLight", "range": "1y",
                                          "id": f"{p['instrumentId']}.{p['exchangeIds'][0]}"})
                abos[abo] = p
        out: dict[str, list[tuple[date, Decimal]]] = {}
        while abos:
            try:
                abo_id, _, antwort = await asyncio.wait_for(tr.recv(), 8)
            except asyncio.TimeoutError:
                break
            except Exception as e:  # noqa: BLE001 – pytr meldet eine abgelehnte Anfrage als Fehler mit der Abo-Nummer
                abgelehnt = str(e.args[0]) if e.args else None
                if abgelehnt not in abos:
                    raise
                log.info("Kein Kursverlauf für %s", abos.pop(abgelehnt).get("instrumentId"))
                continue
            if abo_id not in abos:
                continue
            await tr.unsubscribe(abo_id)
            p = abos.pop(abo_id)
            punkte: dict[date, Decimal] = {}
            for a in (antwort or {}).get("aggregates", []) if isinstance(antwort, dict) else []:
                try:
                    tag = datetime.fromtimestamp(int(a["time"]) / 1000, tz=timezone.utc).date()
                    punkte[tag] = Decimal(str(a["close"]))
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    continue
            if not punkte:
                continue
            # Anleihen notieren in Prozent – auf dieselbe Einheit wie den aktuellen Kurs bringen
            letzter, aktuell = punkte[max(punkte)], Decimal(str(p.get("price") or 0))
            if aktuell and 50 < letzter / aktuell < 200:
                punkte = {t: k / 100 for t, k in punkte.items()}
            out[p["instrumentId"]] = sorted(punkte.items())
        return out

    async def _fremde_kurse(self, tr, isins: list[str]) -> dict[str, list[tuple[date, Decimal]]]:
        """Kursverläufe für Wertpapiere, die in einem anderen Depot liegen: erst den Handelsplatz erfragen."""
        abos = {}
        for isin in isins[:FREMDE_HOECHSTENS]:
            abos[await tr.subscribe({"type": "instrument", "id": isin})] = isin
        gefunden = []
        while abos:
            try:
                abo_id, _, antwort = await asyncio.wait_for(tr.recv(), 8)
            except asyncio.TimeoutError:
                break
            except Exception as e:  # noqa: BLE001 – unbekanntes Wertpapier: Fehler mit der Abo-Nummer
                abgelehnt = str(e.args[0]) if e.args else None
                if abgelehnt not in abos:
                    raise
                log.info("Trade Republic kennt %s nicht", abos.pop(abgelehnt))
                continue
            if abo_id not in abos:
                continue
            await tr.unsubscribe(abo_id)
            isin = abos.pop(abo_id)
            boersen = (antwort or {}).get("exchangeIds") if isinstance(antwort, dict) else None
            if boersen:
                gefunden.append({"instrumentId": isin, "exchangeIds": boersen, "netSize": 1})
        return await self._kursverlaeufe(tr, gefunden) if gefunden else {}

    async def _timeline(self, tr, start: date) -> list[dict]:
        ereignisse: list[dict] = []
        await tr.timeline_transactions()
        while True:
            abo_id, abo, antwort = await asyncio.wait_for(tr.recv(), EMPFANG_TIMEOUT)
            await tr.unsubscribe(abo_id)
            if abo.get("type") != "timelineTransactions":
                continue
            weiter = True
            for e in antwort.get("items", []):
                if date.fromisoformat(e["timestamp"][:10]) < start:
                    weiter = False
                    break
                ereignisse.append(e)
            nach = (antwort.get("cursors") or {}).get("after")
            if not (weiter and nach):
                return ereignisse
            await tr.timeline_transactions(nach)

    def _startdatum(self) -> date:
        letzte = self.letzte_buchung.get("tr-cash")
        if letzte:
            return letzte - timedelta(days=14)
        return self.heute - timedelta(days=ERSTABRUF_TAGE if self.ia.interaktiv else 89)

    def _konten(self, positionen: list[dict], cash: list[dict] | dict, ereignisse: list[dict]) -> list[FetchedAccount]:
        if isinstance(cash, dict):
            cash = [cash]
        eur = next((c for c in cash or [] if c.get("currencyId", "EUR") == "EUR"), None)
        nummer = str((eur or {}).get("accountNumber") or "").replace(" ", "")
        verrechnung = FetchedAccount(
            kontonummer="tr-cash", iban=nummer if iban_gueltig(nummer) else None, name="Verrechnungskonto",
            typ="giro", saldo=Decimal(str(eur["amount"])).quantize(CENT) if eur else None, saldo_datum=self.heute,
            transaktionen=[t for t in (tr_umsatz(e) for e in ereignisse) if t])
        holdings = []
        for p in positionen:
            try:
                einstand = Decimal(str(p["averageBuyIn"])) if p.get("averageBuyIn") not in (None, "") else None
            except ArithmeticError:
                einstand = None
            try:
                holdings.append(FetchedHolding(
                    symbol=p.get("instrumentId") or p.get("isin", ""), name=p.get("name") or p.get("instrumentId", ""),
                    menge=Decimal(str(p["netSize"])), kurs=Decimal(str(p["price"])),
                    wert=Decimal(str(p["netValue"])).quantize(CENT), datum=self.heute, einstand=einstand,
                    kurse=self.kurse.get(p.get("instrumentId"))))
            except (KeyError, ArithmeticError, ValueError):
                log.warning("Position ohne Kurs übersprungen: %s", p.get("instrumentId"))
        depot = FetchedAccount(kontonummer="tr-depot", name="Depot", typ="depot", saldo_datum=self.heute,
                               saldo=sum((h.wert for h in holdings), Decimal(0)), holdings=holdings)
        return [verrechnung, depot]
