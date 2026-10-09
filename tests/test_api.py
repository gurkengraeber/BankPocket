from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from bankpocket.api import create_app
from bankpocket.config import Settings
from conftest import vertraege_bestaetigen

TODAY = date(2026, 10, 1)
FIXTURE = (Path(__file__).parent / "fixtures" / "ing_synthetic.csv").read_bytes()


def csv_rows(*rows: str) -> bytes:
    head = "Buchung;Valuta;Auftraggeber/Empfänger;Buchungstext;Verwendungszweck;Saldo;Währung;Betrag;Währung\n"
    return (head + "\n".join(rows)).encode()


def make_client(tmp_path, today=TODAY, **kw):
    settings = Settings(data_dir=tmp_path, auth=False, scheduler=False, **kw)
    return TestClient(create_app(settings, today=lambda: today))


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path)


def make_account(client, name="ING Girokonto", quelle="ing", gruppe="Tägliche Konten", typ="giro"):
    r = client.post("/api/accounts", json={"name": name, "quelle": quelle, "typ": typ, "gruppe": gruppe})
    assert r.status_code == 201
    return r.json()["id"]


def upload(client, acc, data: bytes):
    r = client.post(f"/api/accounts/{acc}/import", files={"file": ("export.csv", data)})
    assert r.status_code == 200, r.text
    return r.json()


def test_import_dedup_and_balance(client):
    acc = make_account(client)
    first = upload(client, acc, FIXTURE)
    assert first["importiert"] == 6 and first["duplikate"] == 0
    assert sorted(first["vertraege"]["neu"]) == ["Musterfirma AG", "Streamflix GmbH"]

    second = upload(client, acc, FIXTURE)  # überlappender Export
    assert second["importiert"] == 0 and second["duplikate"] == 6

    gruppen = {g["name"]: g for g in client.get("/api/accounts").json()["gruppen"]}
    [konto] = gruppen["Tägliche Konten"]["konten"]
    assert konto["saldo"] == 900 and konto["stand"] is not None
    assert konto["ungesehen"] == 6
    client.post(f"/api/accounts/{acc}/seen")
    assert client.get("/api/accounts").json()["gruppen"][0]["konten"][0]["ungesehen"] == 0


def test_identical_bookings_same_day_kept(client):
    acc = make_account(client)
    row = "02.09.2026;02.09.2026;Bäcker;Kartenzahlung;Brötchen;;EUR;-2,50;EUR"
    assert upload(client, acc, csv_rows(row, row))["importiert"] == 2
    assert upload(client, acc, csv_rows(row, row))["importiert"] == 0


def test_contracts_view(client):
    acc = make_account(client)
    upload(client, acc, FIXTURE)
    v = client.get("/api/contracts").json()
    # erkannte Verträge werden erst erfragt und zählen bis zur Bestätigung nicht mit
    assert v["ausgaben_monatlich"] == 0 and not v["ausgaben"] and not v["einnahmen"]
    assert "Streamflix GmbH" in [o["name"] for o in v["vorschlaege"]]
    assert client.get("/api/kalender").json()["tage"] == []
    vertraege_bestaetigen(client)
    v = client.get("/api/contracts").json()
    assert v["vorschlaege"] == []
    assert v["ausgaben_monatlich"] == 12.99
    assert v["basierend_seit"] == "2026-07-15"
    [monatlich] = v["ausgaben"]
    assert monatlich["turnus"] == "monatlich" and monatlich["anzahl"] == 1
    assert v["einnahmen"][0]["vertraege"][0]["kategorie"] == "Lohn / Gehalt"


def test_user_edits_survive_reimport(client):
    acc = make_account(client)
    upload(client, acc, FIXTURE)
    vertraege_bestaetigen(client)
    v = client.get("/api/contracts").json()
    streamflix = v["ausgaben"][0]["vertraege"][0]
    gehalt = v["einnahmen"][0]["vertraege"][0]

    client.patch(f"/api/contracts/{streamflix['id']}", json={"name": "Streamflix", "kategorie": "Streaming"})
    assert client.delete(f"/api/contracts/{gehalt['id']}").status_code == 204

    upload(client, acc, csv_rows(
        "15.10.2026;15.10.2026;Streamflix GmbH;Lastschrift;Abo Mandatsref: MR-100 Gläubiger-ID: DE98ZZZ09999999999;887,01;EUR;-12,99;EUR",
        "28.10.2026;28.10.2026;Musterfirma AG;Gutschrift;Gehalt Oktober;3.387,01;EUR;2.500,00;EUR",
    ))
    v = client.get("/api/contracts").json()
    [c] = v["ausgaben"][0]["vertraege"]
    assert (c["name"], c["kategorie"], c["vorkommen"]) == ("Streamflix", "Streaming", 4)
    assert v["einnahmen"] == []  # entfernt bleibt entfernt


def test_overdue_contract(tmp_path):
    client = make_client(tmp_path, today=date(2026, 11, 1))
    acc = make_account(client)
    upload(client, acc, FIXTURE)
    vertraege_bestaetigen(client)
    v = client.get("/api/contracts").json()
    c = v["ausgaben"][0]["vertraege"][0]
    assert c["status"] == "ueberfaellig" and c["tage_ueberfaellig"] == 17  # fällig 15.10.


def test_manual_account_and_contract(client):
    bar = make_account(client, "Bargeld", "manuell")
    for _ in range(2):  # zwei identische Buchungen sind bei manuellen Konten erlaubt
        r = client.post(f"/api/accounts/{bar}/transactions", json={"datum": "2026-09-30", "betrag": "50"})
        assert r.status_code == 201
    konto = client.get("/api/accounts").json()["gruppen"][0]["konten"][0]
    assert konto["saldo"] == 100

    ing = make_account(client)
    assert client.post(f"/api/accounts/{ing}/transactions",
                       json={"datum": "2026-09-30", "betrag": "1"}).status_code == 400

    r = client.post("/api/contracts", json={"name": "Hausrat", "kategorie": "Versicherung",
                                            "turnus": "jaehrlich", "betrag": "-120",
                                            "naechste_faelligkeit": "2027-01-01"})
    assert r.status_code == 201
    v = client.get("/api/contracts").json()
    assert v["ausgaben"][0]["turnus"] == "jaehrlich" and v["ausgaben_monatlich"] == 10


def test_stand_eintragen(client):
    sw = make_account(client, "Splitwise", "manuell", gruppe="Virtuell", typ="virtuell")
    assert client.post(f"/api/accounts/{sw}/stand", json={"saldo": "42.50"}).json()["saldo"] == 42.5
    r = client.post(f"/api/accounts/{sw}/stand", json={"saldo": "-10"}).json()
    assert r["saldo"] == -10 and r["differenz"] == -52.5
    client.post(f"/api/accounts/{sw}/stand", json={"saldo": "-10"})  # unverändert: keine neue Buchung
    buchungen = client.get(f"/api/accounts/{sw}/transactions").json()
    assert [b["betrag"] for b in buchungen] == [-52.5, 42.5] and all(b["intern"] for b in buchungen)
    monat = client.get("/api/analysen/monat?monat=2026-10").json()
    assert monat["ausgaben"] == 0 and monat["einnahmen"] == 0

    ing = make_account(client)
    # ein Bankkonto ohne Verbindung (CSV-Import) bekommt den Stand als Ankerpunkt, ohne Korrekturbuchung
    assert client.post(f"/api/accounts/{ing}/stand", json={"saldo": "1"}).json() == {"saldo": 1, "differenz": 0}


def test_closed_account_not_in_total(client):
    acc = make_account(client, "Barclays Visa", "manuell", typ="kreditkarte")
    client.post(f"/api/accounts/{acc}/transactions", json={"datum": "2026-09-30", "betrag": "-30"})
    client.patch(f"/api/accounts/{acc}", json={"aktiv": False})
    data = client.get("/api/accounts").json()
    assert data["gesamtsumme"] == 0
    assert data["gruppen"][0]["konten"][0]["aktiv"] is False


def test_invalid_csv(client):
    acc = make_account(client)
    r = client.post(f"/api/accounts/{acc}/import", files={"file": ("x.csv", b"foo;bar\n1;2")})
    assert r.status_code == 422


def test_kartenausgleich_gegenseite_auf_dem_girokonto(client):
    """Die Karte hat keine IBAN: Die Überweisung vom Girokonto wird über Betrag und Datum als intern erkannt."""
    from bankpocket.db import Account, TransactionRow
    from bankpocket.service import markiere_interne_umbuchungen

    giro = make_account(client)
    karte = make_account(client, name="Norwegian", quelle="norwegian", typ="kreditkarte")
    with client.app.state.ctx.session_factory() as s:
        def buchung(konto, tag, betrag, intern=False, h=[0]):
            h[0] += 1
            s.add(TransactionRow(account_id=konto, buchungsdatum=date(2026, 9, tag), betrag=betrag, gegenpartei="x",
                                 verwendungszweck="", hash=f"h{h[0]}", intern=intern))
        buchung(karte, 30, 1011.05, intern=True)  # Ausgleich kommt auf der Karte an
        buchung(giro, 28, -1011.05)  # … und ging zwei Tage vorher vom Girokonto ab
        buchung(giro, 10, -1011.05)  # gleicher Betrag, aber zu früh
        buchung(giro, 29, -50)
        for _ in range(2):  # ein zweiter Lauf markiert nichts zusätzlich
            markiere_interne_umbuchungen(s)
            s.flush()
        interne = s.query(TransactionRow).filter_by(account_id=giro, intern=True).all()
        assert [(t.buchungsdatum.day, float(t.betrag)) for t in interne] == [(28, -1011.05)]


