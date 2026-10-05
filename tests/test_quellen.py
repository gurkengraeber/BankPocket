import functools
import hashlib
import hmac
import time
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest
import requests
from sqlalchemy import func, select

from bankpocket.analysen import monats_analyse
from bankpocket.config import Settings
from bankpocket.context import AppContext
from bankpocket.db import Account, Connection, Holding, PushSubscription, TransactionRow, make_sessionmaker
from bankpocket.fetchers.binance import BinanceSource
from bankpocket.fetchers.splitwise import SplitwiseSource
from bankpocket.fetchers.trade_republic import TradeRepublicSource
from bankpocket.models import Transaction
from bankpocket.notify import Notifier
from bankpocket.service import speichere_transaktionen
from bankpocket.sync import SyncManager
from bankpocket.vault import Vault

HEUTE = date(2026, 9, 30)
KEY, SECRET = "k" * 64, "s" * 64


@pytest.fixture
def umgebung(tmp_path):
    def bauen(quellen: dict):
        settings = Settings(data_dir=tmp_path, auth=False, scheduler=False)
        S = make_sessionmaker(settings.db_url)
        gesendet = []
        ctx = AppContext(settings=settings, session_factory=S, vault=Vault.from_file(settings.key_file),
                         notifier=Notifier(S, tmp_path, "mailto:t@x", sender=lambda a, p: gesendet.append(p),
                                           asynchron=False),
                         today=lambda: HEUTE, now=lambda: datetime(2026, 9, 30, 12), source_factory=None,
                         quellen=quellen)
        ctx.manager = SyncManager(ctx)
        with S() as s:
            s.add(PushSubscription(endpoint="https://push.example/1", p256dh="x", auth="y"))
            s.commit()
        return ctx, gesendet
    return bauen


def verbindung(ctx, art: str, login: str = "", pin: str = "geheim") -> int:
    with ctx.session_factory() as s:
        c = Connection(art=art, bank=art, name={"binance": "Binance", "splitwise": "Splitwise"}.get(art, "Trade Republic"),
                       blz="", server_url="", login_enc=ctx.vault.encrypt(login), pin_enc=ctx.vault.encrypt(pin))
        s.add(c)
        s.commit()
        return c.id


# ---------------- Binance ----------------
def binance_http(gueltig: bool = True, earn_seiten: int = 1) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v3/ticker/price":
            return httpx.Response(200, json=[{"symbol": s, "price": p} for s, p in
                                             [("BTCEUR", "60000"), ("EURUSDT", "1.10"), ("SOLUSDT", "150"), ("ETHEUR", "2500")]])
        query, signatur = req.url.query.decode().rsplit("&signature=", 1)
        assert req.headers["X-MBX-APIKEY"] == KEY
        assert signatur == hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
        if not gueltig:
            return httpx.Response(401, json={"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."})
        antworten = {
            "/api/v3/account": {"balances": [{"asset": "BTC", "free": "0.01", "locked": "0"},
                                             {"asset": "SOL", "free": "2", "locked": "0"},
                                             {"asset": "LDETH", "free": "1", "locked": "0"},
                                             {"asset": "SHIB", "free": "1000", "locked": "0"}]},
            "/sapi/v1/asset/get-funding-asset": [{"asset": "USDT", "free": "110", "locked": "0", "freeze": "0",
                                                  "withdrawing": "0"}],
            "/sapi/v1/simple-earn/flexible/position": {"rows": [{"asset": "ETH", "totalAmount": "0.5"}], "total": 1},
        }
        if earn_seiten > 1 and req.url.path == "/sapi/v1/simple-earn/flexible/position":
            seite = int(dict(req.url.params)["current"])  # Binance liefert pro Seite nur einen Teil
            zeilen = [{"asset": "ETH", "totalAmount": "0.5"}] if seite == 1 else [{"asset": "BTC", "totalAmount": "0.01"}]
            return httpx.Response(200, json={"rows": zeilen, "total": 2})
        if req.url.path in antworten:
            return httpx.Response(200, json=antworten[req.url.path])
        return httpx.Response(400, json={"code": -1002, "msg": "You are not authorized to execute this request."})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_binance_guthaben_in_euro(umgebung):
    ctx, _ = umgebung({"binance": functools.partial(BinanceSource, http=binance_http())})
    cid = verbindung(ctx, "binance", KEY, SECRET)
    assert ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True) == "ok"
    with ctx.session_factory() as s:
        [konto] = s.scalars(select(Account))
        assert (konto.name, konto.typ, konto.gruppe, konto.quelle) == ("Binance", "krypto", "Crypto", "binance")
        bestand = {h.symbol: h.wert for h in s.scalars(select(Holding))}
    # ETH nur einmal (Simple Earn statt LD-Token), SHIB ohne Kurs übersprungen, USDT/SOL über EURUSDT bewertet
    assert bestand == {"BTC": Decimal("600.00"), "ETH": Decimal("1250.00"), "SOL": Decimal("272.73"),
                       "USDT": Decimal("100.00")}


