from datetime import date
from decimal import Decimal

from bankpocket.analysen import monats_analyse
from bankpocket.db import Account, make_sessionmaker
from bankpocket.models import Transaction
from bankpocket.service import speichere_transaktionen


def _konten(tmp_path, mit_bargeld_konto: bool):
    S = make_sessionmaker(f"sqlite:///{tmp_path}/a.db")
    s = S()
    giro = Account(name="Girokonto", quelle="ing", typ="giro", gruppe="Tägliche Konten")
    s.add(giro)
    s.flush()
    speichere_transaktionen(s, giro, [
        Transaction(date(2026, 9, 1), Decimal("2000"), "Firma", "Gehalt"),
        Transaction(date(2026, 9, 5), Decimal("-100"), "Geldautomat", "Bargeldauszahlung"),
        Transaction(date(2026, 9, 6), Decimal("-40"), "REWE Markt GmbH", ""),
    ])
    if mit_bargeld_konto:
        bar = Account(name="Bargeld", quelle="manuell", typ="giro", gruppe="Tägliche Konten")
        s.add(bar)
        s.flush()
        speichere_transaktionen(s, bar, [Transaction(date(2026, 9, 5), Decimal("100"), "Geldautomat", ""),
                                         Transaction(date(2026, 9, 7), Decimal("-30"), "Wochenmarkt", "")], True)
    s.commit()
    return s


def test_bargeld_konto_vermeidet_doppelzaehlung(tmp_path):
    m = monats_analyse(_konten(tmp_path, True), date(2026, 9, 1))
    assert m["einnahmen"] == 2000  # Einzahlung ins Bargeld-Konto ist kein Einkommen
    assert m["ausgaben"] == 70  # REWE 40 + bar ausgegeben 30; die Abhebung ist nur eine Umbuchung
    assert "Bargeld" not in {k["kategorie"] for k in m["kategorien"]}


def test_ohne_bargeld_konto_zaehlt_die_abhebung(tmp_path):
    m = monats_analyse(_konten(tmp_path, False), date(2026, 9, 1))
    assert m["ausgaben"] == 140
    assert {k["kategorie"] for k in m["kategorien"]} == {"Bargeld", "Lebensmittel"}


def test_budgets_stand_und_hinweise(tmp_path):
    from bankpocket.analysen import budget_stand, pruefe_budgets
    from bankpocket.db import Budget, Notice
    from bankpocket.notify import Notifier

    s = _konten(tmp_path, mit_bargeld_konto=False)  # September: REWE 40 (Lebensmittel), Abhebung 100 (Bargeld)
    s.add_all([Budget(kategorie="Lebensmittel", limit=Decimal("45")), Budget(kategorie="Bargeld", limit=Decimal("80")),
               Budget(kategorie="Restaurants", limit=Decimal("100"))])
    s.commit()
    stand = {b["kategorie"]: b for b in budget_stand(s, date(2026, 9, 15))}
    assert stand["Lebensmittel"]["status"] == "knapp" and stand["Lebensmittel"]["rest"] == 5
    assert stand["Bargeld"]["status"] == "ueberschritten"
    assert stand["Restaurants"]["ausgegeben"] == 0 and stand["Restaurants"]["status"] == "ok"
    assert stand["Lebensmittel"]["prognose"] == Decimal("80.00")  # 40 € in 15 Tagen → 80 € im Monat

    gesendet = []
    n = Notifier(None, tmp_path, "mailto:t@x", sender=lambda a, p: gesendet.append(p), asynchron=False)
    n.push = lambda payload: gesendet.append(payload)
    for _ in range(2):  # zweiter Lauf am selben Tag: keine doppelten Hinweise
        pruefe_budgets(n, s, date(2026, 9, 15))
    titel = sorted(x.titel for x in s.query(Notice))
    assert titel == ["Budget fast aufgebraucht: Lebensmittel", "Budget überschritten: Bargeld"]
    assert len(gesendet) == 2


def test_budget_api(tmp_path):
    from fastapi.testclient import TestClient
    from bankpocket.api import create_app
    from bankpocket.config import Settings

    c = TestClient(create_app(Settings(data_dir=tmp_path, auth=False, scheduler=False), today=lambda: date(2026, 9, 15)))
    assert "Sparen" not in c.get("/api/budgets").json()["kategorien"]
    bid = c.post("/api/budgets", json={"kategorie": "Lebensmittel", "limit": "300"}).json()["id"]
    assert c.post("/api/budgets", json={"kategorie": "Lebensmittel", "limit": "200"}).status_code == 409
    assert c.post("/api/budgets", json={"kategorie": "Quatsch", "limit": "200"}).status_code == 422
    c.patch(f"/api/budgets/{bid}", json={"limit": "250"})
    daten = c.get("/api/budgets").json()
    assert daten["budgets"][0]["limit"] == 250 and "Lebensmittel" not in daten["kategorien"]
    assert c.get("/api/uebersicht").json()["budgets"][0]["kategorie"] == "Lebensmittel"
    assert c.delete(f"/api/budgets/{bid}").status_code == 204