def test_positionen_zeigen_den_letzten_bestand(client):
    from bankpocket.db import Holding

    depot = make_account(client, name="Depot", quelle="trade_republic", gruppe="Sparkonten", typ="depot")
    assert client.get(f"/api/accounts/{depot}/positionen").json() == {
        "stand": None, "davor": None, "positionen": [], "gewinn": None, "gewinn_prozent": None}
    with client.app.state.ctx.session_factory() as s:
        s.add_all([Holding(account_id=depot, datum=date(2026, 9, 30), symbol="ALT", name="Verkauft", menge=1, kurs=1, wert=1),
                   Holding(account_id=depot, datum=date(2026, 9, 30), symbol="IE00B4L5Y983", menge=2, kurs=96, wert=192),
                   Holding(account_id=depot, datum=date(2026, 10, 1), symbol="IE00B4L5Y983", name="Core MSCI World", menge=2, kurs=100, wert=200,
                           einstand=80),
                   Holding(account_id=depot, datum=date(2026, 10, 1), symbol="US0378331005", menge=1, kurs=500, wert=500)])
        s.commit()
    d = client.get(f"/api/accounts/{depot}/positionen").json()
    assert d["stand"] == "2026-10-01"
    assert [(p["name"], p["wert"]) for p in d["positionen"]] == [("US0378331005", 500), ("Core MSCI World", 200)]
    # Plus/Minus seit Kauf nur, wo der Kaufkurs bekannt ist: 2 × 80 € bezahlt, jetzt 200 € wert
    assert [(p["gewinn"], p["gewinn_prozent"]) for p in d["positionen"]] == [(None, None), (40, 25.0)]
    assert (d["gewinn"], d["gewinn_prozent"]) == (40, 25.0)
    # seit dem vorherigen Stand (30.09.) ist der Kurs von 96 auf 100 gestiegen
    assert d["davor"] == "2026-09-30" and [p["kurs_prozent"] for p in d["positionen"]] == [None, 4.17]


def test_buchungen_hinter_der_monatsanalyse(client):
    acc = make_account(client)
    upload(client, acc, FIXTURE)
    monat = client.get("/api/analysen/monat", params={"monat": "2026-09"}).json()
    for art in ("einnahme", "ausgabe"):
        b = client.get("/api/analysen/buchungen", params={"monat": "2026-09", "art": art}).json()["buchungen"]
        assert round(abs(sum(x["betrag"] for x in b)), 2) == round(monat[art + "n" if art == "ausgabe" else "einnahmen"], 2)
    for k in monat["kategorien"]:
        b = client.get("/api/analysen/buchungen", params={"monat": "2026-09", "kategorie": k["kategorie"]}).json()["buchungen"]
        assert len(b) == k["anzahl"] and round(-sum(x["betrag"] for x in b), 2) == round(k["summe"], 2)
    assert client.get("/api/analysen/buchungen", params={"monat": "quatsch"}).status_code == 422
    # Tags erscheinen in der Monatsanalyse, die Suche findet auch Kategorien
    ausgabe = client.get("/api/analysen/buchungen", params={"monat": "2026-09", "art": "ausgabe"}).json()["buchungen"][0]
    client.patch(f"/api/buchungen/{ausgabe['id']}", json={"tags": ["Urlaub"]})
    [tag] = client.get("/api/analysen/monat", params={"monat": "2026-09"}).json()["tags"]
    assert (tag["tag"], tag["anzahl"], tag["summe"]) == ("Urlaub", 1, -ausgabe["betrag"])
    b = client.get("/api/analysen/buchungen", params={"monat": "2026-09", "tag": "Urlaub"}).json()["buchungen"]
    assert [x["id"] for x in b] == [ausgabe["id"]]
    treffer = client.get("/api/buchungen", params={"suche": ausgabe["kategorie"].lower()}).json()["buchungen"]
    assert ausgabe["id"] in [x["id"] for x in treffer] and all(x["kategorie"] == ausgabe["kategorie"] for x in treffer)
    # Auswahl unter dem Suchfeld: vorkommende Kategorien und Tags, danach exakt filtern
    f = client.get("/api/buchungen/filter", params={"konto": acc}).json()
    assert ausgabe["kategorie"] in [k["name"] for k in f["kategorien"]] and f["tags"] == [{"name": "Urlaub", "anzahl": 1}]
    anzahl = next(k["anzahl"] for k in f["kategorien"] if k["name"] == ausgabe["kategorie"])
    genau = client.get("/api/buchungen", params={"konto": acc, "kategorie": ausgabe["kategorie"], "limit": 500}).json()
    assert len(genau["buchungen"]) == anzahl and {x["kategorie"] for x in genau["buchungen"]} == {ausgabe["kategorie"]}
    assert [x["id"] for x in client.get("/api/buchungen", params={"tag": "Urlaub"}).json()["buchungen"]] == [ausgabe["id"]]


def test_buchung_umbuchung_notiz_und_vertrag(client):
    acc = make_account(client)
    upload(client, acc, FIXTURE)
    b = next(x for x in client.get("/api/buchungen", params={"konto": acc}).json()["buchungen"]
             if x["betrag"] < 0)
    # als Umbuchung markieren und Notiz setzen – die Kategorie bleibt dabei unberührt
    r = client.patch(f"/api/buchungen/{b['id']}", json={"intern": True, "notiz": " für Oma "}).json()
    assert (r["intern"], r["notiz"], r["kategorie"]) == (True, "für Oma", b["kategorie"])
    upload(client, acc, FIXTURE)  # erneuter Import ändert daran nichts
    assert client.get(f"/api/buchungen/{b['id']}").json()["intern"] is True
    client.patch(f"/api/buchungen/{b['id']}", json={"intern": False})
    # eigenen Vertrag aus der Buchung anlegen
    r = client.post(f"/api/buchungen/{b['id']}/vertrag", json={"turnus": "zweiwoechentlich"}).json()
    v = client.get(f"/api/contracts/{r['vertrag']['id']}").json()
    assert (v["quelle"], v["turnus"], v["betrag"], v["bestaetigt"]) == ("manuell", "zweiwoechentlich", b["betrag"], True)
    assert b["id"] in [z["id"] for z in v["zahlungen"]]  # samt den übrigen Zahlungen an denselben Empfänger
    summe = sum(Decimal(str(z["betrag"])) for z in v["zahlungen"])
    assert Decimal(str(v["gezahlt_gesamt"])) == summe and summe != 0
    assert abs(Decimal(str(v["gezahlt_12_monate"]))) <= abs(summe)  # nur was im letzten Jahr gebucht wurde
    # Zuordnung lösen – ein neuer Import ordnet die Buchung nicht wieder zu
    assert client.patch(f"/api/buchungen/{b['id']}", json={"contract_id": None}).json()["vertrag"] is None
    upload(client, acc, FIXTURE)
    client.post("/api/contracts/redetect")
    assert client.get(f"/api/buchungen/{b['id']}").json()["vertrag"] is None
    # Schlagworte: ohne „#“, ohne Doppelte, über die Suche auffindbar
    r = client.patch(f"/api/buchungen/{b['id']}", json={"tags": ["#Urlaub", "urlaub", " Portugal 2026 "]}).json()
    assert r["tags"] == ["Urlaub", "Portugal 2026"]
    assert client.get("/api/tags").json() == [{"tag": "Portugal 2026", "anzahl": 1}, {"tag": "Urlaub", "anzahl": 1}]
    assert [x["id"] for x in client.get("/api/buchungen", params={"suche": "#urlaub"}).json()["buchungen"]] == [b["id"]]
    assert client.patch(f"/api/buchungen/{b['id']}", json={"contract_id": 9999}).status_code == 404
    r = client.patch(f"/api/buchungen/{b['id']}", json={"contract_id": v["id"]}).json()
    assert r["vertrag"]["name"] == v["name"]


def test_eigener_vertrag_sammelt_passende_buchungen(client):
    """Zinsen schwanken stark – von Hand als Vertrag angelegt, gehören trotzdem alle Monate dazu."""
    from bankpocket.db import TransactionRow

    acc = make_account(client, name="Verrechnungskonto", quelle="trade_republic")
    with client.app.state.ctx.session_factory() as s:
        for m, betrag in enumerate([1.51, 0.97, 0.14, 3.90, 4.34, 0.53, 2.93], start=3):
            s.add(TransactionRow(account_id=acc, buchungsdatum=date(2026, m, 1), betrag=betrag, gegenpartei="Zinsen",
                                 verwendungszweck="2 % p.a.", buchungstext="INTEREST_PAYOUT", kategorie="Zinsen",
                                 hash=f"z{m}"))
        s.add(TransactionRow(account_id=acc, buchungsdatum=date(2026, 9, 12), betrag=-20, gegenpartei="REWE", hash="r"))
        s.commit()
    letzte = client.get("/api/buchungen", params={"konto": acc, "suche": "Zinsen"}).json()["buchungen"][0]
    r = client.post(f"/api/buchungen/{letzte['id']}/vertrag", json={"turnus": "monatlich"}).json()
    v = client.get(f"/api/contracts/{r['vertrag']['id']}").json()
    assert len(v["zahlungen"]) == 7 and v["vorkommen"] == 7 and v["naechste_faelligkeit"] == "2026-10-01"
    # die Erkennung schlägt denselben Vertrag nicht noch einmal vor
    assert client.get("/api/contracts").json()["vorschlaege"] == []


