from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from bankpocket.api import create_app
from bankpocket.config import Settings
from bankpocket.contracts import categorize
from conftest import vertraege_bestaetigen

FIXTURE = (Path(__file__).parent / "fixtures" / "ing_synthetic.csv").read_bytes()
HEUTE = date(2026, 10, 1)


def client(tmp_path):
    return TestClient(create_app(Settings(data_dir=tmp_path, auth=False, scheduler=False), today=lambda: HEUTE))


def test_eigene_kategorie_und_regel_wirken_auf_alt_und_neu(tmp_path):
    c = client(tmp_path)
    acc = c.post("/api/accounts", json={"name": "Giro", "quelle": "ing", "typ": "giro", "gruppe": "Tägliche Konten"}).json()["id"]
    c.post(f"/api/accounts/{acc}/import", files={"file": ("x.csv", FIXTURE)})

    assert c.post("/api/kategorien", json={"name": "Abos", "emoji": "📺"}).status_code == 201
    assert c.post("/api/kategorien", json={"name": "Abos"}).status_code == 409
    assert c.post("/api/kategorien", json={"name": "abos", "typ": "einnahme"}).status_code == 409  # auch anders geschrieben
    # eigene Kategorien gelten in beide Richtungen: „Bob“ für Geld von Bob passt auch für Geld an Bob
    assert c.post("/api/kategorien", json={"name": "Bob", "typ": "einnahme"}).status_code == 201
    k = c.get("/api/kategorien").json()
    assert "Bob" in k["ausgabe"] and "Bob" in k["einnahme"] and "Abos" in k["einnahme"]
    r = c.post("/api/regeln", json={"stichwort": "Streamflix", "kategorie": "Abos"}).json()
    assert r["geaendert"] == 3

    k = c.get("/api/kategorien").json()
    assert "Abos" in k["ausgabe"] and k["emoji"]["Abos"] == "📺"
    assert k["regeln"][0]["stichwort"] == "streamflix"
    # vorhandene Buchungen und der erkannte Vertrag folgen der Regel
    assert {b["kategorie"] for b in c.get("/api/buchungen", params={"suche": "streamflix"}).json()["buchungen"]} == {"Abos"}
    vertraege_bestaetigen(c)
    assert c.get("/api/contracts").json()["ausgaben"][0]["vertraege"][0]["kategorie"] == "Abos"
    # künftige Buchungen ebenso
    assert categorize("STREAMFLIX GMBH", "") == "Abos"
    assert categorize("Musterfirma AG", "Gehalt", "einnahme") == "Lohn / Gehalt"  # nur gleicher Typ
    assert c.post("/api/budgets", json={"kategorie": "Abos", "limit": "30"}).status_code == 201

    regel_id = k["regeln"][0]["id"]
    assert c.delete(f"/api/regeln/{regel_id}").status_code == 204
    assert categorize("STREAMFLIX GMBH", "") == "Sonstiges"
    assert c.delete("/api/kategorien/Abos").status_code == 204
    assert c.delete("/api/kategorien/Miete").status_code == 404  # eingebaute bleiben


def test_regeln_werden_beim_start_geladen(tmp_path):
    c = client(tmp_path)
    c.post("/api/regeln", json={"stichwort": "Bäckerei Krume", "kategorie": "Lebensmittel"})
    from bankpocket.contracts import regeln_setzen
    regeln_setzen([])
    client(tmp_path)  # Neustart
    assert categorize("BAECKEREI", "Bäckerei Krume Filiale 3") == "Lebensmittel"


def test_kalender(tmp_path):
    c = client(tmp_path)
    acc = c.post("/api/accounts", json={"name": "Giro", "quelle": "ing", "typ": "giro", "gruppe": "Tägliche Konten"}).json()["id"]
    c.post(f"/api/accounts/{acc}/import", files={"file": ("x.csv", FIXTURE)})
    vertraege_bestaetigen(c)
    c.post("/api/contracts", json={"name": "Hausrat", "kategorie": "Versicherung", "turnus": "monatlich",
                                   "betrag": "-10", "naechste_faelligkeit": "2026-10-20"})
    k = c.get("/api/kalender", params={"tage": 45}).json()
    daten = [(t["datum"], [e["name"] for e in t["eintraege"]]) for t in k["tage"]]
    assert daten == [("2026-10-15", ["Streamflix GmbH"]), ("2026-10-20", ["Hausrat"]),
                     ("2026-10-28", ["Musterfirma AG"]), ("2026-11-15", ["Streamflix GmbH"])]
    assert k["monat_ausgaben"] == 22.99 and k["monat_einnahmen"] == 2500


