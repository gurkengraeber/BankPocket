"""Enable Banking (Bank Norwegian): JWT, Freigabe, Umsätze – ohne Netzwerk, mit synthetischem Schlüssel."""
import base64
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from bankpocket.fetchers.base import FetchError, FreigabeNoetig, Interaktion, PinFalsch
from bankpocket.fetchers.enablebanking import (EnableBankingSource, code_aus_eingabe, fehler_aus_eingabe, jwt_erzeugen,
                                               umsatz)

APP_ID = "11111111-2222-3333-4444-555555555555"
HEUTE = date(2026, 10, 3)
REDIRECT = "http://192.168.1.10:8000/api/enablebanking/callback"


@pytest.fixture(scope="module")
def schluessel():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return key, pem


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_jwt_ist_gueltig_signiert(schluessel):
    key, pem = schluessel
    kopf, inhalt, signatur = jwt_erzeugen(APP_ID, pem, jetzt=1000).split(".")
    assert json.loads(_b64d(kopf)) == {"typ": "JWT", "alg": "RS256", "kid": APP_ID}
    assert json.loads(_b64d(inhalt)) == {"iss": "enablebanking.com", "aud": "api.enablebanking.com",
                                         "iat": 1000, "exp": 4600}
    key.public_key().verify(_b64d(signatur), f"{kopf}.{inhalt}".encode(), padding.PKCS1v15(), hashes.SHA256())


def test_code_aus_eingefuegter_adresse():
    assert code_aus_eingabe("http://x/api/enablebanking/callback?state=bp3-abc&code=XYZ") == ("XYZ", "bp3-abc")
    assert code_aus_eingabe("  XYZ ") == ("XYZ", None)
    abgelehnt = "https://localhost/api/enablebanking/callback?state=bp3-abc&error=access_denied&error_description=Nicht+erlaubt"
    assert fehler_aus_eingabe(abgelehnt) == "access_denied – Nicht erlaubt"
    assert fehler_aus_eingabe("http://x/api/enablebanking/callback?state=bp3-abc&code=XYZ") is None


def test_umsatz_vorzeichen_und_gegenpartei():
    ausgabe = umsatz({"entry_reference": "1", "transaction_amount": {"amount": "12.50", "currency": "EUR"},
                      "credit_debit_indicator": "DBDT", "booking_date": "2026-09-30", "status": "BOOK",
                      "creditor": {"name": "REWE"}, "remittance_information": ["Einkauf", "Leipzig"]})
    assert (ausgabe.betrag, ausgabe.gegenpartei, ausgabe.verwendungszweck) == (Decimal("-12.50"), "REWE", "Einkauf Leipzig")
    assert ausgabe.extern_id == "eb-1"
    einnahme = umsatz({"entry_reference": "2", "transaction_amount": {"amount": "50"}, "credit_debit_indicator": "CRDT",
                       "booking_date": "2026-09-30", "status": "BOOK", "debtor": {"name": "Ich"}})
    assert einnahme.betrag == Decimal("50.00")
    assert umsatz({"transaction_amount": {"amount": "1"}, "credit_debit_indicator": "DBDT",
                   "booking_date": "2026-09-30", "status": "PDNG"}) is None