def test_zinsen_mit_schwankendem_betrag_werden_erkannt(client):
    from bankpocket.db import TransactionRow

    acc = make_account(client, name="Verrechnungskonto", quelle="trade_republic")
    with client.app.state.ctx.session_factory() as s:
        for m, betrag in enumerate([0.01, 1.51, 0.97, 0.14, 3.90, 4.34, 0.53, 2.93], start=2):
            s.add(TransactionRow(account_id=acc, buchungsdatum=date(2026, m, 1), betrag=betrag, gegenpartei="Zinsen",
                                 buchungstext="INTEREST_PAYOUT", kategorie="Zinsen", hash=f"z{m}"))
        s.commit()
    client.post("/api/contracts/redetect")
    [v] = client.get("/api/contracts").json()["vorschlaege"]
    assert (v["name"], v["turnus"], v["vorkommen"], v["typ"]) == ("Zinsen", "monatlich", 8, "einnahme")
    assert v["betrag"] == 1.95  # Mitte der letzten sechs Monate (Ausreißer zählen nicht)


def test_selbst_eingetragene_buchung_aendern_und_loeschen(client):
    bar = client.post("/api/accounts", json={"name": "Bargeld", "quelle": "manuell", "typ": "giro",
                                             "gruppe": "Tägliche Konten"}).json()["id"]
    client.post(f"/api/accounts/{bar}/transactions", json={"datum": "2026-10-01", "betrag": "-8.90", "gegenpartei": "Bäcker"})
    [b] = client.get("/api/buchungen", params={"konto": bar}).json()["buchungen"]
    assert client.get(f"/api/buchungen/{b['id']}").json()["bearbeitbar"] is True
    r = client.patch(f"/api/buchungen/{b['id']}", json={"datum": "2026-09-20", "betrag": "-9.50", "gegenpartei": "Markt"}).json()
    assert (r["datum"], r["betrag"], r["gegenpartei"]) == ("2026-09-20", -9.5, "Markt")
    # Stand mit Datum in der Vergangenheit eintragen
    client.post(f"/api/accounts/{bar}/stand", json={"saldo": "50", "datum": "2026-09-25"})
    assert {x["datum"] for x in client.get("/api/buchungen", params={"konto": bar}).json()["buchungen"]} == {
        "2026-09-20", "2026-09-25"}
    assert client.delete(f"/api/buchungen/{b['id']}").status_code == 204
    # Buchungen von der Bank bleiben, wie sie sind
    acc = make_account(client)
    upload(client, acc, FIXTURE)
    bank = client.get("/api/buchungen", params={"konto": acc}).json()["buchungen"][0]
    assert client.patch(f"/api/buchungen/{bank['id']}", json={"datum": "2026-01-01"}).status_code == 400
    assert client.delete(f"/api/buchungen/{bank['id']}").status_code == 400


def test_wertverlauf_einer_position(client):
    from bankpocket.db import Connection, Holding, Price, TransactionRow

    with client.app.state.ctx.session_factory() as s:
        tr = Connection(art="trade_republic", bank="trade_republic", name="TR", blz="", server_url="", login_enc="", pin_enc="")
        s.add(tr)
        s.flush()
        vid = tr.id
        s.commit()
    cash = make_account(client, name="Verrechnungskonto", quelle="trade_republic")
    depot = make_account(client, name="Depot", quelle="trade_republic", gruppe="Sparkonten", typ="depot")
    with client.app.state.ctx.session_factory() as s:
        from bankpocket.db import Account
        for a in (cash, depot):
            s.get(Account, a).connection_id = vid
        s.add(Holding(account_id=depot, datum=date(2026, 10, 1), symbol="IE00WELT", name="MSCI World", menge=3, kurs=110,
                      wert=330, einstand=100))
        s.add_all(Price(symbol="IE00WELT", datum=d, kurs=k) for d, k in
                  [(date(2026, 9, 1), 100), (date(2026, 9, 15), 100), (date(2026, 10, 1), 110)])
        s.add(TransactionRow(account_id=cash, buchungsdatum=date(2026, 9, 10), betrag=-100, gegenpartei="MSCI World",
                             verwendungszweck="Sparplan ausgeführt", kategorie="Sparen", hash="k1"))
        s.commit()
    v = client.get(f"/api/accounts/{depot}/positionen/IE00WELT").json()
    # am 1.9. lagen erst 2 Stück im Depot (der Kauf vom 10.9. fehlte noch), danach 3
    assert [(p["d"], p["w"], p["eingezahlt"]) for p in v["punkte"]] == [
        ("2026-09-01", 200, 200), ("2026-09-15", 300, 300), ("2026-10-01", 330, 300)]
    assert (v["gewinn"], v["gewinn_prozent"], len(v["kaeufe"])) == (30, 10.0, 1)
    assert client.get(f"/api/accounts/{depot}/positionen/GIBTSNICHT").status_code == 404


def test_neue_buchungen_einzeln_und_alle_als_gelesen(client):
    acc = make_account(client)
    upload(client, acc, FIXTURE)

    def neu():
        return client.get("/api/accounts").json()["gruppen"][0]["konten"][0]["ungesehen"]

    alle = client.get("/api/buchungen", params={"konto": acc}).json()["buchungen"]
    anzahl = neu()
    assert anzahl == len(alle) and not any(b["gesehen"] for b in alle)  # Ansehen der Liste markiert nichts
    client.post("/api/buchungen/gesehen", json={"ids": [alle[0]["id"]]})
    assert neu() == anzahl - 1
    client.post("/api/buchungen/gesehen", json={"konto": acc})
    assert neu() == 0


def test_kontostand_bei_csv_konto_eintragen(client):
    """Ein CSV-Auszug ohne Saldo-Spalte: Der Stand wird von Hand gesetzt, die Buchungen bleiben wie importiert."""
    acc = client.post("/api/accounts", json={"name": "Consors", "quelle": "csv", "typ": "giro",
                                             "gruppe": "Tägliche Konten"}).json()["id"]
    daten = csv_rows("01.09.2026;01.09.2026;Firma;Gehalt;Lohn;;EUR;2000,00;EUR",
                     "10.09.2026;10.09.2026;Vermieter;Dauerauftrag;Miete;;EUR;-800,00;EUR")

    def konto():
        return next(k for g in client.get("/api/accounts").json()["gruppen"] for k in g["konten"] if k["id"] == acc)

    upload(client, acc, daten)
    anzahl = len(client.get("/api/buchungen", params={"konto": acc}).json()["buchungen"])
    assert konto()["stand_setzbar"] and not konto()["manuell"]
    r = client.post(f"/api/accounts/{acc}/stand", json={"saldo": "1234.56"})
    assert r.status_code == 200 and konto()["saldo"] == 1234.56
    assert len(client.get("/api/buchungen", params={"konto": acc}).json()["buchungen"]) == anzahl  # keine Korrekturbuchung
    client.post(f"/api/accounts/{acc}/stand", json={"saldo": "-50"})  # korrigieren geht jederzeit
    assert konto()["saldo"] == -50


DEPOT_CSV = """Depot;Inhaber;Portfolio Ansicht;Exportdatum
123456789;Erika Muster;Kompakt;01.10.2026, 19:25:34

Gesamtdepot
Gesamtdepotwert (EUR);Entwicklung seit Kauf (EUR);Entwicklung seit Kauf (%);Entwicklung Heute (EUR);Entwicklung Heute (%)
700,00;100,00;16,67;1,00;0,10
Positionen
Name;WKN;Gattung;Stück/Nominal;Einstandskurs inkl. NK;Einstandskurs inkl. NK Währung/Prozent;Einstandswert;Einstandswert Währung;Kurs;Kurs Währung/Prozent;Datum/Uhrzeit;Handelsplatz;Gesamtwert;Gesamtwert Währung
WELT ETF 1C;A1XB5U;ETF;4,00;100,00;EUR;400,00;EUR;125,00;EUR;01.10.2026 22:03:10;Tradegate;500,00;EUR
RENTEN FONDS;A40SPN;Fonds;5,00;50,00;EUR;250,00;EUR;40,00;EUR;01.10.2026 11:00:00;Fondsgesellschaft;200,00;EUR
""".encode()


def test_depotuebersicht_importieren(client):
    acc = client.post("/api/accounts", json={"name": "Consors Depot", "quelle": "csv", "typ": "giro",
                                             "gruppe": "Tägliche Konten"}).json()["id"]
    r = client.post(f"/api/accounts/{acc}/import", files={"file": ("depot.csv", DEPOT_CSV)}).json()
    assert (r["depot"], r["importiert"], r["wert"], r["stand"]) == (True, 2, 700, "2026-10-01")
    konto = next(k for g in client.get("/api/accounts").json()["gruppen"] for k in g["konten"] if k["id"] == acc)
    assert (konto["typ"], konto["gruppe"], konto["saldo"]) == ("depot", "Sparkonten", 700)
    p = client.get(f"/api/accounts/{acc}/positionen").json()
    assert [(x["name"], x["symbol"], x["wert"], x["gewinn"], x["gewinn_prozent"]) for x in p["positionen"]] == [
        ("WELT ETF 1C", "A1XB5U", 500, 100, 25.0), ("RENTEN FONDS", "A40SPN", 200, -50, -20.0)]
    assert (p["gewinn"], p["gewinn_prozent"]) == (50, 7.7)
    # eine Depotübersicht gehört nicht in ein Konto mit Buchungen
    giro = make_account(client)
    upload(client, giro, FIXTURE)
    assert client.post(f"/api/accounts/{giro}/import", files={"file": ("depot.csv", DEPOT_CSV)}).status_code == 422


