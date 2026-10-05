"""Binance: Guthaben über einen read-only API-Schlüssel, bewertet in Euro.

Schlüssel in Binance anlegen: Profil → API-Verwaltung → „System generated“, nur „Lesen“ erlauben
(kein Handel, keine Auszahlung), optional auf die IP deines Heimanschlusses beschränken.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from .base import FetchedAccount, FetchedHolding, FetchError, FetchResult, Interaktion, PinFalsch

log = logging.getLogger(__name__)

BASIS = "https://api.binance.com"
BRUECKEN = ("USDT", "BTC", "USDC", "FDUSD", "BNB", "ETH")
SCHLUESSEL_UNGUELTIG = {-2008, -2014, -2015, -1022}
NAMEN = {"BTC": "Bitcoin", "ETH": "Ethereum", "BNB": "BNB", "SOL": "Solana", "XRP": "XRP", "ADA": "Cardano",
         "DOT": "Polkadot", "DOGE": "Dogecoin", "USDT": "Tether", "USDC": "USD Coin", "EUR": "Euro",
         "LINK": "Chainlink", "AVAX": "Avalanche", "MATIC": "Polygon", "POL": "Polygon", "LTC": "Litecoin"}
CENT = Decimal("0.01")


def eur_kurs(asset: str, preise: dict[str, Decimal], _tief: bool = False) -> Decimal | None:
    """Euro-Preis eines Assets: direkt, invers (EURUSDT) oder über eine Brücke (z. B. SOL→USDT→EUR)."""
    if asset == "EUR":
        return Decimal(1)
    if f"{asset}EUR" in preise:
        return preise[f"{asset}EUR"]
    if preise.get(f"EUR{asset}"):
        return Decimal(1) / preise[f"EUR{asset}"]
    if _tief:
        return None
    for b in BRUECKEN:
        if b != asset and f"{asset}{b}" in preise:
            kurs = eur_kurs(b, preise, _tief=True)
            if kurs is not None:
                return preise[f"{asset}{b}"] * kurs
    return None


def _code(r: httpx.Response):
    try:
        daten = r.json()
    except ValueError:
        return None
    return daten.get("code") if isinstance(daten, dict) else None


class BinanceSource:
    def __init__(self, *, login: str, pin: str, interaktion: Interaktion, heute: date | None = None,
                 http: httpx.Client | None = None, uhr=time.time, **_andere):
        self.key, self.secret = login, pin
        self.ia = interaktion
        self.heute = heute or date.today()
        self.http = http or httpx.Client(timeout=20)
        self.uhr = uhr
        self._versatz = 0

    def _antwort(self, r: httpx.Response):
        if r.status_code == 401 or _code(r) in SCHLUESSEL_UNGUELTIG:
            raise PinFalsch("Binance lehnt den API-Schlüssel ab – bitte Schlüssel, Secret und Leserecht prüfen. "
                            "Automatische Abrufe sind gestoppt.")
        if r.status_code >= 400:
            try:
                meldung = r.json().get("msg")
            except ValueError:
                meldung = None
            raise FetchError(f"Binance: {meldung or f'Fehler {r.status_code}'}")
        return r.json()

    def _signiert(self, methode: str, pfad: str, params: dict | None = None, nochmal: bool = True):
        mit_zeit = {**(params or {}), "timestamp": int(self.uhr() * 1000) + self._versatz, "recvWindow": 10000}
        query = urlencode(mit_zeit)
        signatur = hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        r = self.http.request(methode, f"{BASIS}{pfad}?{query}&signature={signatur}",
                              headers={"X-MBX-APIKEY": self.key})
        if nochmal and _code(r) == -1021:  # Serveruhr weicht ab → Versatz übernehmen und einmal wiederholen
            server = self.http.get(f"{BASIS}/api/v3/time").json()["serverTime"]
            self._versatz = server - int(self.uhr() * 1000)
            return self._signiert(methode, pfad, params, nochmal=False)
        return self._antwort(r)

    def _optional(self, methode: str, pfad: str, params: dict | None = None) -> object | None:
        """Zusatzguthaben (Funding, Earn): fehlende Berechtigung ist kein Grund, den Abruf abzubrechen."""
        try:
            return self._signiert(methode, pfad, params)
        except PinFalsch:
            raise
        except FetchError as e:
            log.info("Binance %s nicht verfügbar: %s", pfad, e)
            return None

    def _seiten(self, pfad: str) -> dict | None:
        """Alle Zeilen einer Simple-Earn-Liste (Binance liefert sonst nur 10 pro Seite)."""
        zeilen: list = []
        for seite in range(1, 51):
            antwort = self._optional("GET", pfad, {"current": seite, "size": 100})
            if antwort is None:
                return None if seite == 1 else {"rows": zeilen}
            neu = antwort.get("rows", [])
            zeilen += neu
            if not neu or len(zeilen) >= int(antwort.get("total") or 0):
                break
        return {"rows": zeilen}

    def abrufen(self) -> FetchResult:
        try:
            self.ia.melden("abruf", "Lade Guthaben von Binance …")
            preise = {p["symbol"]: Decimal(p["price"])
                      for p in self._antwort(self.http.get(f"{BASIS}/api/v3/ticker/price"))}
            menge: dict[str, Decimal] = defaultdict(Decimal)
            for b in self._signiert("GET", "/api/v3/account", {"omitZeroBalances": "true"}).get("balances", []):
                menge[b["asset"]] += Decimal(b["free"]) + Decimal(b["locked"])
            for b in self._optional("POST", "/sapi/v1/asset/get-funding-asset") or []:
                menge[b["asset"]] += sum(Decimal(b.get(k) or 0) for k in ("free", "locked", "freeze", "withdrawing"))
            flexibel = self._seiten("/sapi/v1/simple-earn/flexible/position")
            for r in (flexibel or {}).get("rows", []):
                menge[r["asset"]] += Decimal(r["totalAmount"])
            for r in (self._seiten("/sapi/v1/simple-earn/locked/position") or {}).get("rows", []):
                menge[r["asset"]] += Decimal(r["amount"])
        except httpx.HTTPError as e:
            raise FetchError(f"Binance nicht erreichbar: {e}") from e

        holdings = []
        for asset, anzahl in sorted(menge.items()):
            if asset.startswith("LD"):  # alte Spar-Token im Spot-Konto
                if flexibel is not None:
                    continue  # schon über Simple Earn gezählt
                asset = asset[2:]
            kurs = eur_kurs(asset, preise)
            if anzahl <= 0 or kurs is None:
                if anzahl > 0:
                    log.info("Kein Euro-Kurs für %s – übersprungen", asset)
                continue
            wert = (anzahl * kurs).quantize(CENT)
            if wert >= CENT:
                holdings.append(FetchedHolding(symbol=asset, name=NAMEN.get(asset, asset), menge=anzahl,
                                               kurs=kurs.quantize(Decimal("0.0001")), wert=wert, datum=self.heute))
        holdings.sort(key=lambda h: -h.wert)
        konto = FetchedAccount(kontonummer="binance", name="Binance", typ="krypto", saldo_datum=self.heute,
                               saldo=sum((h.wert for h in holdings), Decimal(0)), holdings=holdings)
        return FetchResult(konten=[konto])