def api(pem_ok: bool = True, abgelaufen: bool = False, aufrufe: list | None = None) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        if aufrufe is not None:
            aufrufe.append((req.method, req.url.path, dict(req.url.params)))
        assert req.headers["Authorization"].startswith("Bearer ")
        p = req.url.path
        if p == "/application":
            return httpx.Response(200 if pem_ok else 401, json={} if pem_ok else {"message": "Invalid JWT"})
        if p == "/aspsps":
            return httpx.Response(200, json={"aspsps": [{"name": "Bank Norwegian", "country": "DE"},
                                                        {"name": "Andere Bank", "country": "DE"}]})
        if p == "/auth":
            body = json.loads(req.content)
            assert body["aspsp"] == {"name": "Bank Norwegian", "country": "DE"} and body["redirect_url"] == REDIRECT
            return httpx.Response(200, json={"url": "https://auth.example/start", "authorization_id": "a"})
        if p == "/sessions":
            return httpx.Response(200, json={"session_id": "s1", "access": {"valid_until": "2027-01-01T00:00:00Z"},
                                             "accounts": [{"uid": "u1", "identification_hash": "h1",
                                                           "name": "Norwegian Reward", "currency": "EUR",
                                                           "cash_account_type": "CARD"}]})
        if abgelaufen:
            return httpx.Response(401, json={"error": "EXPIRED_SESSION", "message": "Session expired"})
        if p == "/accounts/u1/balances":
            return httpx.Response(200, json={"balances": [
                {"balance_type": "ITAV", "balance_amount": {"amount": "999", "currency": "EUR"}},
                {"balance_type": "CLBD", "balance_amount": {"amount": "-120.40", "currency": "EUR"},
                 "reference_date": "2026-10-02"}]})
        if p == "/accounts/u1/transactions":
            if req.url.params.get("continuation_key"):
                return httpx.Response(200, json={"transactions": [
                    {"entry_reference": "t2", "transaction_amount": {"amount": "5", "currency": "EUR"},
                     "credit_debit_indicator": "CRDT", "booking_date": "2026-09-01", "status": "BOOK"}]})
            return httpx.Response(200, json={"continuation_key": "k", "transactions": [
                {"entry_reference": "t1", "transaction_amount": {"amount": "20", "currency": "EUR"},
                 "credit_debit_indicator": "DBDT", "booking_date": "2026-09-02", "status": "BOOK",
                 "creditor": {"name": "Shop"}}]})
        return httpx.Response(404, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


def quelle(pem, http, interaktiv=True, client_data=None, **kw):
    return EnableBankingSource(login=APP_ID, pin=pem, interaktion=Interaktion(interaktiv), url=REDIRECT,
                               http=http, heute=HEUTE, client_data=client_data, **kw)


def test_erste_freigabe_und_abruf(schluessel):
    _, pem = schluessel
    q = quelle(pem, api())
    q.ia.eingabe({"code": f"{REDIRECT}?code=ABC"})
    ergebnis = q.abrufen()
    [konto] = ergebnis.konten
    assert (konto.typ, konto.name, konto.saldo, konto.saldo_datum) == ("kreditkarte", "Norwegian Reward",
                                                                      Decimal("-120.40"), date(2026, 10, 2))
    assert [t.betrag for t in konto.transaktionen] == [Decimal("-20.00"), Decimal("5.00")]  # beide Seiten
    assert ergebnis.freigabe_erfolgt and json.loads(ergebnis.client_data)["session_id"] == "s1"


def test_gespeicherte_sitzung_braucht_keine_freigabe(schluessel):
    _, pem = schluessel
    sitzung = json.dumps({"session_id": "s1", "valid_until": "2099-01-01T00:00:00Z", "accounts": [
        {"uid": "u1", "hash": "h1", "name": "Norwegian Reward", "iban": None, "currency": "EUR", "typ": "CARD"}]})
    aufrufe = []
    q = quelle(pem, api(aufrufe=aufrufe), interaktiv=False, client_data=sitzung.encode())
    ergebnis = q.abrufen()
    assert not ergebnis.freigabe_erfolgt and len(ergebnis.konten[0].transaktionen) == 2
    assert not any(p in ("/auth", "/sessions") for _, p, _ in aufrufe)
    ab = [params["date_from"] for _, p, params in aufrufe if p.endswith("/transactions")][0]
    assert ab == "2026-07-06"  # im Hintergrund nur die letzten 89 Tage


def test_abgelaufene_sitzung_im_hintergrund_fordert_hinweis(schluessel):
    _, pem = schluessel
    sitzung = json.dumps({"session_id": "s1", "valid_until": "2099-01-01T00:00:00Z", "accounts": [
        {"uid": "u1", "hash": "h1", "name": "x", "iban": None, "currency": "EUR", "typ": "CARD"}]})
    with pytest.raises(FreigabeNoetig):
        quelle(pem, api(abgelaufen=True), interaktiv=False, client_data=sitzung.encode()).abrufen()


def test_ohne_sitzung_im_hintergrund_keine_freigabe(schluessel):
    _, pem = schluessel
    with pytest.raises(FreigabeNoetig):
        quelle(pem, api(), interaktiv=False).abrufen()


def test_falscher_schluessel_stoppt_automatik(schluessel):
    _, pem = schluessel
    with pytest.raises(PinFalsch):
        quelle(pem, api(pem_ok=False)).abrufen()
    with pytest.raises(PinFalsch):
        quelle("kein schluessel", api()).abrufen()


def test_fremde_adresse_wird_uebergangen(schluessel, monkeypatch):
    """Eine Adresse aus einer anderen Freigabe bricht nichts ab – der Abruf wartet weiter auf die richtige."""
    monkeypatch.setattr("bankpocket.fetchers.enablebanking.WARTEN_AUF_BANK", 0.3)
    _, pem = schluessel
    q = quelle(pem, api(), verbindung_id=3)
    q.ia.eingabe({"code": f"{REDIRECT}?code=ABC&state=bp9-fremd"})
    with pytest.raises(FreigabeNoetig):
        q.abrufen()


def test_rueckkehr_adresse_nur_https():
    from starlette.requests import Request

    from bankpocket.routes.verbindungen import _rueckkehr_adresse

    def anfrage(scheme, host):
        return Request({"type": "http", "scheme": scheme, "server": (host, 443 if scheme == "https" else 8000),
                        "path": "/api/verbindungen", "headers": [], "query_string": b""})

    assert _rueckkehr_adresse(anfrage("http", "192.168.1.10")) == "https://localhost/api/enablebanking/callback"
    assert _rueckkehr_adresse(anfrage("https", "bank.example")) == "https://bank.example/api/enablebanking/callback"


def test_eingabe_nimmt_eingefuegte_adresse_an():
    from bankpocket.routes.verbindungen import EingabeIn

    adresse = "https://localhost/api/enablebanking/callback?state=bp4-abc&code=XYZ"
    assert EingabeIn(code=adresse).model_dump(exclude_none=True) == {"code": adresse}


def test_kartenausgleich_ist_interne_umbuchung():
    zahlung = {"entry_reference": "9", "transaction_amount": {"amount": "1011.05"}, "credit_debit_indicator": "CRDT",
               "booking_date": "2026-09-30", "status": "BOOK", "bank_transaction_code": {"code": "Einzahlung"},
               "remittance_information": ["Payment"]}
    assert umsatz(zahlung, karte=True).intern and not umsatz(zahlung).intern
    erstattung = {**zahlung, "bank_transaction_code": {"code": "Gutschrift"}}
    assert not umsatz(erstattung, karte=True).intern


def test_freigabe_so_lange_wie_die_bank_erlaubt(schluessel):
    _, pem = schluessel
    bank = {"name": "Bank Norwegian", "country": "DE", "maximum_consent_validity": 15552000}
    http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"aspsps": [bank]})))
    q = quelle(pem, http)
    assert q._bank() == {"name": "Bank Norwegian", "country": "DE"} and q.zugriff_tage == 179
    q = quelle(pem, api())
    q._bank()
    assert q.zugriff_tage == 89  # Bank nennt keine Dauer