def test_konto_loeschen(client):
    from bankpocket.db import Balance, Holding, TransactionRow

    acc = client.post("/api/accounts", json={"name": "Altes Depot", "quelle": "csv", "typ": "giro",
                                             "gruppe": "Tägliche Konten"}).json()["id"]
    client.post(f"/api/accounts/{acc}/import", files={"file": ("depot.csv", DEPOT_CSV)})
    giro = make_account(client)
    upload(client, giro, FIXTURE)
    assert client.delete(f"/api/accounts/{acc}").status_code == 204
    konten = [k["id"] for g in client.get("/api/accounts").json()["gruppen"] for k in g["konten"]]
    assert acc not in konten and giro in konten
    with client.app.state.ctx.session_factory() as s:
        for tabelle in (TransactionRow, Balance, Holding):
            assert s.query(tabelle).filter_by(account_id=acc).count() == 0
        assert s.query(TransactionRow).filter_by(account_id=giro).count() > 0  # andere Konten bleiben unberührt
    assert client.delete(f"/api/accounts/{acc}").status_code == 404


def test_konten_reihenfolge(client):
    a = make_account(client, name="A")
    b = make_account(client, name="B")
    c = make_account(client, name="C")

    def namen():
        return [k["name"] for k in client.get("/api/accounts").json()["gruppen"][0]["konten"]]

    assert namen() == ["A", "B", "C"]
    assert client.put("/api/accounts/reihenfolge", json={"ids": [c, a, b]}).json() == {"ok": True}
    assert namen() == ["C", "A", "B"]
    make_account(client, name="D")  # neue Konten stehen hinten, bis man sie einsortiert
    assert namen() == ["C", "A", "B", "D"]


def test_sparen_ist_eigener_abschnitt_bei_den_vertraegen(client):
    from bankpocket.db import TransactionRow

    acc = make_account(client, name="Verrechnungskonto", quelle="trade_republic")
    with client.app.state.ctx.session_factory() as s:
        for m in range(4, 10):
            s.add(TransactionRow(account_id=acc, buchungsdatum=date(2026, m, 2), betrag=-25 if m < 9 else -50,
                                 gegenpartei="MSCI World", verwendungszweck="Sparplan ausgeführt",
                                 buchungstext="TRADING_SAVINGSPLAN_EXECUTED", kategorie="Sparen", hash=f"s{m}"))
        s.commit()
    upload(client, make_account(client), FIXTURE)
    vertraege_bestaetigen(client)
    v = client.get("/api/contracts").json()
    [abschnitt] = v["sparen"]
    [plan] = abschnitt["vertraege"]
    assert (plan["name"], plan["sparen"], plan["betrag_gestiegen"], plan["vorheriger_betrag"]) == ("MSCI World", True, True, -25)
    assert abschnitt["summe"] == 50 and v["sparen_monatlich"] == 50
    # in den Ausgaben taucht der Sparplan nicht mehr auf
    assert "MSCI World" not in [c["name"] for a in v["ausgaben"] for c in a["vertraege"]]
    assert [c["name"] for a in v["ausgaben"] for c in a["vertraege"]] == ["Streamflix GmbH"]


def test_konto_in_andere_gruppe_verschieben(client):
    acc = make_account(client, name="Tagesgeld")
    assert client.patch(f"/api/accounts/{acc}", json={"gruppe": "Sparkonten"}).json() == {"ok": True}
    gruppen = {g["name"]: [k["name"] for k in g["konten"]] for g in client.get("/api/accounts").json()["gruppen"]}
    assert gruppen["Sparkonten"] == ["Tagesgeld"] and gruppen["Tägliche Konten"] == []
    assert client.patch(f"/api/accounts/{acc}", json={"gruppe": "Gibt es nicht"}).status_code == 422


def test_umbuchungen_paaren(client):
    """Sichere Paare automatisch, unsichere als Frage, von Hand wählbar – und nie ein erkannter Händler."""
    from bankpocket.db import TransactionRow
    from bankpocket.service import markiere_interne_umbuchungen

    giro = make_account(client, name="Giro")
    tr = make_account(client, name="Verrechnungskonto", quelle="trade_republic")
    with client.app.state.ctx.session_factory() as s:
        def b(konto, tag, betrag, name="", intern=False, h=[0]):
            h[0] += 1
            t = TransactionRow(account_id=konto, buchungsdatum=date(2026, 9, tag), betrag=betrag, gegenpartei=name,
                               verwendungszweck="", hash=f"p{h[0]}", intern=intern)
            s.add(t)
            s.flush()
            return t.id
        ab1, zu1 = b(giro, 1, -500, "Trade Republic Bank"), b(tr, 2, 500, "Einzahlung", intern=True)   # sicher
        ab2, zu2 = b(giro, 10, -80, "Max Muster"), b(tr, 11, 80, "Eingang")                             # unsicher
        b(giro, 15, -45, "REWE Markt GmbH"), b(tr, 15, 45, "Gutschrift")                                # Händler: nein
        markiere_interne_umbuchungen(s)
        s.commit()
    detail = client.get(f"/api/buchungen/{ab1}").json()
    assert detail["intern"] and detail["gegenbuchung"]["id"] == zu1 and detail["gegenbuchung"]["konto_name"] == "Verrechnungskonto"
    [frage] = client.get("/api/umbuchungen/fragen").json()
    assert (frage["abgang"]["id"], frage["zugang"]["id"]) == (ab2, zu2) and 55 <= frage["sicherheit"] < 80
    assert client.get("/api/unklar").json()["umbuchungen"][0]["abgang"]["id"] == ab2
    # von Hand wählen: die Kandidatenliste nennt die passende Buchung
    assert [k["id"] for k in client.get(f"/api/buchungen/{ab2}/gegenbuchungen").json()] == [zu2]
    r = client.post("/api/umbuchungen", json={"a": ab2, "b": zu2}).json()
    assert r["intern"] and r["gegenbuchung"]["id"] == zu2 and client.get("/api/umbuchungen/fragen").json() == []
    # lösen und ablehnen: wird danach nicht mehr vorgeschlagen
    assert client.delete(f"/api/umbuchungen/{ab2}").status_code == 204
    assert client.get(f"/api/buchungen/{zu2}").json()["gegenbuchung"] is None
    client.post("/api/umbuchungen/ablehnen", json={"a": ab2, "b": zu2})
    assert client.get(f"/api/buchungen/{ab2}/gegenbuchungen").json() == []
    assert client.post("/api/umbuchungen", json={"a": ab1, "b": ab2}).status_code == 422


def _buchungen(client, acc, *zeilen):
    """(Datum, Betrag, Name, IBAN) direkt in die Datenbank – wie nach einem Abruf."""
    from bankpocket.db import TransactionRow

    with client.app.state.ctx.session_factory() as s:
        for datum, betrag, name, iban in zeilen:
            s.add(TransactionRow(account_id=acc, buchungsdatum=datum, betrag=betrag, gegenpartei=name,
                                 iban_gegenpartei=iban, hash=f"{acc}{datum}{betrag}{name}"))
        s.commit()
    client.post("/api/contracts/redetect")


def _vertrag(client, name):
    v = client.get("/api/contracts").json()
    return next(c for g in v["ausgaben"] for c in g["vertraege"] if name in c["name"])


def test_zahlung_mit_anderem_betrag_zaehlt_fuer_bestaetigten_vertrag(tmp_path):
    """Spende von 20 auf 22,50 erhöht, Handyrechnung einmal nur 1,28: gezahlt ist gezahlt, nicht überfällig."""
    client = make_client(tmp_path, today=date(2026, 10, 4))
    acc = make_account(client)
    _buchungen(client, acc, *[(date(2026, m, 27), -20, "Spendenverein", "DE01") for m in (5, 6, 7, 8)],
               *[(date(2026, m, 27), -38.5, "Handy GmbH", "DE02") for m in (5, 6, 7, 8)])
    vertraege_bestaetigen(client)
    assert _vertrag(client, "Spendenverein")["status"] == "ueberfaellig"
    _buchungen(client, acc, (date(2026, 9, 29), -22.5, "Spendenverein", "DE01"),
               (date(2026, 9, 22), -30, "Handy GmbH", "DE02"),  # Aufladung zwischendurch – weiter weg vom Termin
               (date(2026, 9, 29), -1.28, "Handy GmbH", "DE02"))
    spende, handy = _vertrag(client, "Spendenverein"), _vertrag(client, "Handy")
    assert (spende["status"], spende["letzte_zahlung"], spende["naechste_faelligkeit"]) == ("aktiv", "2026-09-29", "2026-10-29")
    assert (spende["betrag"], spende["betrag_gestiegen"], spende["vorheriger_betrag"]) == (-22.5, True, -20)
    # die Ausnahme-Rechnung zählt als Zahlung, ändert aber den erwarteten Betrag nicht
    assert (handy["status"], handy["letzte_zahlung"], handy["betrag"]) == ("aktiv", "2026-09-29", -38.5)
    # Bleibt es beim neuen Betrag, entsteht daraus kein zweiter Vorschlag neben dem bestätigten Vertrag
    _buchungen(client, acc, *[(date(2026, m, 28), -22.5, "Spendenverein", "DE01") for m in (10, 11)])
    assert client.get("/api/contracts").json()["vorschlaege"] == []
    assert _vertrag(client, "Spendenverein")["letzte_zahlung"] == "2026-11-28"


