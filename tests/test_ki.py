import json

import pytest
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from fastapi.testclient import TestClient

from bankpocket.api import create_app
from bankpocket.config import Settings
from bankpocket.db import Account, TransactionRow

HEUTE = date(2026, 10, 1)


class FakeMistral:
    """Antwortet wie die Mistral-API mit JSON und merkt sich die Anfragen."""

    def __init__(self, antworten: dict[str, str]):
        self.antworten, self.anfragen = antworten, []

    def chat(self, modell, system, frage):
        self.anfragen.append({"modell": modell, "system": system, "frage": frage})
        zuordnungen = []
        for zeile in frage.split("Buchungen:\n")[1].splitlines():
            nr, rest = zeile.split(". Name: ", 1)
            name = rest.split(" | ")[0]
            zuordnungen.append({"nr": int(nr), "kategorie": self.antworten.get(name, "Sonstiges")})
        zuordnungen.append({"nr": 99, "kategorie": "Erfundene Kategorie"})  # wird verworfen
        return json.dumps({"zuordnungen": zuordnungen})


def app_mit_buchungen(tmp_path, fake):
    settings = Settings(data_dir=tmp_path, auth=False, scheduler=False, fints_product_id="TEST")
    app = create_app(settings, today=lambda: HEUTE, ki_client=lambda key: fake)
    with app.state.ctx.session_factory() as s:
        acc = Account(quelle="ing", name="Giro", typ="giro", gruppe="Tägliche Konten")
        s.add(acc)
        s.flush()
        for i, (name, zweck, betrag, text, cid) in enumerate([
            ("Kaffeerösterei Bohnenglück GmbH", "Einkauf Filiale 4711 DE12500105170648489890", -12.5, "Kartenzahlung", ""),
            ("Kaffeerösterei Bohnenglück GmbH", "Einkauf", -8.9, "Kartenzahlung", ""),
            ("Klettermax Leipzig", "Beitrag Oktober", -39, "Lastschrift", "DE11ZZZ00000012345"),
            ("REWE Markt GmbH", "Einkauf", -45.1, "Kartenzahlung", ""),  # erkennt schon die Händlerliste
            ("Anna Beispiel", "Pizza gestern", -15, "Überweisung", ""),  # Privatperson: wird nicht gesendet
        ]):
            s.add(TransactionRow(account_id=acc.id, buchungsdatum=date(2026, 9, 1 + i), betrag=D(str(betrag)),
                                 gegenpartei=name, verwendungszweck=zweck, buchungstext=text, glaeubiger_id=cid,
                                 hash=f"h{i}"))
        s.commit()
    return TestClient(app)


def test_ki_ordnet_nur_haendler_ein_und_merkt_sich_das(tmp_path):
    fake = FakeMistral({"Kaffeerösterei Bohnenglück GmbH": "Restaurants", "Klettermax Leipzig": "Fitness"})
    client = app_mit_buchungen(tmp_path, fake)
    assert client.post("/api/ki/einordnen").status_code == 409  # ohne Schlüssel
    assert client.put("/api/ki", json={"schluessel": "zu kurz!"}).status_code == 422
    stand = client.put("/api/ki", json={"schluessel": "test-schluessel-0123456789abcdef", "aktiv": True}).json()
    assert stand["schluessel_gesetzt"] and stand["aktiv"] and stand["offen"] == 2

    r = client.post("/api/ki/einordnen").json()
    assert (r["neu_eingeordnet"], r["offen"], r["eingeordnet"]) == (2, 0, 2)
    [anfrage] = fake.anfragen
    gesendet = anfrage["frage"]
    assert "Bohnenglück" in gesendet and "Klettermax" in gesendet
    assert "Anna" not in gesendet and "REWE" not in gesendet  # Privatperson und Regeltreffer bleiben hier
    assert "DE12" not in gesendet and "4711" not in gesendet  # keine IBAN, keine Nummern
    assert anfrage["modell"] == "mistral-small-latest" and "- Restaurants" in gesendet and "JSON" in anfrage["system"]

    buchungen = {b["gegenpartei"]: b for b in client.get("/api/buchungen").json()["buchungen"]}
    assert buchungen["Klettermax Leipzig"]["kategorie"] == "Fitness"
    assert buchungen["Klettermax Leipzig"]["kategorie_quelle"] == "ki"
    assert buchungen["REWE Markt GmbH"]["kategorie_quelle"] == "regel"
    assert buchungen["Anna Beispiel"]["kategorie"] == "Sonstiges"

    # zweiter Lauf fragt niemanden erneut
    client.post("/api/ki/einordnen")
    assert len(fake.anfragen) == 1
    # Vergessen setzt zurück
    assert client.delete("/api/ki/ergebnisse").status_code == 204
    assert client.get("/api/ki").json()["offen"] == 2


