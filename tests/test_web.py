import functools
import time
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from bankpocket.api import create_app
from bankpocket.auth import passwort_setzen
from bankpocket.config import Settings
from bankpocket.fetchers.fints_source import FinTSSource
from bankpocket.notify import Notifier
from conftest import vertraege_bestaetigen
from fints_fake import FakeBank

HEUTE = date(2026, 10, 1)


def app_mit_bank(tmp_path, bank=None, auth=False, frontend_dir=None):
    bank = bank or FakeBank(HEUTE)
    settings = Settings(data_dir=tmp_path, auth=auth, scheduler=False, fints_product_id="TEST",
                        frontend_dir=frontend_dir)
    app = create_app(settings, today=lambda: HEUTE, now=lambda: datetime(2026, 10, 1, 9, 30),
                     source_factory=functools.partial(FinTSSource, client_factory=bank.factory,
                                                      schlafen=lambda s: None))
    gesendet = []
    ctx = app.state.ctx
    ctx.notifier = Notifier(ctx.session_factory, tmp_path, "mailto:t@x", sender=lambda a, p: gesendet.append(p),
                            asynchron=False)
    return TestClient(app), bank, gesendet


def warte_bis_fertig(client, conn_id):
    for _ in range(500):
        v = client.get(f"/api/verbindungen/{conn_id}").json()
        if v["live"] and not v["live"]["laeuft"]:
            return v
        time.sleep(0.01)
    raise AssertionError("Abruf wurde nicht fertig")


def test_login_pflicht_und_bremse(tmp_path):
    client, _, _ = app_mit_bank(tmp_path, auth=True)
    assert client.get("/api/uebersicht").status_code == 401
    assert client.get("/api/auth").json() == {"aktiv": True, "passwort_gesetzt": False, "angemeldet": False}
    with client.app.state.ctx.session_factory() as s:
        passwort_setzen(s, "ein-langes-passwort")
        s.commit()
    assert client.post("/api/login", json={"passwort": "falsch"}).status_code == 401
    r = client.post("/api/login", json={"passwort": "ein-langes-passwort"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/uebersicht").status_code == 200
    client.post("/api/logout")
    client.cookies.clear()
    for _ in range(5):
        client.post("/api/login", json={"passwort": "falsch"})
    assert client.post("/api/login", json={"passwort": "ein-langes-passwort"}).status_code == 429


def test_bank_verbinden_ueber_die_api(tmp_path):
    client, bank, _ = app_mit_bank(tmp_path)
    assert {b["id"] for b in client.get("/api/banken").json()} == {"ing", "consorsbank"}
    r = client.post("/api/verbindungen", json={"bank": "ing", "login": "kunde1", "pin": "1234"})
    assert r.status_code == 201
    v = warte_bis_fertig(client, r.json()["id"])
    assert v["status"] == "ok" and v["live"]["phase"] == "fertig"
    assert v["tan_verfahren"] == "App-Freigabe" and v["freigabe_faellig_am"] == "2026-12-30"
    assert {k["name"] for k in v["konten"]} == {"Girokonto", "Extra-Konto", "Direkt-Depot"}

    vertraege_bestaetigen(client)
    u = client.get("/api/uebersicht").json()
    gruppen = {g["name"]: g for g in u["gruppen"]}
    assert gruppen["Tägliche Konten"]["summe"] == 1500
    assert gruppen["Sparkonten"]["summe"] == 8955  # Extra-Konto + Depot
    assert u["gesamtsumme"] == 10455 and u["banner"] == []
    assert u["letzte_aktualisierung"].startswith("2026-10-01T09:30")
    # Gehalt kam am 28.09., nächstes am 28.10.; Streamflix (12,99) ist am 15.10. noch fällig
    g = u["gehalt"]
    assert (g["tage"], g["datum"], g["ausstehend"]) == (27, "2026-10-28", 12.99)
    assert g["verfuegbar"] == 2500 - 12.99
    assert [p["name"] for p in g["posten"]] == ["Streamflix GmbH"] and g["pro_tag"] == round((2500 - 12.99) / 27, 2)
    assert g["verspaetet"] is False


def test_falsche_pin_banner_und_pin_aendern(tmp_path):
    client, bank, _ = app_mit_bank(tmp_path)
    cid = client.post("/api/verbindungen", json={"bank": "ing", "login": "kunde1", "pin": "0000"}).json()["id"]
    assert warte_bis_fertig(client, cid)["status"] == "pin_falsch"
    assert client.get("/api/uebersicht").json()["banner"][0]["art"] == "pin_falsch"
    assert client.post(f"/api/verbindungen/{cid}/abrufen").status_code == 409
    assert client.patch(f"/api/verbindungen/{cid}", json={"pin": "1234"}).json()["status"] == "neu"
    assert client.post(f"/api/verbindungen/{cid}/abrufen").json()["gestartet"]
    assert warte_bis_fertig(client, cid)["status"] == "ok"


def test_andere_bank_braucht_blz_und_https(tmp_path):
    client, _, _ = app_mit_bank(tmp_path)
    r = client.post("/api/verbindungen", json={"bank": "andere", "login": "x", "pin": "y", "blz": "12030000",
                                               "url": "http://unsicher.example"})
    assert r.status_code == 422


def test_buchungen_analysen_und_hinweise(tmp_path):
    client, _, push = app_mit_bank(tmp_path)
    cid = client.post("/api/verbindungen", json={"bank": "ing", "login": "kunde1", "pin": "1234"}).json()["id"]
    warte_bis_fertig(client, cid)

    b = client.get("/api/buchungen", params={"gruppe": "Tägliche Konten", "limit": 5}).json()
    assert len(b["buchungen"]) == 5 and b["weitere"]
    assert b["buchungen"][0]["datum"] == "2026-09-28" and b["buchungen"][0]["konto_name"] == "Girokonto"
    streamflix = client.get("/api/buchungen", params={"suche": "streamflix"}).json()["buchungen"]
    assert len(streamflix) == 4 and all(x["contract_id"] for x in streamflix)
    detail = client.get(f"/api/buchungen/{streamflix[0]['id']}").json()
    assert detail["glaeubiger_id"] == "DE98ZZZ09999999999"
    client.patch(f"/api/buchungen/{streamflix[0]['id']}", json={"kategorie": "Streaming"})

    m = client.get("/api/analysen/monat", params={"monat": "2026-09"}).json()
    assert m["einnahmen"] == 2500 and m["ausgaben"] == 12.99  # Umbuchung aufs Extra-Konto zählt nicht
    assert m["kategorien"][0]["kategorie"] == "Streaming" and len(m["verlauf"]) == 6

    v = client.get("/api/analysen/vermoegen", params={"tage": 120}).json()
    assert v["aktuell"] == 10455 and v["punkte"][-1]["d"] == "2026-10-01"
    # vom heutigen Saldo zurückgerechnet: vor dem Gehalt am 28.09. war das Girokonto 2500 € niedriger
    werte = {p["d"]: p["w"] for p in v["punkte"]}
    assert werte["2026-09-27"] == pytest.approx(10455 - 2500)

    vertraege_bestaetigen(client)
    vertraege = client.get("/api/contracts").json()
    sf = vertraege["ausgaben"][0]["vertraege"][0]
    d = client.get(f"/api/contracts/{sf['id']}").json()
    assert len(d["zahlungen"]) == 4 and d["monatlich"] == 12.99

    with client.app.state.ctx.session_factory() as s:
        client.app.state.ctx.notifier.hinweis(s, "test", "Hallo", "Welt")
        s.commit()
    assert client.get("/api/uebersicht").json()["hinweise_ungelesen"] == 1
    client.post("/api/hinweise/gelesen", json={})
    assert client.get("/api/hinweise").json()[0]["gelesen"] is True


def test_push_abo_und_test(tmp_path):
    client, _, push = app_mit_bank(tmp_path)
    info = client.get("/api/push").json()
    assert len(info["schluessel"]) == 87 and info["abos"] == 0
    abo = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "k", "auth": "a"}}
    client.post("/api/push/abo", json=abo)
    client.post("/api/push/abo", json=abo)  # doppelt anmelden ist harmlos
    assert client.get("/api/push").json()["abos"] == 1
    assert client.post("/api/push/test").json() == {"gesendet": 1}
    client.request("DELETE", "/api/push/abo", json={"endpoint": abo["endpoint"]})
    assert client.get("/api/push").json()["abos"] == 0