def test_binance_earn_wird_seitenweise_geholt(umgebung):
    ctx, _ = umgebung({"binance": functools.partial(BinanceSource, http=binance_http(earn_seiten=2))})
    cid = verbindung(ctx, "binance", KEY, SECRET)
    assert ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True) == "ok"
    with ctx.session_factory() as s:
        bestand = {h.symbol: h.wert for h in s.scalars(select(Holding))}
    assert bestand["BTC"] == Decimal("1200.00")  # 0,01 BTC Spot + 0,01 BTC von Seite 2
    assert bestand["ETH"] == Decimal("1250.00")


def test_binance_ungueltiger_schluessel_stoppt_automatik(umgebung):
    ctx, push = umgebung({"binance": functools.partial(BinanceSource, http=binance_http(gueltig=False))})
    cid = verbindung(ctx, "binance", KEY, SECRET)
    assert ctx.manager.ausfuehren(cid, interaktiv=False) == "pin_falsch"
    assert "API-Schlüssel" in push[0]["text"]


# ---------------- Splitwise ----------------
def splitwise_http(ausgaben: list[dict]) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.headers.get("Authorization") != f"Bearer {KEY}":
            return httpx.Response(401, json={"error": "Invalid API request: you are not logged in"})
        if req.url.path.endswith("/get_current_user"):
            return httpx.Response(200, json={"user": {"id": 1, "first_name": "Ich"}})
        if req.url.path.endswith("/get_friends"):
            return httpx.Response(200, json={"friends": [
                {"first_name": "Anna", "balance": [{"currency_code": "EUR", "amount": "40.0"}]},
                {"first_name": "Ben", "balance": [{"currency_code": "EUR", "amount": "-12.5"},
                                                  {"currency_code": "USD", "amount": "5"}]}]})
        return httpx.Response(200, json={"expenses": ausgaben})
    return httpx.Client(transport=httpx.MockTransport(handler))


def ausgabe(id_, datum, text, ich, andere, kategorie="General", geloescht=False, zahlung=False):
    users = [{"user": {"id": 1, "first_name": "Ich"}, "net_balance": ich}]
    users += [{"user": {"id": i + 2, "first_name": n}, "net_balance": b} for i, (n, b) in enumerate(andere)]
    return {"id": id_, "date": f"{datum}T18:00:00Z", "description": text, "currency_code": "EUR", "payment": zahlung,
            "category": {"name": kategorie}, "deleted_at": "2026-09-25T10:00:00Z" if geloescht else None,
            "users": users}


def test_splitwise_saldo_buchungen_und_analyse(umgebung):
    ausgaben = [ausgabe(10, "2026-09-20", "Pizza", "40.0", [("Anna", "-20"), ("Ben", "-20")], "Dining out"),
                ausgabe(12, "2026-09-22", "Kino", "-12.5", [("Ben", "12.5")], "Movies")]
    http = splitwise_http(ausgaben)
    ctx, _ = umgebung({"splitwise": functools.partial(SplitwiseSource, http=http)})
    cid = verbindung(ctx, "splitwise", pin=KEY)
    assert ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True) == "ok"
    with ctx.session_factory() as s:
        konto = s.scalar(select(Account).where(Account.quelle == "splitwise"))
        assert (konto.typ, konto.gruppe) == ("virtuell", "Virtuell")
        # Bankseite: ich habe die ganze Pizza bezahlt
        giro = Account(name="Girokonto", quelle="ing", typ="giro", gruppe="Tägliche Konten")
        s.add(giro)
        s.flush()
        speichere_transaktionen(s, giro, [Transaction(date(2026, 9, 20), Decimal("-60"), "Pizzeria Roma", "Pizza"),
                                          Transaction(date(2026, 9, 1), Decimal("2000"), "Firma", "Gehalt")])
        s.commit()
        m = monats_analyse(s, date(2026, 9, 1))
    assert m["einnahmen"] == 2000
    assert m["ausgaben"] == Decimal("32.50")  # 60 Pizza − 40 Anteil der anderen + 12,50 Kino, das Ben bezahlt hat
    assert {k["kategorie"]: k["summe"] for k in m["kategorien"]} == {"Restaurants": Decimal("20"),
                                                                    "Freizeit": Decimal("12.5")}

    # Ausgabe geändert und eine gelöscht → aktualisieren statt doppelt, gelöschte entfernen
    ausgaben[0] = ausgabe(10, "2026-09-20", "Pizza", "45.0", [("Anna", "-22.5"), ("Ben", "-22.5")], "Dining out")
    ausgaben[1] = ausgabe(12, "2026-09-22", "Kino", "-12.5", [("Ben", "12.5")], geloescht=True)
    assert ctx.manager.ausfuehren(cid, interaktiv=False) == "ok"
    with ctx.session_factory() as s:
        konto = s.scalar(select(Account).where(Account.quelle == "splitwise"))
        betraege = list(s.scalars(select(TransactionRow.betrag).where(TransactionRow.account_id == konto.id)))
        assert betraege == [Decimal("45")]
        from bankpocket.service import account_saldo
        assert account_saldo(s, konto) == Decimal("27.50")  # EUR-Bilanzen; USD wird nicht vermischt