def test_api_fehler_wird_verstaendlich(tmp_path):
    import httpx

    from bankpocket.ki import KiFehler, MistralClient

    def antwort(status, json_daten=None):
        return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=json_daten or {})))

    gesehen = {}

    def ok(req):
        gesehen.update(json.loads(req.content), auth=req.headers["authorization"], url=str(req.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    c = MistralClient("geheim", httpx.Client(transport=httpx.MockTransport(ok)))
    assert c.chat("mistral-small-latest", "System", "Frage") == "{}"
    assert gesehen["url"] == "https://api.mistral.ai/v1/chat/completions" and gesehen["auth"] == "Bearer geheim"
    assert gesehen["model"] == "mistral-small-latest" and gesehen["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in gesehen["messages"]] == ["system", "user"]

    for status, text in ((401, "abgelehnt"), (429, "Zu viele Anfragen"), (500, "Mistral-API-Fehler (500)")):
        try:
            MistralClient("geheim", antwort(status)).chat("m", "s", "f")
            raise AssertionError("hätte scheitern müssen")
        except KiFehler as e:
            assert text in str(e)

    class Kaputt(FakeMistral):
        def chat(self, modell, system, frage):
            raise KiFehler("Der API-Schlüssel wurde abgelehnt.")

    client = app_mit_buchungen(tmp_path, Kaputt({}))
    client.put("/api/ki", json={"schluessel": "test-schluessel-0123456789abcdef"})
    r = client.post("/api/ki/einordnen")
    assert r.status_code == 502 and r.json()["detail"] == "Der API-Schlüssel wurde abgelehnt."


def test_einzelne_buchung_erkennen(tmp_path):
    fake = FakeMistral({"Anna Beispiel": "Restaurants"})
    client = app_mit_buchungen(tmp_path, fake)
    anna = next(b for b in client.get("/api/buchungen").json()["buchungen"] if b["gegenpartei"] == "Anna Beispiel")
    assert client.post(f"/api/buchungen/{anna['id']}/erkennen").status_code == 409  # ohne Schlüssel
    client.put("/api/ki", json={"schluessel": "test-schluessel-0123456789abcdef"})
    # auf ausdrücklichen Wunsch geht auch eine Überweisung an eine Privatperson raus – nur diese eine
    r = client.post(f"/api/buchungen/{anna['id']}/erkennen").json()
    assert (r["erkannt"], r["kategorie"], r["kategorie_quelle"]) == ("Restaurants", "Restaurants", "ki")
    assert "Anna Beispiel" in fake.anfragen[-1]["frage"] and "Bohnenglück" not in fake.anfragen[-1]["frage"]
    # nichts Passendes: die Buchung bleibt, wie sie ist
    rewe = next(b for b in client.get("/api/buchungen").json()["buchungen"] if b["gegenpartei"] == "Klettermax Leipzig")
    assert client.post(f"/api/buchungen/{rewe['id']}/erkennen").json()["erkannt"] is None


class FakePlaner:
    """Übersetzt wie die KI eine Frage in einen Auftrag – und merkt sich, was ihr geschickt wurde."""

    def __init__(self, antwort):
        self.antwort, self.anfragen = antwort, []

    def chat(self, modell, system, frage):
        self.anfragen.append(system + "\n" + frage)
        return self.antwort if isinstance(self.antwort, str) else json.dumps(self.antwort)


def test_frage_sendet_keine_finanzdaten_und_rechnet_lokal(tmp_path):
    fake = FakePlaner({"art": "summe", "richtung": "ausgabe", "kategorie": "Lebensmittel", "suchtext": None,
                       "von": "2026-09-01", "bis": "2026-09-30"})
    client = app_mit_buchungen(tmp_path, fake)
    assert client.post("/api/ki/frage", json={"frage": "Wie viel für Lebensmittel im September?"}).status_code == 409
    client.put("/api/ki", json={"schluessel": "test-schluessel-0123456789abcdef"})
    r = client.post("/api/ki/frage", json={"frage": "Wie viel für Lebensmittel im September?"}).json()
    assert r["summe"] == 45.1 and r["anzahl"] == 1 and "45,10 €" in r["antwort"]
    assert r["verstanden"] == "Ausgaben für Lebensmittel · 01.09.2026 – 30.09.2026"
    # nach draußen gingen nur Frage, Datum und Kategorienamen – kein Betrag, kein Empfänger, kein Verwendungszweck
    [gesendet] = fake.anfragen
    assert "Wie viel für Lebensmittel im September?" in gesendet and "Lebensmittel" in gesendet
    for geheim in ("REWE", "Bohnenglück", "Klettermax", "Anna Beispiel", "45", "12,5", "12.5", "Pizza", "DE12"):
        assert geheim not in gesendet, geheim

    # Rangliste der Empfänger, Händler aus der Frage, erfundene Kategorie wird verworfen
    fake.antwort = {"art": "empfaenger", "richtung": "ausgabe", "kategorie": "Gibt es nicht", "von": "2026-09-01",
                    "bis": "2026-09-30", "anzahl": 2}
    r = client.post("/api/ki/frage", json={"frage": "Wo gebe ich am meisten aus?"}).json()
    assert [(z["label"], z["betrag"]) for z in r["zeilen"]] == [("REWE Markt GmbH", 45.1), ("Klettermax Leipzig", 39)]
    fake.antwort = {"art": "kategorien", "richtung": "ausgabe", "von": "2026-09-01", "bis": "2026-09-30", "anzahl": 2}
    r = client.post("/api/ki/frage", json={"frage": "Wofür gebe ich am meisten aus?"}).json()
    assert [(z["label"], z["betrag"]) for z in r["zeilen"]] == [("Sonstiges", 75.4), ("Lebensmittel", 45.1)]
    fake.antwort = {"art": "vergleich", "richtung": "ausgabe", "suchtext": "bohnenglück", "von": "2026-09-01",
                    "bis": "2026-09-30", "vergleich_von": "2026-08-01", "vergleich_bis": "2026-08-31"}
    r = client.post("/api/ki/frage", json={"frage": "Bohnenglück September gegen August?"}).json()
    assert [z["betrag"] for z in r["zeilen"]] == [21.4, 0] and "21,40 € mehr" in r["antwort"]
    # unbrauchbare Antworten der KI führen zu einer Erklärung statt zu einem Fehler
    for kaputt in ("kein json", {"art": "unklar"}, {"art": "loeschen"}):
        fake.antwort = kaputt
        r = client.post("/api/ki/frage", json={"frage": "Was soll ich kaufen?"}).json()
        assert r["verstanden"] is None and r["zeilen"] == []


def test_kategorien_verlauf(tmp_path):
    client = app_mit_buchungen(tmp_path, FakePlaner("{}"))
    v = client.get("/api/analysen/kategorien-verlauf", params={"monate": 3}).json()
    assert v["monate"] == ["2026-08", "2026-09", "2026-10"]
    lebensmittel = next(k for k in v["kategorien"] if k["kategorie"] == "Lebensmittel")
    assert lebensmittel["werte"] == [0, 45.1, 0] and lebensmittel["schnitt"] == pytest.approx(22.55)