def test_von_hand_zugeordnete_zahlung_bleibt_beim_erkannten_vertrag(tmp_path):
    """Abo läuft jetzt über eine andere Karte (anderer Name): einmal zuordnen, künftige Zahlungen kommen von selbst."""
    client = make_client(tmp_path, today=date(2026, 10, 4))
    acc = make_account(client)
    # „n/a“ im IBAN-Feld (Kartenzahlung) ist keine IBAN – sonst landen alle Kartenzahlungen in einer Gruppe
    _buchungen(client, acc, *[(date(2026, m, 7), -21.42, "CLAUDE SUB ANTHR", "n/a") for m in (5, 6, 7, 8)],
               *[(date(2026, m, 20), -21.42, "Ganz anderer Laden", "n/a") for m in (5, 6)],
               (date(2026, 9, 6), -21.42, "CLAUDE ABO", ""))
    vertraege_bestaetigen(client)
    abo = _vertrag(client, "CLAUDE")
    assert (abo["status"], abo["vorkommen"]) == ("ueberfaellig", 4)
    neu = next(b for b in client.get("/api/buchungen", params={"konto": acc}).json()["buchungen"]
               if b["gegenpartei"] == "CLAUDE ABO")
    client.patch(f"/api/buchungen/{neu['id']}", json={"contract_id": abo["id"]})
    assert _vertrag(client, "CLAUDE")["status"] == "aktiv"
    _buchungen(client, acc, (date(2026, 10, 6), -21.42, "CLAUDE ABO", ""))  # der Abgleich lässt die Zuordnung stehen
    abo = _vertrag(client, "CLAUDE")
    assert (abo["status"], abo["letzte_zahlung"], abo["naechste_faelligkeit"]) == ("aktiv", "2026-10-06", "2026-11-06")


def test_vertragsdaten_kuendigungsfrist_und_erinnerung(tmp_path):
    client = make_client(tmp_path, today=date(2026, 10, 4))
    acc = make_account(client)
    _buchungen(client, acc, *[(date(2026, m, 1), -16.01, "WGV Versicherung", "DE03") for m in (6, 7, 8, 9, 10)])
    vertraege_bestaetigen(client)
    c = _vertrag(client, "WGV")
    assert c["kuendigung"] is None and c["jaehrlich"] == pytest.approx(192.12)
    # Laufzeit bis 31.12., drei Monate Frist, verlängert sich um ein Jahr: der Termin 30.09. ist schon vorbei
    r = client.patch(f"/api/contracts/{c['id']}", json={"art": "Hausrat", "frist_wert": 3, "frist_einheit": "monate",
                                                         "laufzeit_bis": "2026-12-31", "verlaengerung_monate": 12}).json()
    assert r["kuendigung"] == {"frist": "3 Monate", "kuendigen_bis": "2027-09-30", "ende": "2027-12-31", "tage": 361,
                               "jederzeit": False, "verpasst": False}
    assert r["name"] == c["name"]  # Name bleibt, die Erkennung darf ihn weiter pflegen
    # ein Monat Frist: bis 30.11. – wer kündigen will, bekommt jetzt (≤ 30 Tage wären es am 31.10.) noch nichts
    r = client.patch(f"/api/contracts/{c['id']}", json={"frist_wert": 1, "kuendigen": True}).json()
    assert r["kuendigung"]["kuendigen_bis"] == "2026-11-30" and r["kuendigen"] is True
    assert not [h for h in client.get("/api/hinweise").json() if h["art"] == "kuendigen"]

    v = client.get("/api/versicherungen").json()
    assert [(o["arten"], o["art_eingetragen"]) for o in v["vertraege"]] == [(["Hausrat"], True)]
    # ein Vertrag, zwei Versicherungen: beide gelten als erfasst
    client.patch(f"/api/contracts/{c['id']}", json={"art": "Hausrat, Fahrrad / E-Bike"})
    v = client.get("/api/versicherungen").json()
    assert v["vertraege"][0]["arten"] == ["Hausrat", "Fahrrad / E-Bike"]
    # wo der Vertrag liegt und was im Schadensfall gilt
    r = client.patch(f"/api/contracts/{c['id']}", json={"verwaltet_ueber": "app", "verwaltet_name": "Getsafe", "versichert": "haushalt",
                                                         "selbstbeteiligung": 150, "kontakt": "0341 123456"}).json()
    assert (r["verwaltet_ueber"], r["verwaltet_name"], r["versichert"], r["selbstbeteiligung"]) == ("app", "Getsafe", "haushalt", 150)
    assert client.patch(f"/api/contracts/{c['id']}", json={"selbstbeteiligung": None}).json()["selbstbeteiligung"] is None
    assert client.patch(f"/api/contracts/{c['id']}", json={"verwaltet_ueber": "irgendwas"}).status_code == 422
    v = client.get("/api/versicherungen").json()
    assert v["vertraege"][0]["kostenanteil"] == 1.0 and v["monatlich"] == pytest.approx(16.01)
    assert v["naechste_kuendigung"]["kuendigen_bis"] == "2026-11-30"
    assert "Hausrat" not in v["nicht_erfasst"] and "Privathaftpflicht" in v["nicht_erfasst"]
    assert len(v["arten"]) == 30 and len(set(v["arten"])) == 30  # Auswahl: die 30 verbreitetsten Arten
    assert v["jaehrlich"] == pytest.approx(192.12)

    # Felder lassen sich wieder leeren: ohne Laufzeit ist der Vertrag jederzeit kündbar – Erinnerung sofort
    r = client.patch(f"/api/contracts/{c['id']}", json={"laufzeit_bis": None}).json()
    assert r["kuendigung"]["jederzeit"] and r["kuendigung"]["ende"] == "2026-11-04"
    [h] = [h for h in client.get("/api/hinweise").json() if h["art"] == "kuendigen"]
    assert "kündigen" in h["titel"]


def test_kuendigungs_erinnerung_in_stufen(tmp_path):
    from bankpocket.db import ContractRow, Notice
    from bankpocket.service import pruefe_kuendigungen

    client = make_client(tmp_path)
    ctx = client.app.state.ctx
    with ctx.session_factory() as s:
        s.add(ContractRow(schluessel="x", name="Fitnessstudio", kategorie="Fitness", turnus="monatlich", typ="ausgabe",
                          erwarteter_betrag=-30, naechste_faelligkeit=date(2026, 11, 1), bestaetigt=True, kuendigen=True,
                          frist_wert=4, frist_einheit="wochen", laufzeit_bis=date(2026, 12, 31)))  # kündigen bis 03.12.
        s.commit()
        for tag, erwartet in [(date(2026, 10, 30), 0), (date(2026, 11, 5), 1), (date(2026, 11, 20), 1),
                              (date(2026, 11, 27), 2), (date(2026, 12, 2), 3), (date(2026, 12, 3), 3), (date(2026, 12, 10), 3)]:
            pruefe_kuendigungen(ctx.notifier, s, tag, push=False)
            assert len(list(s.scalars(select(Notice)))) == erwartet, tag