def test_frontend_wird_ausgeliefert(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>BankPocket</title>")
    (dist / "assets" / "app-123.js").write_text("console.log(1)")
    (dist / "sw.js").write_text("// sw")
    client, _, _ = app_mit_bank(tmp_path / "daten", frontend_dir=dist)
    assert "BankPocket" in client.get("/").text
    assert "immutable" in client.get("/assets/app-123.js").headers["cache-control"]
    assert client.get("/sw.js").headers["cache-control"] == "no-cache"
    assert "BankPocket" in client.get("/irgendwas").text  # SPA-Fallback
    assert client.get("/api/gibtsnicht").status_code == 404
    assert client.get("/../secret.key").status_code in (200, 404) and "BankPocket" in client.get("/../x").text


def test_bank_aus_der_liste_per_blz(tmp_path):
    client, _, _ = app_mit_bank(tmp_path)
    [t] = client.get("/api/banken/suche", params={"q": "DE02 8609 5604 0000 0000 00"}).json()
    assert (t["name"], t["familie"]) == ("Leipziger Volksbank eG", "volksbank")
    assert t["url"].startswith("https://fints1.atruvia.de")  # alter Fiducia-Server umgeschrieben
    assert client.get("/api/banken/suche", params={"q": "sparkasse leipzig"}).json()[0]["blz"] == "86055592"
    assert client.get("/api/banken/suche", params={"q": "12030000"}).json()[0]["familie"] == "dkb"

    cid = client.post("/api/verbindungen", json={"bank": "andere", "login": "kunde1", "pin": "1234",
                                                 "blz": "86055592"}).json()["id"]
    v = client.get(f"/api/verbindungen/{cid}").json()
    assert (v["bank"], v["name"]) == ("sparkasse", "Stadt- und Kreissparkasse Leipzig")
    assert client.post("/api/verbindungen", json={"bank": "andere", "login": "x", "pin": "y",
                                                  "blz": "99999999"}).status_code == 422