def test_rueckkehr_von_der_bank_braucht_keine_anmeldung(tmp_path):
    """Die Bank leitet von einer fremden Seite zurück – ohne Cookie. Ein falscher state bricht nichts ab."""
    from fastapi.testclient import TestClient

    from bankpocket.api import create_app
    from bankpocket.auth import passwort_setzen
    from bankpocket.config import Settings

    app = create_app(Settings(data_dir=tmp_path, scheduler=False, auth=True))
    with app.state.ctx.session_factory() as s:
        passwort_setzen(s, "ein-langes-passwort")
        s.commit()
    c = TestClient(app, follow_redirects=False)
    assert c.get("/api/verbindungen").status_code == 401  # alles andere braucht die Anmeldung
    r = c.get("/api/enablebanking/callback", params={"state": "bp7-0123456789ab", "code": "XYZ"})
    assert r.status_code == 303 and r.headers["location"] == "/#/verbindung/7"
    assert "default-src 'self'" in r.headers["content-security-policy"]



def test_weitere_bank_nutzt_die_zugangsdaten_mit(tmp_path, schluessel):
    """Consorsbank über dieselbe Enable-Banking-Anwendung: ohne erneute Eingabe von Application-ID und Schlüssel."""
    from fastapi.testclient import TestClient

    from bankpocket.api import create_app
    from bankpocket.config import Settings
    from bankpocket.db import Connection

    _, pem = schluessel
    app = create_app(Settings(data_dir=tmp_path, scheduler=False, auth=False))
    ctx = app.state.ctx
    gestartet = []
    ctx.manager.starten = lambda conn_id, **kw: gestartet.append(conn_id) or True
    c = TestClient(app)
    leer = c.post("/api/verbindungen", json={"art": "enablebanking", "bank": "consorsbank"})
    assert leer.status_code == 422  # noch keine Anwendung eingerichtet
    erste = c.post("/api/verbindungen", json={"art": "enablebanking", "login": APP_ID, "pin": pem}).json()["id"]
    zweite = c.post("/api/verbindungen", json={"art": "enablebanking", "bank": "consorsbank"}).json()["id"]
    with ctx.session_factory() as s:
        a, b = s.get(Connection, erste), s.get(Connection, zweite)
        assert (a.bank, a.name) == ("norwegian", "Bank Norwegian")
        assert (b.bank, b.name, b.server_url) == ("consorsbank", "Consorsbank", a.server_url)
        assert ctx.vault.decrypt_str(b.login_enc) == APP_ID and ctx.vault.decrypt_str(b.pin_enc) == pem.strip()
    assert gestartet == [erste, zweite]