def test_jahresanalyse_und_sparen(client):
    acc = make_account(client)
    zeilen = [(date(2026, m, 28), 2000, "Firma AG", "DE10") for m in range(1, 10)]
    zeilen += [(date(2026, m, 5), -1200, "Vermieter", "DE11") for m in range(1, 10)]
    zeilen += [(date(2026, m, 12), -15, "Sea-Watch e.V.", "DE12") for m in range(1, 10)]
    zeilen += [(date(2025, 12, 12), -500, "Vermieter", "DE11")]
    zeilen += [(date(2026, m, 7), -175, "Finanzamt Leipzig I", "DE13") for m in (3, 6, 9)] + [(date(2026, 8, 3), 312.5, "Finanzamt Leipzig I", "DE13")]
    _buchungen(client, acc, *zeilen)
    # eine Bankprämie mit „steuerfrei“ im Text ist keine Steuererstattung, die Kfz-Steuer aber eine Steuerzahlung
    from bankpocket.analysen import ist_steuer
    from bankpocket.db import TransactionRow
    praemie = TransactionRow(betrag=200, gegenpartei="ING-DiBa AG.", verwendungszweck="Prämien sind bis zu 256 Euro pro Jahr steuerfrei")
    kfz = TransactionRow(betrag=-220, gegenpartei="Zoll", verwendungszweck="Kfz-Steuer fuer B OB 3008")
    berater = TransactionRow(betrag=-90, gegenpartei="Steuerberater Müller", verwendungszweck="Rechnung 12")
    assert (ist_steuer(praemie), ist_steuer(kfz), ist_steuer(berater)) == (False, True, False)
    j = client.get("/api/analysen/jahr", params={"jahr": 2026}).json()
    assert (j["einnahmen"], j["ausgaben"], len(j["verlauf"])) == (18312.5, 11460, 12)
    assert j["verlauf"][0]["monat"] == "2026-01" and j["vorjahr"]["ausgaben"] == 500
    spenden, zahlungen, erstattungen = j["steuer"]
    assert (zahlungen["kategorie"], zahlungen["summe"], zahlungen["steuern"]) == ("Steuerzahlungen", 525, True)
    assert (erstattungen["kategorie"], erstattungen["summe"], erstattungen["art"]) == ("Steuererstattungen", 312.5, "einnahme")
    steuerbuchungen = client.get("/api/analysen/buchungen", params={"jahr": 2026, "steuern": True}).json()["buchungen"]
    assert len(steuerbuchungen) == 3 and steuerbuchungen[0]["steuer"] is True
    # eine Buchung aus der Steuerliste nehmen (war etwas anderes) – und wieder automatisch einordnen lassen
    raus = steuerbuchungen[0]["id"]
    assert client.patch(f"/api/buchungen/{raus}", json={"steuer": "nein"}).json()["steuer"] is False
    assert client.get("/api/analysen/jahr", params={"jahr": 2026}).json()["steuer"][1]["summe"] == 350
    assert len(client.get("/api/analysen/buchungen", params={"jahr": 2026, "steuern": True}).json()["buchungen"]) == 2
    # auch eine Spende lässt sich aus der Liste nehmen, ohne ihre Kategorie zu ändern
    spende = client.get("/api/analysen/buchungen", params={"jahr": 2026, "kategorie": "Spenden"}).json()["buchungen"][0]
    client.patch(f"/api/buchungen/{spende['id']}", json={"steuer": "nein"})
    assert client.get("/api/analysen/jahr", params={"jahr": 2026}).json()["steuer"][0]["summe"] == 120
    assert len(client.get("/api/analysen/buchungen", params={"jahr": 2026, "kategorie": "Spenden", "steuerliste": True}).json()["buchungen"]) == 8
    for i in (raus, spende["id"]):
        client.patch(f"/api/buchungen/{i}", json={"steuer": ""})
    assert spenden["kategorie"] == "Spenden" and spenden["summe"] == 135
    assert spenden["empfaenger"] == [{"name": "Sea-Watch e.V.", "summe": 135, "anzahl": 9}]
    b = client.get("/api/analysen/buchungen", params={"jahr": 2026, "kategorie": "Spenden",
                                                      "empfaenger": "Sea-Watch e.V."}).json()["buchungen"]
    assert len(b) == 9

    sp = client.get("/api/sparen").json()  # heute 1.10.2026: sechs volle Monate April–September
    assert sp["monate"] == 6 and len(sp["verlauf"]) == 12 and sp["sparplaene"] == []
    # April–September: 6 × (2000 − 1215) + 312,50 Erstattung − 2 × 175 Finanzamt
    assert sp["uebrig_monatlich"] == pytest.approx((6 * 785 + 312.5 - 350) / 6)


def test_gehaltsmonat_im_detail(tmp_path):
    client = make_client(tmp_path, today=date(2026, 10, 4))
    acc = make_account(client)
    zeilen = [(date(2026, m, 25), 2000, "Firma AG Gehalt", "DE20") for m in range(5, 10)]
    zeilen += [(date(2026, m, 28), -900, "Hausverwaltung Miete", "DE21") for m in range(5, 10)]
    zeilen += [(date(2026, m, 10), -30, "Fitnessstudio", "DE22") for m in range(6, 10)]
    zeilen += [(date(2026, 9, 30), -80, "Baumarkt", ""), (date(2026, 10, 1), -120, "Auslage für Anna", ""),
               (date(2026, 10, 2), 15, "Erstattung Bahn", "")]
    _buchungen(client, acc, *zeilen)
    with client.app.state.ctx.session_factory() as s:  # Gehalt als solches ausweisen (sonst „Sonstige Einnahmen“)
        from bankpocket.db import TransactionRow
        for t in s.scalars(select(TransactionRow).where(TransactionRow.gegenpartei == "Firma AG Gehalt")):
            t.kategorie = "Lohn / Gehalt"
        s.commit()
    client.post("/api/contracts/redetect")
    vertraege_bestaetigen(client)
    g = client.get("/api/gehalt").json()
    # seit dem Gehalt am 25.09.: Miete bezahlt, Fitness (10.10.) kommt noch; Baumarkt und Auslage sind Sonstiges
    assert g["start"] == "2026-09-25" and g["detail"] == {"einnahmen": 2015, "vertraege": 930, "sparen": 0, "sonstige": 200}
    assert g["offen"]["vertraege"] == 30 and g["verfuegbar"] == 885 and g["ausgaben"] == 1130
    # vier abgeschlossene Gehaltsmonate davor: 2000 − 900 (− 30 Fitness ab Juni)
    assert [v["frei"] for v in g["verlauf"]] == [1070, 1070, 1070, 1070]
    b = client.get("/api/gehalt/buchungen", params={"art": "vertraege"}).json()
    assert [x["gegenpartei"] for x in b["buchungen"]] == ["Hausverwaltung Miete"] and b["offen"][0]["name"] == "Fitnessstudio"
    # die Auslage nicht berücksichtigen
    auslage = next(x for x in client.get("/api/gehalt/buchungen", params={"art": "sonstige"}).json()["buchungen"]
                   if x["gegenpartei"] == "Auslage für Anna")
    assert client.patch(f"/api/buchungen/{auslage['id']}", json={"ausgeschlossen": True}).json()["ausgeschlossen"]
    g = client.get("/api/gehalt").json()
    assert (g["detail"]["sonstige"], g["verfuegbar"], g["ausgeschlossen"]) == (80, 1005, 1)
    assert len(client.get("/api/gehalt/buchungen", params={"art": "ausgeschlossen"}).json()["buchungen"]) == 1

    # geteilter Vertrag: von der Miete zahle ich die Hälfte – in der Vertragsübersicht zählt mein Anteil
    miete = _vertrag(client, "Hausverwaltung")
    r = client.patch(f"/api/contracts/{miete['id']}", json={"anteil_prozent": 50}).json()
    assert (r["betrag"], r["mein_betrag"], r["monatlich"], r["anteil_prozent"]) == (-900, -450, 450, 50)
    assert client.get("/api/contracts").json()["ausgaben_monatlich"] == 480
    # … und genauso überall sonst: Analysen, frei verfügbar, Liste der Buchungen
    m = client.get("/api/analysen/monat", params={"monat": "2026-08"}).json()
    assert m["ausgaben"] == 480 and {k["kategorie"]: k["summe"] for k in m["kategorien"]}["Miete"] == 450
    g = client.get("/api/gehalt").json()
    assert (g["detail"]["vertraege"], g["verfuegbar"]) == (480, 1455)  # 450 Miete + 30 Fitness; 2015 − 480 − 80
    b = client.get("/api/gehalt/buchungen", params={"art": "vertraege"}).json()["buchungen"][0]
    assert (b["betrag"], b["mein_betrag"]) == (-900, -450)
    assert len(client.get("/api/gehalt/buchungen", params={"art": "ausgaben"}).json()["buchungen"]) == 2
    # nicht berücksichtigte Buchungen fehlen auch in den Analysen
    okt = client.get("/api/analysen/monat", params={"monat": "2026-10"}).json()
    assert okt["ausgaben"] == 0 and okt["einnahmen"] == 15
    # Rückzahlung: die 15 € Erstattung der Bahn mindern die Ausgaben für „Mobilität“, statt Einnahme zu sein
    erstattung = client.get("/api/buchungen", params={"suche": "Erstattung Bahn"}).json()["buchungen"][0]
    r = client.patch(f"/api/buchungen/{erstattung['id']}", json={"rueckzahlung": True, "kategorie": "Mobilität"}).json()
    assert r["rueckzahlung"] and r["kategorie"] == "Mobilität"
    okt = client.get("/api/analysen/monat", params={"monat": "2026-10"}).json()
    assert (okt["einnahmen"], okt["ausgaben"]) == (0, -15)
    g = client.get("/api/gehalt").json()
    assert (g["detail"]["einnahmen"], g["detail"]["sonstige"], g["verfuegbar"]) == (2000, 65, 1455)  # unterm Strich gleich
    assert client.patch(f"/api/buchungen/{auslage['id']}", json={"rueckzahlung": True}).status_code == 400  # nur Eingänge
    client.patch(f"/api/buchungen/{erstattung['id']}", json={"rueckzahlung": False})
    assert client.get(f"/api/buchungen/{erstattung['id']}").json()["kategorie"] != "Mobilität"  # Kategorie neu wählen

    # gekündigt: keine Erinnerung mehr, und nach dem Enddatum wird nichts mehr eingeplant
    fitness = _vertrag(client, "Fitness")
    r = client.patch(f"/api/contracts/{fitness['id']}", json={"kuendigen": True, "gekuendigt_zum": "2026-10-05"}).json()
    assert r["kuendigen"] is False and r["gekuendigt_zum"] == "2026-10-05"
    assert client.get("/api/gehalt").json()["offen"]["vertraege"] == 0
    assert "Fitnessstudio" not in [e["name"] for t in client.get("/api/kalender").json()["tage"] for e in t["eintraege"]]
    assert client.patch(f"/api/contracts/{miete['id']}", json={"anteil_prozent": 0}).status_code == 422