def test_splitwise_falscher_schluessel(umgebung):
    ctx, _ = umgebung({"splitwise": functools.partial(SplitwiseSource, http=splitwise_http([]))})
    assert ctx.manager.ausfuehren(verbindung(ctx, "splitwise", pin="x" * 30), interaktiv=False) == "pin_falsch"


# ---------------- Trade Republic ----------------
class TRSzenario:
    def __init__(self):
        self.sitzung_gueltig, self.bestaetigt, self.pin_falsch = True, True, False
        self.logins = 0
        self.ereignisse = [
            {"id": "a1", "timestamp": "2026-09-28T09:12:00.000+0000", "title": "REWE", "subtitle": "Kartenzahlung",
             "amount": {"currency": "EUR", "value": -23.4}, "eventType": "card_successful_transaction",
             "status": "EXECUTED"},
            {"id": "a2", "timestamp": "2026-09-15T08:00:00.000+0000", "title": "Max Mustermann", "subtitle": "Einzahlung",
             "amount": {"currency": "EUR", "value": 500}, "eventType": "INCOMING_TRANSFER", "status": "EXECUTED"},
            {"id": "a3", "timestamp": "2026-09-02T07:00:00.000+0000", "title": "MSCI World", "subtitle": "Sparplan",
             "amount": {"currency": "EUR", "value": -200}, "eventType": "SAVINGS_PLAN_EXECUTED", "status": "EXECUTED"},
            {"id": "a4", "timestamp": "2026-09-01T07:00:00.000+0000", "title": "Abgebrochen", "subtitle": "",
             "amount": {"currency": "EUR", "value": -50}, "eventType": "TRADE_INVOICE", "status": "CANCELED"},
        ]


class FakeTR:
    weblogin_needs_authenticator = False

    def __init__(self, szenario: TRSzenario, **kw):
        self.s, self.cookies = szenario, kw["cookies_file"]
        assert kw["use_v2_login"] is True

    def resume_websession(self):
        from pathlib import Path
        p = Path(self.cookies)
        return p.exists() and p.read_text() == "sitzung-ok" and self.s.sitzung_gueltig

    def initiate_weblogin(self):
        if self.s.pin_falsch:
            r = requests.Response()
            r.status_code = 401
            raise requests.HTTPError(response=r)
        self.s.logins += 1
        return 120

    def complete_weblogin(self, code=None):
        if not self.s.bestaetigt:
            raise TimeoutError("nicht bestätigt")
        from pathlib import Path
        Path(self.cookies).write_text("sitzung-ok")
        self.s.sitzung_gueltig = True

    def save_websession(self):
        pass

    async def close(self):
        pass


class FakeTRQuelle(TradeRepublicSource):
    szenario: TRSzenario

    async def _portfolio(self, tr):
        return ([{"instrumentId": "IE00B4L5Y983", "name": "iShares Core MSCI World", "netSize": "10.5",
                  "price": "98.2", "netValue": "1031.10"}],
                [{"accountNumber": "DE89370400440532013000", "currencyId": "EUR", "amount": 1234.56}])

    async def _timeline(self, tr, start):
        return [e for e in self.szenario.ereignisse if date.fromisoformat(e["timestamp"][:10]) >= start]


def tr_quelle(szenario):
    klasse = type("TR", (FakeTRQuelle,), {"szenario": szenario})
    return functools.partial(klasse, api_factory=lambda **kw: FakeTR(szenario, **kw))