def test_bank_der_verbindung_bestimmt_die_bank_bei_enable_banking(schluessel):
    _, pem = schluessel
    q = EnableBankingSource(login=APP_ID, pin=pem, interaktion=None, bank="consorsbank")
    assert q.bank_name == "Consorsbank"
    assert EnableBankingSource(login=APP_ID, pin=pem, interaktion=None, bank="andere").bank_name == "Bank Norwegian"


def test_n26_und_revolut_sind_ueber_enable_banking_waehlbar(tmp_path, schluessel):
    from fastapi.testclient import TestClient

    from bankpocket.api import create_app
    from bankpocket.config import Settings
    from bankpocket.db import Connection

    _, pem = schluessel
    app = create_app(Settings(data_dir=tmp_path, scheduler=False, auth=False))
    ctx = app.state.ctx
    ctx.manager.starten = lambda conn_id, **kw: True
    c = TestClient(app)
    c.post("/api/verbindungen", json={"art": "enablebanking", "login": APP_ID, "pin": pem})
    ids = {b: c.post("/api/verbindungen", json={"art": "enablebanking", "bank": b}).json()["id"] for b in ("n26", "revolut")}
    with ctx.session_factory() as s:
        assert [(s.get(Connection, i).bank, s.get(Connection, i).name) for i in ids.values()] == [
            ("n26", "N26"), ("revolut", "Revolut")]
    for kuerzel, name in (("n26", "N26"), ("revolut", "Revolut")):
        assert EnableBankingSource(login=APP_ID, pin=pem, interaktion=None, bank=kuerzel).bank_name == name


def _api_ohne_konten(nachfrage: list | None):
    """Die Bank liefert nach der Freigabe zunächst keine Konten; `nachfrage` (oder nichts) beim zweiten Nachfragen."""
    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/application":
            return httpx.Response(200, json={})
        if p == "/aspsps":
            return httpx.Response(200, json={"aspsps": [{"name": "Revolut", "country": "DE"}]})
        if p == "/auth":
            return httpx.Response(200, json={"url": "https://auth.example/start"})
        if p == "/sessions":
            return httpx.Response(200, json={"session_id": "s9", "accounts": [], "access": {"valid_until": "2027-01-01T00:00:00Z"}})
        if p == "/sessions/s9":
            return httpx.Response(200, json={"session_id": "s9", "accounts": nachfrage or []})
        if p.endswith("/balances"):
            return httpx.Response(200, json={"balances": []})
        if p.endswith("/transactions"):
            return httpx.Response(200, json={"transactions": []})
        return httpx.Response(404, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_keine_konten_nach_der_freigabe_wird_erklaert_statt_null_konten_zu_melden(schluessel):
    _, pem = schluessel
    q = quelle(pem, _api_ohne_konten(None), bank="revolut")
    q.ia.eingabe({"code": f"{REDIRECT}?code=ABC"})
    with pytest.raises(FetchError) as e:
        q.abrufen()
    text = str(e.value)
    assert "keine Konten geliefert" in text and "Revolut" in text and "Activate by linking accounts" in text
    assert "s9" not in text  # keine Inhalte der Antwort, nur die Feldnamen


def test_konten_die_erst_auf_nachfrage_kommen_werden_genommen(schluessel):
    _, pem = schluessel
    q = quelle(pem, _api_ohne_konten([{"uid": "u7", "identification_hash": "h7", "name": "Hauptkonto", "currency": "EUR",
                                       "account_id": {"iban": "DE02100100100006820101"}}]), bank="revolut")
    q.ia.eingabe({"code": f"{REDIRECT}?code=ABC"})
    [konto] = q.abrufen().konten
    assert (konto.name, konto.typ, konto.iban) == ("Hauptkonto", "giro", "DE02100100100006820101")