def test_bereich_was_kostet_die_wohnung(client):
    """Miete, Strom und der Rundfunkbeitrag zusammen – der Schnitt pro Monat samt Aufschlüsselung."""
    acc = make_account(client)
    zeilen = [(date(2026, m, 3), -900, "Hausverwaltung Miete", "DE31") for m in range(4, 10)]
    zeilen += [(date(2026, m, 5), -60, "Stadtwerke Strom", "DE32") for m in range(4, 10)]
    zeilen += [(date(2026, m, 15), -55.08, "Rundfunk ARD, ZDF, DRadio", "DE33") for m in (5, 8)]
    zeilen += [(date(2026, 9, 20), -40, "REWE Markt", ""), (date(2026, 9, 21), 300, "Untermieterin", "DE34")]
    _buchungen(client, acc, *zeilen)
    vertraege_bestaetigen(client)
    v = client.get("/api/bereiche").json()
    wohnung = next(x for x in v["vorlagen"] if x["name"] == "Wohnung")
    assert wohnung["kategorien"] == ["Miete", "Strom", "Internet & Telefon"] and len(wohnung["vertraege"]) == 1  # Rundfunk
    bid = client.post("/api/bereiche", json=wohnung).json()["id"]
    d = client.get(f"/api/bereiche/{bid}").json()
    # sechs volle Monate (April–September): 6 × 960 + 2 × 55,08
    assert d["zeitraum"] == 6 and d["schnitt"] == pytest.approx((6 * 960 + 110.16) / 6)
    # Schnitt über drei Monate (Juli–September) bzw. zwölf – es gibt aber erst sechs Monate mit Buchungen
    d3 = client.get(f"/api/bereiche/{bid}", params={"fenster": 3}).json()
    assert (d3["zeitraum"], d3["von"]) == (3, "2026-07") and d3["schnitt"] == pytest.approx((3 * 960 + 55.08) / 3)
    d12 = client.get(f"/api/bereiche/{bid}", params={"fenster": 12}).json()
    assert d12["zeitraum"] == 6 and d12["schnitt"] == d["schnitt"] and len(d12["monate"]) == 13
    assert [(p["name"], p["art"]) for p in d["posten"]] == [("Hausverwaltung Miete", "vertrag"), ("Stadtwerke Strom", "vertrag"),
                                                           ("Rundfunk ARD, ZDF, DRadio", "vertrag")]
    assert d["fix_monatlich"] == pytest.approx(960 + 55.08 / 3)
    assert [x["summe"] for x in d["monate"]][-2:] == [960, 0]  # September, laufender Oktober
    assert len(client.get(f"/api/bereiche/{bid}/buchungen", params={"monat": "2026-08"}).json()["buchungen"]) == 3
    # ein Posten „Kategorie“ führt zu seinen Buchungen: was in der Kategorie liegt, aber kein Vertrag ist
    _buchungen(client, acc, (date(2026, 7, 9), -165, "Mieterverein Kaution", ""))
    kaution = client.get("/api/buchungen", params={"suche": "Kaution"}).json()["buchungen"][0]
    client.patch(f"/api/buchungen/{kaution['id']}", json={"kategorie": "Miete"})
    posten = client.get(f"/api/bereiche/{bid}/buchungen", params={"kategorie": "Miete"}).json()["buchungen"]
    assert [x["gegenpartei"] for x in posten] == ["Mieterverein Kaution"]
    client.patch(f"/api/buchungen/{kaution['id']}", json={"ausgeschlossen": True})  # für die Zahlen darunter wieder herausnehmen
    # Einnahmen in einer gewählten Kategorie mindern die Kosten (Untermiete)
    client.post("/api/kategorien", json={"name": "Untermiete", "typ": "einnahme"})
    untermiete = client.get("/api/buchungen", params={"suche": "Untermieterin"}).json()["buchungen"][0]
    client.patch(f"/api/buchungen/{untermiete['id']}", json={"kategorie": "Untermiete"})
    d = client.put(f"/api/bereiche/{bid}", json={**wohnung, "kategorien": [*wohnung["kategorien"], "Untermiete"]}).json()
    assert d["monate"][-2]["summe"] == 660 and "Wohnung" not in [x["name"] for x in client.get("/api/bereiche").json()["vorlagen"]]
    assert client.delete(f"/api/bereiche/{bid}").status_code == 204


def test_eigener_name_als_gegenseite_ist_eine_umbuchung(client):
    """Geld von oder zu einem eigenen, nicht angebundenen Konto: am eigenen Namen als Gegenseite erkannt."""
    from bankpocket.db import TransactionRow

    giro = make_account(client)
    with client.app.state.ctx.session_factory() as s:
        for i, (wer, fix) in enumerate([("Max Mustermann", False), ("MUSTERMANN, MAX", False), ("Maxi Mustermann", False),
                                        ("Erika Mustermann", False), ("Max Mustermann", True), ("REWE", False)]):
            s.add(TransactionRow(account_id=giro, buchungsdatum=date(2026, 9, 1 + i), betrag=-10 - i, gegenpartei=wer,
                                 verwendungszweck="", hash=f"n{i}", intern=False, intern_fix=fix))
        s.commit()
    assert client.get("/api/einstellungen").json()["eigene_namen"] == ""
    r = client.put("/api/einstellungen/eigene-namen", json={"namen": " Max Mustermann ,"}).json()
    assert r == {"eigene_namen": "Max Mustermann", "neu_markiert": 2, "zurueckgenommen": 0}
    with client.app.state.ctx.session_factory() as s:
        interne = {t.hash for t in s.query(TransactionRow).filter_by(intern=True)}
    assert interne == {"n0", "n1"}  # andere Vornamen und von Hand festgelegte Buchungen bleiben
    assert client.put("/api/einstellungen/eigene-namen", json={"namen": "Max Mustermann"}).json()["neu_markiert"] == 0
    # Name geändert oder gelöscht: was nur wegen des Namens Umbuchung war, zählt wieder normal
    r = client.put("/api/einstellungen/eigene-namen", json={"namen": "Erika Mustermann"}).json()
    with client.app.state.ctx.session_factory() as s:
        assert {t.hash for t in s.query(TransactionRow).filter_by(intern=True)} == {"n3"}
    assert client.put("/api/einstellungen/eigene-namen", json={"namen": ""}).json()["zurueckgenommen"] == 1
    with client.app.state.ctx.session_factory() as s:
        assert not s.query(TransactionRow).filter_by(intern=True).count()


def _roh_buchungen(client, konto, zeilen):
    """(Hash, Tag, Betrag, Gegenpartei[, Felder]) direkt anlegen – wie von einem Abruf oder Import."""
    from bankpocket.db import TransactionRow
    with client.app.state.ctx.session_factory() as s:
        for h, tag, betrag, wer, *mehr in zeilen:
            s.add(TransactionRow(account_id=konto, buchungsdatum=date(2026, 9, tag), betrag=betrag, gegenpartei=wer,
                                 verwendungszweck="", hash=h, **(mehr[0] if mehr else {})))
        s.commit()


def test_csv_import_verdoppelt_keine_vorhandenen_roh_buchungen(client):
    """Ältere Historie per CSV in ein angebundenes Konto: Der Abruf nennt dieselbe Buchung mit anderem Text."""
    from bankpocket.db import TransactionRow

    giro = make_account(client)
    _roh_buchungen(client, giro, [("abruf1", 15, Decimal("-12.99"), "STREAMFLIX GMBH SEPA"),
                              ("abruf2", 20, Decimal("-4.50"), "BAECKEREI KARTE"),
                              ("abruf3", 20, Decimal("-4.50"), "BAECKEREI KARTE")])
    kopf = "Buchung;Valuta;Sender / Empfänger;IBAN;BIC;Buchungstext;Verwendungszweck;Betrag;Währung\n"
    zeile = "{0}.09.2026;{0}.09.2026;{1};DE02100100100006820101;X;Lastschrift;{2};{3};EUR\n"
    csv = (kopf + zeile.format("15", "Streamflix GmbH", "Abo", "-12,99") + zeile.format("20", "Bäckerei", "Brot", "-4,50")
           + zeile.format("20", "Bäckerei", "Kuchen", "-4,50") + zeile.format("20", "Bäckerei", "Kaffee", "-4,50")
           + zeile.format("01", "Vermieter", "Miete", "-700,00")).encode()
    r = upload(client, giro, csv)
    assert (r["importiert"], r["duplikate"]) == (2, 3)  # dritte Bäckerei-Buchung und die Miete sind neu
    assert upload(client, giro, csv)["importiert"] == 0  # derselbe Export noch einmal ändert nichts
    with client.app.state.ctx.session_factory() as s:
        assert s.query(TransactionRow).filter_by(account_id=giro).count() == 5