def test_trade_republic_anmeldung_depot_und_umsaetze(umgebung, tmp_path):
    sz = TRSzenario()
    ctx, _ = umgebung({"trade_republic": tr_quelle(sz)})
    cid = verbindung(ctx, "trade_republic", "+491701234567", "1234")
    assert ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True) == "ok"
    assert sz.logins == 1
    assert not list(tmp_path.glob("tr-*.cookies"))  # Sitzung liegt nur verschlüsselt in der DB
    with ctx.session_factory() as s:
        conn = s.get(Connection, cid)
        assert ctx.vault.decrypt(conn.client_data_enc) == b"sitzung-ok"
        konten = {a.name: a for a in s.scalars(select(Account))}
        assert konten["Verrechnungskonto"].gruppe == "Tägliche Konten"
        assert konten["Verrechnungskonto"].iban == "DE89370400440532013000"
        assert konten["Depot"].gruppe == "Sparkonten"
        assert s.scalar(select(func.count()).select_from(Holding)) == 1
        umsaetze = {t.gegenpartei: t for t in s.scalars(select(TransactionRow))}
        assert set(umsaetze) == {"REWE", "Max Mustermann", "MSCI World"}  # stornierte fehlt
        assert umsaetze["Max Mustermann"].intern and umsaetze["MSCI World"].kategorie == "Sparen"
        m = monats_analyse(s, date(2026, 9, 1))
    assert (m["einnahmen"], m["ausgaben"], m["gespart"]) == (0, Decimal("23.40"), Decimal("200"))

    # Folgeabruf im Hintergrund nutzt die gespeicherte Sitzung – keine neue Anmeldung
    sz.ereignisse[0]["amount"]["value"] = -23.9  # nachträglich geänderter Betrag
    assert ctx.manager.ausfuehren(cid, interaktiv=False) == "ok"
    assert sz.logins == 1
    with ctx.session_factory() as s:
        rewe = list(s.scalars(select(TransactionRow).where(TransactionRow.gegenpartei == "REWE")))
        assert [t.betrag for t in rewe] == [Decimal("-23.90")]


def test_trade_republic_sitzung_abgelaufen_im_hintergrund(umgebung):
    sz = TRSzenario()
    ctx, push = umgebung({"trade_republic": tr_quelle(sz)})
    cid = verbindung(ctx, "trade_republic", "+491701234567", "1234")
    ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True)
    sz.sitzung_gueltig = False
    assert ctx.manager.ausfuehren(cid, interaktiv=False) == "freigabe_noetig"
    assert sz.logins == 1  # keine ungefragte Anmeldung in der App
    assert "Trade-Republic-App" in push[-1]["text"]


def test_trade_republic_pin_falsch_und_nicht_bestaetigt(umgebung):
    sz = TRSzenario()
    sz.pin_falsch = True
    ctx, _ = umgebung({"trade_republic": tr_quelle(sz)})
    cid = verbindung(ctx, "trade_republic", "+491701234567", "9999")
    assert ctx.manager.ausfuehren(cid, interaktiv=True) == "pin_falsch"
    sz.pin_falsch, sz.bestaetigt = False, False
    with ctx.session_factory() as s:
        s.get(Connection, cid).status = "neu"
        s.commit()
    assert ctx.manager.ausfuehren(cid, interaktiv=True) == "freigabe_noetig"


def test_api_prueft_eingaben_je_quelle(tmp_path):
    from fastapi.testclient import TestClient
    from bankpocket.api import create_app
    app = create_app(Settings(data_dir=tmp_path, auth=False, scheduler=False),
                     quellen={"trade_republic": tr_quelle(TRSzenario())})
    c = TestClient(app)
    assert c.post("/api/verbindungen", json={"art": "trade_republic", "login": "0170 1234567", "pin": "12"}).status_code == 422
    assert c.post("/api/verbindungen", json={"art": "binance", "login": "kurz", "pin": "kurz"}).status_code == 422
    r = c.post("/api/verbindungen", json={"art": "trade_republic", "login": "0170 / 123 45 67", "pin": "1234"})
    assert r.status_code == 201
    with app.state.ctx.session_factory() as s:
        conn = s.get(Connection, r.json()["id"])
        assert app.state.ctx.vault.decrypt_str(conn.login_enc) == "+491701234567"
        assert (conn.art, conn.bank, conn.name) == ("trade_republic", "trade_republic", "Trade Republic")