def test_depot_vergangenheit_aus_kaeufen_zurueckgerechnet(tmp_path):
    from bankpocket.analysen import konto_verlauf, vermoegen
    from bankpocket.service import saldo_setzen

    s = make_sessionmaker(f"sqlite:///{tmp_path}/d.db")()
    from bankpocket.db import Connection
    tr = Connection(art="trade_republic", bank="trade_republic", name="Trade Republic", blz="", server_url="",
                    login_enc="", pin_enc="")
    s.add(tr)
    s.flush()
    cash = Account(name="Verrechnungskonto", quelle="trade_republic", typ="giro", gruppe="Tägliche Konten",
                   connection_id=tr.id)
    depot = Account(name="Depot", quelle="trade_republic", typ="depot", gruppe="Sparkonten", connection_id=tr.id)
    s.add_all([cash, depot])
    s.flush()
    speichere_transaktionen(s, cash, [
        Transaction(date(2026, 9, 1), Decimal("500"), "Einzahlung", "", intern=True),
        Transaction(date(2026, 9, 10), Decimal("-200"), "MSCI World", "Sparplan ausgeführt", kategorie="Sparen"),
        Transaction(date(2026, 9, 20), Decimal("-100"), "MSCI World", "Sparplan ausgeführt", kategorie="Sparen"),
    ])
    saldo_setzen(s, cash, date(2026, 10, 1), Decimal("200"))
    saldo_setzen(s, depot, date(2026, 10, 1), Decimal("330"))  # 300 € gekauft, 30 € Kursgewinn
    s.commit()
    v = konto_verlauf(s, depot, date(2026, 9, 5), date(2026, 10, 1))
    assert (v[date(2026, 9, 5)], v[date(2026, 9, 10)], v[date(2026, 9, 25)], v[date(2026, 10, 1)]) == (30, 230, 330, 330)
    # Kauf verschiebt nur Geld vom Verrechnungskonto ins Depot – das Vermögen bleibt gleich
    punkte = {p["d"]: p["w"] for p in vermoegen(s, date(2026, 10, 1), 26)["punkte"]}
    assert punkte["2026-09-05"] == punkte["2026-09-25"] == 530


def test_anfangsstand_eines_manuellen_kontos_ist_kein_zugewinn(tmp_path):
    from bankpocket.analysen import konto_verlauf
    from bankpocket.db import TransactionRow

    s = make_sessionmaker(f"sqlite:///{tmp_path}/m.db")()
    bar = Account(name="Bargeld", quelle="manuell", typ="giro", gruppe="Tägliche Konten")
    schulden = Account(name="Schulden", quelle="manuell", typ="virtuell", gruppe="Virtuell")
    s.add_all([bar, schulden])
    s.flush()
    s.add_all([
        TransactionRow(account_id=bar.id, buchungsdatum=date(2026, 10, 3), betrag=Decimal("460"),
                       gegenpartei="Stand angepasst", hash="a", intern=True),
        TransactionRow(account_id=schulden.id, buchungsdatum=date(2026, 10, 1), betrag=Decimal("-500"),
                       gegenpartei="Kredit", hash="b"),
    ])
    s.commit()
    v = konto_verlauf(s, bar, date(2026, 9, 1), date(2026, 10, 3))
    assert v[date(2026, 9, 1)] == v[date(2026, 10, 3)] == 460
    # datierte Buchungen bleiben, wie eingetragen
    v = konto_verlauf(s, schulden, date(2026, 9, 1), date(2026, 10, 3))
    assert (v[date(2026, 9, 30)], v[date(2026, 10, 1)]) == (0, -500)


def test_balken_bleiben_beim_blaettern_stehen(tmp_path):
    s = _konten(tmp_path, False)
    monate = lambda m, bis=None: [v["monat"] for v in monats_analyse(s, m, bis)["verlauf"]]  # noqa: E731
    assert monate(date(2026, 9, 1))[-1] == "2026-09"
    # ein früherer Monat im selben Fenster: die sechs Balken ändern sich nicht
    assert monate(date(2026, 6, 1), date(2026, 10, 1)) == monate(date(2026, 10, 1), date(2026, 10, 1))
    # außerhalb des Fensters rückt es gerade so weit, dass der Monat wieder zu sehen ist
    assert monate(date(2026, 3, 1), date(2026, 10, 1)) == ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    assert monate(date(2026, 11, 1), date(2026, 10, 1))[-1] == "2026-11"


def test_prognose_rechnet_durchgereichtes_geld_gegen(tmp_path):
    """1000 € von Freunden bekommen und weiterüberwiesen: Das ist kein Alltagstempo."""
    from bankpocket.analysen import gehalt_karte
    from bankpocket.db import ContractRow, TransactionRow

    S = make_sessionmaker(f"sqlite:///{tmp_path}/g.db")
    s = S()
    giro = Account(name="Girokonto", quelle="ing", typ="giro", gruppe="Tägliche Konten")
    gehalt = ContractRow(schluessel="g", name="Firma", kategorie="Lohn / Gehalt", turnus="monatlich", typ="einnahme",
                         erwarteter_betrag=Decimal("2000"), letzte_zahlung=date(2026, 9, 25),
                         naechste_faelligkeit=date(2026, 10, 25), bestaetigt=True)
    s.add_all([giro, gehalt])
    s.flush()
    zeilen = [(date(2026, 9, 25), 2000, "Firma", gehalt.id), (date(2026, 8, 10), 1000, "Freundin", None),
              (date(2026, 8, 12), -1000, "Vermieter Ferienhaus", None)]
    zeilen += [(date(2026, 7, 10) + (date(2026, 7, 20) - date(2026, 7, 10)) * i, -100, "Einkauf", None) for i in range(9)]
    for i, (d, betrag, name, cid) in enumerate(zeilen):
        s.add(TransactionRow(account_id=giro.id, buchungsdatum=d, betrag=betrag, gegenpartei=name, contract_id=cid,
                             hash=f"h{i}"))
    s.commit()
    g = gehalt_karte(s, date(2026, 10, 4))
    # 900 € Einkäufe in 87 Tagen ≈ 10,34 € am Tag – die 1000 € hin und zurück zählen nicht
    assert g["tempo_pro_tag"] == Decimal("10.34")
    assert g["verfuegbar"] == 1900 and g["prognose"] == Decimal("1683")