def test_konto_loeschen_nennt_folgen_und_zusammenfuehren_behaelt_alles(client):
    from bankpocket.db import Account, Connection, TransactionRow

    alt = make_account(client, name="Altes CSV-Konto", quelle="csv")
    upload(client, alt, FIXTURE)
    vertraege_bestaetigen(client)
    folgen = client.get(f"/api/accounts/{alt}/folgen").json()
    assert folgen["buchungen"] > 5 and folgen["vertraege"] >= 1 and folgen["beispiele"]

    neu = make_account(client, name="Bankkonto")
    with client.app.state.ctx.session_factory() as s:  # das neue Konto hängt an einer Verbindung
        conn = Connection(bank="ing", name="ING", blz="50010517", server_url="https://x", login_enc="x", pin_enc="x")
        s.add(conn)
        s.flush()
        s.get(Account, neu).connection_id = conn.id
        alte = s.query(TransactionRow).filter_by(account_id=alt).order_by(TransactionRow.buchungsdatum.desc()).all()
        gleiche, eine = alte[0], alte[1]
        kategorie_vorher, vertrag_vorher = gleiche.kategorie, gleiche.contract_id
        s.add(TransactionRow(account_id=neu, buchungsdatum=gleiche.buchungsdatum, betrag=gleiche.betrag,
                             gegenpartei="ANDERER TEXT VOM ABRUF", verwendungszweck="", hash="vom-abruf"))
        s.add(TransactionRow(account_id=neu, buchungsdatum=date(2026, 10, 1), betrag=Decimal("-1.23"),
                             gegenpartei="Nur im Abruf", verwendungszweck="", hash="nur-abruf"))
        s.commit()
        gleiche_id, anzahl_alt = gleiche.id, len(alte)
    assert client.post(f"/api/accounts/{neu}/zusammenfuehren", json={"ziel_id": alt}).status_code == 409
    r = client.post(f"/api/accounts/{alt}/zusammenfuehren", json={"ziel_id": neu}).json()
    assert r == {"uebernommen": anzahl_alt, "doppelt": 1, "ziel_id": neu}
    with client.app.state.ctx.session_factory() as s:
        assert s.get(Account, alt) is None
        zeilen = s.query(TransactionRow).filter_by(account_id=neu).all()
        assert len(zeilen) == anzahl_alt + 1  # die doppelte nur einmal, „Nur im Abruf“ bleibt
        g = s.get(TransactionRow, gleiche_id)
        assert (g.hash, g.kategorie, g.contract_id) == ("vom-abruf", kategorie_vorher, vertrag_vorher)
    # die Verträge sind noch da und aktiv
    assert client.get(f"/api/accounts/{neu}/folgen").json()["vertraege"] == folgen["vertraege"]


def test_rueckzahlung_gehoert_zum_vertrag_ohne_ihn_zu_verschieben(client):
    """Eine Erstattung des Anbieters wird am Vertrag eingetragen: sie steht bei den Zahlungen und mindert die
    Kosten, ändert aber weder letzte Zahlung noch erwarteten Betrag."""
    acc = make_account(client)
    upload(client, acc, csv_rows(
        "28.09.2026;28.09.2026;Musterfirma AG;Gutschrift;Gehalt September;900,00;EUR;2.500,00;EUR",
        "28.08.2026;28.08.2026;Musterfirma AG;Gutschrift;Gehalt August;900,00;EUR;2.500,00;EUR",
        "28.07.2026;28.07.2026;Musterfirma AG;Gutschrift;Gehalt Juli;900,00;EUR;2.500,00;EUR",
        "29.09.2026;29.09.2026;Streamflix GmbH;Gutschrift;Erstattung Abo;900,00;EUR;5,00;EUR",
        "15.09.2026;15.09.2026;Streamflix GmbH;Lastschrift;Abo Mandatsref: MR-100;900,00;EUR;-12,99;EUR",
        "15.08.2026;15.08.2026;Streamflix GmbH;Lastschrift;Abo Mandatsref: MR-100;900,00;EUR;-12,99;EUR",
        "15.07.2026;15.07.2026;Streamflix GmbH;Lastschrift;Abo Mandatsref: MR-100;900,00;EUR;-12,99;EUR"))
    vertraege_bestaetigen(client)
    vertrag = _vertrag(client, "Streamflix")
    vorher = client.get(f"/api/contracts/{vertrag['id']}").json()
    assert len(vorher["zahlungen"]) == 3 and vorher["rueckzahlungen"] == 0
    # die Auswahl „Rückzahlung eintragen“ kennt nur Geldeingänge
    eingaenge = client.get("/api/buchungen", params={"eingaenge": True}).json()["buchungen"]
    assert [b["betrag"] for b in eingaenge if b["betrag"] < 100] == [5]
    erstattung = next(b for b in eingaenge if b["betrag"] == 5)
    # ein Geldeingang, der keine Rückzahlung ist, gehört nicht zu einem Ausgaben-Vertrag
    r = client.patch(f"/api/buchungen/{erstattung['id']}", json={"contract_id": vertrag["id"]})
    assert r.status_code == 400
    r = client.patch(f"/api/buchungen/{erstattung['id']}",
                     json={"rueckzahlung": True, "contract_id": vertrag["id"], "kategorie": vorher["kategorie"]})
    assert r.status_code == 200 and r.json()["vertrag"]["id"] == vertrag["id"]
    nachher = client.get(f"/api/contracts/{vertrag['id']}").json()
    assert [(z["betrag"], z["rueckzahlung"]) for z in nachher["zahlungen"]] == [
        (5, True), (-12.99, False), (-12.99, False), (-12.99, False)]
    assert (nachher["rueckzahlungen"], nachher["gezahlt_gesamt"]) == (5, -33.97)
    for feld in ("letzte_zahlung", "naechste_faelligkeit", "vorkommen", "turnus"):
        assert nachher[feld] == vorher[feld], feld
    # der Betrag des Vertrags ist, was nach der Rückzahlung unterm Strich gezahlt wurde: 12,99 − 5,00
    assert (nachher["betrag"], nachher["letzte_zahlung_betrag"], nachher["letzte_zahlung_netto"]) == (-7.99, -12.99, -7.99)
    assert abs(nachher["jaehrlich"] - 7.99 * 12) < 0.01
    # die Rückzahlung wieder lösen und neu eintragen: der Betrag folgt
    client.patch(f"/api/buchungen/{erstattung['id']}", json={"rueckzahlung": False})
    assert client.get(f"/api/contracts/{vertrag['id']}").json()["betrag"] == -12.99
    client.patch(f"/api/buchungen/{erstattung['id']}",
                 json={"rueckzahlung": True, "contract_id": vertrag["id"], "kategorie": vorher["kategorie"]})
    assert client.get(f"/api/contracts/{vertrag['id']}").json()["betrag"] == -7.99
    # auch ein späterer Abgleich ändert daran nichts
    upload(client, acc, csv_rows("15.10.2026;15.10.2026;Streamflix GmbH;Lastschrift;Abo Mandatsref: MR-100;900,00;EUR;-12,99;EUR"))
    nach_abgleich = client.get(f"/api/contracts/{vertrag['id']}").json()
    assert nach_abgleich["betrag"] == vorher["betrag"] and len(nach_abgleich["zahlungen"]) == 5
    # in „vom Gehalt verfügbar“ mindert die Rückzahlung die Kosten der Verträge, nicht die der sonstigen Ausgaben
    erst = client.get("/api/gehalt/buchungen", params={"art": "vertraege"}).json()["buchungen"]
    assert 5 in [b["betrag"] for b in erst]
    # Rückzahlung zurücknehmen: sie zählt wieder als Einnahme und gehört nicht mehr zum Vertrag
    client.patch(f"/api/buchungen/{erstattung['id']}", json={"rueckzahlung": False})
    assert client.get(f"/api/buchungen/{erstattung['id']}").json()["vertrag"] is None
    assert len(client.get(f"/api/contracts/{vertrag['id']}").json()["zahlungen"]) == 4


def test_betrag_eines_vertrags_von_hand_festlegen(client):
    acc = make_account(client)
    upload(client, acc, FIXTURE)
    vertraege_bestaetigen(client)
    vertrag = _vertrag(client, "Streamflix")
    assert (vertrag["betrag"], vertrag["betrag_fix"]) == (-12.99, False)
    r = client.patch(f"/api/contracts/{vertrag['id']}", json={"betrag": "9.99"}).json()
    assert (r["betrag"], r["betrag_fix"], r["betrag_gestiegen"]) == (-9.99, True, False)
    assert abs(r["monatlich"] - 9.99) < 0.01 and abs(r["jaehrlich"] - 9.99 * 12) < 0.01
    # neue Buchungen und Abgleiche lassen den festgelegten Betrag stehen
    upload(client, acc, csv_rows("15.10.2026;15.10.2026;Streamflix GmbH;Lastschrift;Abo Mandatsref: MR-100 "
                                 "Gläubiger-ID: DE98ZZZ09999999999;900,00;EUR;-14,99;EUR"))
    d = client.get(f"/api/contracts/{vertrag['id']}").json()
    assert (d["betrag"], d["betrag_fix"], d["letzte_zahlung"]) == (-9.99, True, "2026-10-15")
    # „automatisch“: wieder aus den Buchungen
    r = client.patch(f"/api/contracts/{vertrag['id']}", json={"betrag_automatisch": True}).json()
    assert r["betrag_fix"] is False and r["betrag"] != -9.99
    # Null und Negatives sind keine Beträge
    assert client.patch(f"/api/contracts/{vertrag['id']}", json={"betrag": "0"}).status_code == 422
    assert client.patch(f"/api/contracts/{vertrag['id']}", json={"betrag": "-5"}).status_code == 422



def test_health_nennt_die_version(client, monkeypatch, tmp_path):
    from bankpocket import version
    assert client.get("/api/health").json()["ok"] is True
    datei = tmp_path / "VERSION"
    monkeypatch.setattr(version, "DATEI", datei)
    assert version.gelesen() == "entwicklung"  # ohne Datei
    datei.write_text("abc1234\n")
    monkeypatch.setattr(version, "GESTARTET", "abc1234")
    h = client.get("/api/health").json()
    assert (h["version"], h["gestartet"]) == ("abc1234", "abc1234")
    datei.write_text("def5678\n")  # neuer Code liegt auf der Platte, der laufende ist noch der alte
    h = client.get("/api/health").json()
    assert (h["version"], h["gestartet"]) == ("def5678", "abc1234")