def test_trade_republic_liefert_kursverlauf_fuer_fremde_depots(umgebung):
    """ING und Consorsbank nennen nur den heutigen Kurs – den Verlauf der ETFs holt der Abruf bei Trade Republic."""
    import asyncio
    from datetime import datetime, timezone

    from bankpocket.db import Price
    from bankpocket.service import wertpapiere_ohne_verlauf

    class TRMitKursen(FakeTR):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.offen, self.fertig, self.nr = {}, asyncio.Queue(), 0

        async def subscribe(self, abo):
            self.nr += 1
            nummer = str(self.nr)
            if abo["type"] == "instrument":
                if abo["id"] == "LU0000000002":  # kennt Trade Republic nicht
                    self.fertig.put_nowait(Exception(nummer))
                else:
                    self.fertig.put_nowait((nummer, abo, {"exchangeIds": ["LSX", "TDG"]}))
            else:
                assert abo == {"type": "aggregateHistoryLight", "range": "1y", "id": "FR0010261198.LSX"}
                tage = [datetime(2026, 9, t, tzinfo=timezone.utc).timestamp() * 1000 for t in (1, 2, 30)]
                self.fertig.put_nowait((nummer, abo, {"aggregates": [{"time": z, "close": 240 + i}
                                                                    for i, z in enumerate(tage)]}))
            return nummer

        async def recv(self):
            antwort = await self.fertig.get()
            if isinstance(antwort, Exception):
                raise antwort
            return antwort

        async def unsubscribe(self, nummer):
            pass

    class Quelle(FakeTRQuelle):
        szenario = TRSzenario()

        async def _kursverlaeufe(self, tr, positionen):
            return await TradeRepublicSource._kursverlaeufe(self, tr, positionen) if positionen and \
                positionen[0].get("exchangeIds") else {}

    sz = Quelle.szenario
    ctx, _ = umgebung({"trade_republic": functools.partial(Quelle, api_factory=lambda **kw: TRMitKursen(sz, **kw))})
    cid = verbindung(ctx, "trade_republic", "+491701234567", "1234")
    with ctx.session_factory() as s:
        ing = Account(quelle="ing", name="ING Direkt-Depot", typ="depot", gruppe="Sparkonten")
        s.add(ing)
        s.flush()
        for isin in ("FR0010261198", "LU0000000002", "KEINEISIN"):
            s.add(Holding(account_id=ing.id, datum=date(2026, 9, 30), symbol=isin, name=isin, menge=Decimal("1"),
                          kurs=Decimal("243.7"), wert=Decimal("243.70")))
        s.add(Price(symbol="FR0010261198", datum=date(2026, 9, 30), kurs=Decimal("243.7")))
        s.commit()
        assert wertpapiere_ohne_verlauf(s, cid) == ["FR0010261198", "LU0000000002"]
    assert ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True) == "ok"
    with ctx.session_factory() as s:
        kurse = dict(s.execute(select(Price.datum, Price.kurs).where(Price.symbol == "FR0010261198")).all())
        assert kurse == {date(2026, 9, 1): 240, date(2026, 9, 2): 241, date(2026, 9, 30): Decimal("243.7")}
        assert not s.scalar(select(func.count()).select_from(Price).where(Price.symbol == "LU0000000002"))


def test_trade_republic_nach_dem_code_noch_app_bestaetigung(umgebung):
    """Trade Republic verlangt nach dem Authenticator-Code zusätzlich die Bestätigung in der App."""
    sz = TRSzenario()
    schritte = []

    class TRMitBeidem(FakeTR):
        weblogin_needs_authenticator = True

        def complete_weblogin(self, code=None):
            schritte.append(("code", code))
            super().complete_weblogin(code)

        def _get_weblogin_process(self, quiet=False):
            return {"status": "PENDING", "requiredAction": "DEVICE_CONFIRMATION"}

        def _await_weblogin_confirmation(self):
            schritte.append(("app", None))

    klasse = type("TR", (FakeTRQuelle,), {"szenario": sz})
    ctx, _ = umgebung({"trade_republic": functools.partial(klasse, api_factory=lambda **kw: TRMitBeidem(sz, **kw))})
    cid = verbindung(ctx, "trade_republic", "+491701234567", "1234")
    import threading
    def code_eingeben():
        for _ in range(500):
            if ctx.manager.eingabe(cid, {"tan": "123456"}):
                return
            time.sleep(0.01)
    threading.Thread(target=code_eingeben, daemon=True).start()
    assert ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True) == "ok"
    assert schritte == [("code", "123456"), ("app", None)]