def test_unklare_buchungen_zuordnen(tmp_path):
    from bankpocket.db import TransactionRow
    c = client(tmp_path)
    acc = c.post("/api/accounts", json={"name": "Karte", "quelle": "norwegian", "typ": "kreditkarte",
                                        "gruppe": "Tägliche Konten"}).json()["id"]
    with c.app.state.ctx.session_factory() as s:
        for i, (name, betrag) in enumerate([("PAYPAL *BUMMBUMM", -12), ("PAYPAL *BUMMBUMM", -8), ("HAPPYHAIR 24", -25),
                                            ("REWE Markt", -30), ("Ich selbst", -500)]):
            s.add(TransactionRow(account_id=acc, buchungsdatum=date(2026, 9, 1 + i), betrag=betrag, gegenpartei=name,
                                 hash=f"u{i}"))
        s.commit()
    u = c.get("/api/unklar").json()
    assert u["anzahl"] == 4  # REWE erkennt die Händlerliste
    erste = u["gruppen"][0]
    assert (erste["haendler"], erste["anzahl"], erste["summe"]) == ("PAYPAL *BUMMBUMM", 2, -20)
    # Händler zuordnen und merken: gilt für beide vorhandenen und für künftige Buchungen
    r = c.post("/api/unklar", json={"ids": erste["ids"], "kategorie": "Freizeit", "merken": True,
                                    "haendler": erste["haendler"]}).json()
    assert (r["zugeordnet"], r["offen"]) == (2, 2)
    assert categorize("PAYPAL *BUMMBUMM", "") == "Freizeit"
    # Umbuchung und bewusstes „Sonstiges“ gelten ebenfalls als erledigt
    rest = {g["haendler"]: g for g in c.get("/api/unklar").json()["gruppen"]}
    c.post("/api/unklar", json={"ids": rest["Ich selbst"]["ids"], "umbuchung": True})
    c.post("/api/unklar", json={"ids": rest["HAPPYHAIR 24"]["ids"], "kategorie": "Sonstiges"})
    assert c.get("/api/unklar").json()["anzahl"] == 0
    assert c.post("/api/unklar", json={"ids": [1], "kategorie": "Gibt es nicht"}).status_code == 422


def test_unterkategorien_symbole_und_umbenennen(tmp_path):
    from datetime import date as d
    from bankpocket.db import Account, TransactionRow

    c = TestClient(create_app(Settings(data_dir=tmp_path, auth=False, scheduler=False), today=lambda: d(2026, 10, 4)))
    with c.app.state.ctx.session_factory() as s:
        acc = Account(name="Giro", quelle="ing", typ="giro", gruppe="Tägliche Konten")
        s.add(acc)
        s.flush()
        for i, (name, betrag) in enumerate([("REWE Markt", -40), ("Bäckerei Schmidt", -6), ("Bäckerei Schmidt", -4)]):
            s.add(TransactionRow(account_id=acc.id, buchungsdatum=d(2026, 9, 10 + i), betrag=betrag, gegenpartei=name, hash=f"u{i}"))
        s.commit()
    # Unterkategorie von „Lebensmittel“ – steht in der Auswahl direkt dahinter
    assert c.post("/api/kategorien", json={"name": "Bäcker", "emoji": "🥐", "ober": "Lebensmittel"}).status_code == 201
    k = c.get("/api/kategorien").json()
    assert k["ober"] == {"Bäcker": "Lebensmittel"} and k["ausgabe"][k["ausgabe"].index("Lebensmittel") + 1] == "Bäcker"
    # nur eine Ebene, und nur bekannte Oberkategorien
    assert c.post("/api/kategorien", json={"name": "Brötchen", "ober": "Bäcker"}).status_code == 422
    assert c.post("/api/kategorien", json={"name": "Brötchen", "ober": "Gibt es nicht"}).status_code == 422
    c.post("/api/regeln", json={"stichwort": "bäckerei schmidt", "kategorie": "Bäcker"})
    # in den Analysen zählt die Unterkategorie bei „Lebensmittel“ mit und steht darunter einzeln
    m = c.get("/api/analysen/monat", params={"monat": "2026-09"}).json()
    [lm] = m["kategorien"]
    assert (lm["kategorie"], lm["summe"], lm["anzahl"]) == ("Lebensmittel", 50, 3)
    assert lm["unter"] == [{"kategorie": "Bäcker", "summe": 10, "anzahl": 2}]
    buchungen = lambda kat: len(c.get("/api/analysen/buchungen", params={"monat": "2026-09", "kategorie": kat}).json()["buchungen"])  # noqa: E731
    assert (buchungen("Lebensmittel"), buchungen("Bäcker")) == (3, 2)
    # ein Budget für die Oberkategorie umfasst die Unterkategorie
    c.post("/api/budgets", json={"kategorie": "Lebensmittel", "limit": 100})
    # eigenes Symbol auch für eine eingebaute Kategorie
    assert c.patch("/api/kategorien/Lebensmittel", json={"emoji": "🥦"}).status_code == 200
    assert c.patch("/api/kategorien/Lebensmittel", json={"name": "Essen"}).status_code == 422  # eingebaut: kein Umbenennen
    # umbenennen zieht Buchungen und Regeln mit
    assert c.patch("/api/kategorien/Bäcker", json={"name": "Backwaren", "emoji": "🥖"}).json() == {"name": "Backwaren"}
    k = c.get("/api/kategorien").json()
    assert k["emoji"]["Lebensmittel"] == "🥦" and k["emoji"]["Backwaren"] == "🥖" and k["ober"] == {"Backwaren": "Lebensmittel"}
    assert [r["kategorie"] for r in k["regeln"]] == ["Backwaren"] and buchungen("Backwaren") == 2
    # wieder eigenständig machen, dann löschen: die Buchungen ordnen sich automatisch neu ein
    assert c.patch("/api/kategorien/Backwaren", json={"ober": ""}).status_code == 200
    assert len(c.get("/api/analysen/monat", params={"monat": "2026-09"}).json()["kategorien"]) == 2
    assert c.delete("/api/kategorien/Backwaren").status_code == 204
