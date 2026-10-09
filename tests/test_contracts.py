from datetime import date
from decimal import Decimal as D
from pathlib import Path

from bankpocket.contracts import (add_months, average_monthly_expenses, average_monthly_savings,
                                  detect_contracts, summary_by_turnus)
from bankpocket.csv_import import load_transactions, parse_amount
from bankpocket.models import Transaction

TODAY = date(2026, 10, 1)


def tx(d, amount, name="", zweck="", iban="", cid="", mref=""):
    return Transaction(d, D(str(amount)), name, zweck, iban, cid, mref)


def series(start, n, months=1, **kw):
    amount = kw.pop("amount")
    amounts = amount if isinstance(amount, list) else [amount] * n
    return [tx(add_months(start, i * months), amounts[i], **kw) for i in range(n)]


def by_name(contracts, name):
    return [c for c in contracts if name.lower() in c.name.lower()]


def test_sepa_monthly_with_price_increase():
    txs = series(date(2026, 5, 15), 5, amount=[-9.99, -9.99, -9.99, -9.99, -12.99],
                 name="Netflix International", cid="DE98ZZZ09999999999", mref="MR-1")
    [c] = detect_contracts(txs, TODAY)
    assert (c.turnus, c.methode, c.status, c.typ) == ("monatlich", "sepa", "aktiv", "ausgabe")
    assert c.betrag_gestiegen and c.vorheriger_betrag == D("-9.99")
    assert c.naechste_faelligkeit == date(2026, 10, 15)
    assert c.kategorie == "Streaming"


def test_same_creditor_different_mandates_are_separate():
    a = series(date(2026, 6, 1), 4, amount=-30, name="Immergrün", cid="DE11ZZZ00000000001", mref="A")
    b = series(date(2026, 6, 3), 4, amount=-55, name="Immergrün", cid="DE11ZZZ00000000001", mref="B")
    assert len(detect_contracts(a + b, TODAY)) == 2


def test_salary_detected_as_income():
    txs = series(date(2026, 5, 28), 5, amount=2500, name="Musterfirma AG", zweck="Gehalt")
    [c] = detect_contracts(txs, TODAY)
    assert c.typ == "einnahme" and c.kategorie == "Lohn / Gehalt"
    assert c.naechste_faelligkeit == date(2026, 10, 28)


def test_quarterly_by_iban_with_amount_tolerance():
    txs = series(date(2025, 10, 1), 4, months=3, amount=[-100, -104, -97, -103],
                 name="Beispiel Versicherung", iban="DE02100100100006820101")
    [c] = detect_contracts(txs, TODAY)
    assert c.turnus == "quartalsweise" and c.kategorie == "Versicherung"


def test_yearly_needs_only_two_occurrences():
    txs = series(date(2025, 3, 10), 2, months=12, amount=-49, name="Verein e.V.")
    [c] = detect_contracts(txs, date(2026, 4, 1))
    assert c.turnus == "jaehrlich"


def test_irregular_shopping_not_detected():
    txs = [tx(date(2026, m, d), -a, name="REWE SAGT DANKE 1234")
           for m, d, a in [(5, 3, 23.4), (5, 17, 61.2), (6, 2, 12.9), (6, 29, 45.0), (7, 11, 80.1), (8, 4, 9.5)]]
    assert detect_contracts(txs, TODAY) == []


def test_two_occurrences_monthly_is_not_enough():
    txs = series(date(2026, 8, 5), 2, amount=-20, name="Neuer Anbieter")
    assert detect_contracts(txs, TODAY) == []


def test_paypal_merchants_split():
    txs = []
    for i in range(4):
        txs.append(tx(add_months(date(2026, 6, 2), i), -9.99, "PayPal Europe S.a.r.l.",
                      "PP.1234.PP . Spotify, Ihr Einkauf bei Spotify"))
        txs.append(tx(add_months(date(2026, 6, 20), i), -13.99, "PayPal Europe S.a.r.l.",
                      "PP.5678.PP . Netflix, Ihr Einkauf bei Netflix"))
    cs = detect_contracts(txs, TODAY)
    assert {c.name for c in cs} == {"Spotify", "Netflix"} and all(c.methode == "paypal" for c in cs)


def test_overdue_and_inactive():
    txs = series(date(2026, 3, 1), 4, amount=-20, name="Altes Abo")  # letzte Zahlung 01.06.
    [c] = detect_contracts(txs, date(2026, 7, 15))
    assert c.status == "ueberfaellig" and c.tage_ueberfaellig == 14  # fällig war 01.07.
    [c] = detect_contracts(txs, date(2026, 10, 1))
    assert c.status == "inaktiv"


def test_average_monthly_expenses_ignores_inactive_and_income():
    cs = detect_contracts(
        series(date(2026, 6, 1), 4, amount=-10, name="A")
        + series(date(2025, 10, 1), 4, months=3, amount=-90, name="B", iban="DE1")
        + series(date(2026, 6, 28), 4, amount=2000, name="Chef")
        + series(date(2026, 1, 1), 3, amount=-500, name="Tot"),
        TODAY,
    )
    assert average_monthly_expenses(cs) == D("40")  # 10 + 90/3


def test_parse_amount_german():
    assert parse_amount("-1.234,56") == D("-1234.56")
    assert parse_amount("2.500,00") == D("2500.00")


def test_ing_csv_end_to_end():
    path = Path(__file__).parent / "fixtures" / "ing_synthetic.csv"
    txs = load_transactions(path)
    assert len(txs) == 6
    assert txs[0].glaeubiger_id == "DE98ZZZ09999999999" and txs[0].mandatsreferenz == "MR-100"
    cs = detect_contracts(txs, TODAY)
    assert {(c.typ, c.turnus) for c in cs} == {("ausgabe", "monatlich"), ("einnahme", "monatlich")}


def test_unknown_income_is_sonstige_einnahmen():
    [c] = detect_contracts(series(date(2026, 6, 3), 4, amount=150, name="Jonas Beispiel"), TODAY)
    assert c.kategorie == "Sonstige Einnahmen"


def test_savings_plan_not_counted_as_expense():
    cs = detect_contracts(
        series(date(2026, 6, 2), 4, amount=-100, name="Trade Republic", zweck="Sparplan")
        + series(date(2026, 6, 5), 4, amount=-20, name="Congstar"),
        TODAY,
    )
    assert {c.kategorie for c in cs} == {"Sparen", "Internet & Telefon"}
    assert average_monthly_expenses(cs) == D("20")
    assert average_monthly_savings(cs) == D("100")


def test_summary_by_turnus():
    cs = detect_contracts(
        series(date(2026, 6, 1), 4, amount=-10, name="A")
        + series(date(2026, 6, 9), 4, amount=-15, name="B")
        + series(date(2025, 10, 1), 4, months=3, amount=-90, name="C", iban="DE1")
        + series(date(2026, 6, 28), 4, amount=2000, name="Chef"),
        TODAY,
    )
    s = summary_by_turnus(cs)
    assert s["ausgabe"]["monatlich"] == {"anzahl": 2, "summe": D("25")}
    assert s["ausgabe"]["quartalsweise"]["anzahl"] == 1
    assert s["einnahme"]["monatlich"]["summe"] == D("2000")


def test_schluessel_stable_when_new_payments_arrive():
    base = series(date(2026, 5, 1), 3, amount=-10, name="Abo")
    [a] = detect_contracts(base, TODAY)
    [b] = detect_contracts(base + [tx(date(2026, 8, 1), -10.5, name="Abo")], TODAY)
    assert a.schluessel == b.schluessel


def test_supermarkt_ist_kein_vertrag():
    import random
    rnd = random.Random(7)
    txs = []
    tag = date(2025, 9, 1)
    while tag <= date(2026, 9, 30):
        if rnd.random() < 0.4:  # mehrmals pro Woche, Beträge streuen
            txs.append(tx(tag, -round(rnd.uniform(9, 78), 2), name="REWE Markt GmbH"))
        tag += __import__("datetime").timedelta(days=1)
    assert detect_contracts(txs, TODAY) == []


def test_paypal_mit_gemeinsamem_mandat_nach_haendler_getrennt():
    txs = []
    for i in range(4):
        for haendler, betrag, tag in (("Netflix", -13.99, 12), ("Spotify", -10.99, 20)):
            txs.append(tx(add_months(date(2026, 6, tag), i), betrag, "PayPal Europe S.a.r.l. et Cie S.C.A",
                          f"PP.7712.PP . {haendler}, Ihr Einkauf bei {haendler}",
                          cid="LU96ZZZ0000000000000000058", mref="GLEICHES-MANDAT"))
    cs = detect_contracts(txs, TODAY)
    assert {c.name for c in cs} == {"Netflix", "Spotify"}


def test_schwankende_zinsen_sind_ein_monatlicher_vertrag():
    txs = series(date(2026, 1, 28), 9, amount=[12, 13, 14, 12, 13, 14, 12, 13, 14], name="Consorsbank",
                 zweck="Zinsgutschrift")
    [c] = detect_contracts(txs, TODAY)
    assert (c.turnus, c.kategorie, c.typ) == ("monatlich", "Zinsen", "einnahme")


def test_ausbleibende_zahlung_bleibt_zwei_monate_ueberfaellig():
    txs = series(date(2026, 3, 18), 5, amount=120, name="Jonas Beispiel")  # letzte Zahlung 18.07.
    [c] = detect_contracts(txs, date(2026, 10, 1))
    assert (c.status, c.tage_ueberfaellig) == ("ueberfaellig", 44)
    [c] = detect_contracts(txs, date(2026, 10, 20))
    assert c.status == "inaktiv"


def test_zufaelliges_jahresmuster_bei_haeufigem_haendler_ist_kein_vertrag():
    # zwei fast gleiche Beträge im Jahresabstand, dazwischen viele andere Besuche
    txs = [tx(date(2025, 9, 13), -9.8, name="Cafe Kranich"), tx(date(2026, 9, 13), -9.8, name="Cafe Kranich")]
    besuche = [(1, 3, 4.5), (2, 19, 11.2), (3, 8, 6.9), (4, 27, 13.4), (5, 14, 5.1), (6, 2, 8.8), (7, 22, 12.0),
               (8, 11, 7.3)]
    txs += [tx(date(2026, m, t), -b, name="Cafe Kranich") for m, t, b in besuche]
    assert detect_contracts(txs, TODAY) == []


def test_echter_jahresvertrag_bleibt_erkannt():
    txs = series(date(2025, 3, 10), 2, months=12, amount=-79, name="ADAC")
    txs.append(tx(date(2025, 11, 2), -12.5, name="ADAC"))  # einmalige Zusatzleistung
    [c] = detect_contracts(txs, date(2026, 4, 1))
    assert c.turnus == "jaehrlich"


def test_gehalt_laut_buchungstext_schon_nach_zwei_monaten():
    txs = [Transaction(date(2026, 8, 31), D("2400"), "Neue Firma GmbH", "Abrechnung 08/2026", buchungstext="Gehalt/Rente"),
           Transaction(date(2026, 9, 30), D("2400"), "Neue Firma GmbH", "Abrechnung 09/2026", buchungstext="Gehalt/Rente")]
    [c] = detect_contracts(txs, TODAY)
    assert (c.turnus, c.kategorie, c.typ) == ("monatlich", "Lohn / Gehalt", "einnahme")
    # ohne Hinweis auf Gehalt bleiben zwei Zahlungen zu wenig
    assert detect_contracts([tx(t.buchungsdatum, 2400, "Neue Firma GmbH") for t in txs], TODAY) == []


def test_kategorien_aus_haendlerliste_und_buchungstext():
    from bankpocket.contracts import categorize
    assert categorize("LEIPZIGER VERKEHRSBETRIEBE", "") == "Mobilität"
    assert categorize("Fressnapf Filiale 123", "") == "Haustier"
    assert categorize("Uber Eats", "") == "Restaurants"
    assert categorize("Familienkasse", "Kindergeld", "einnahme") == "Staatliche Leistungen"
    assert categorize("Max Mustermann", "", buchungstext="Bargeldauszahlung") == "Bargeld"
    assert categorize("Firma XY", "Abrechnung", "einnahme", buchungstext="Gehalt/Rente") == "Lohn / Gehalt"


def test_zwei_aehnliche_kartenkaeufe_im_halbjahr_sind_kein_vertrag():
    # Fernbus im März und im Oktober, Preise ähnlich – Zufall, kein Abo
    txs = [tx(date(2026, 3, 28), -30.99, name="BlaBlaCar"), tx(date(2026, 10, 2), -33.49, name="BlaBlaCar")]
    assert detect_contracts(txs, date(2026, 10, 3)) == []
    # gleicher Betrag, aber ein Laden: auch kein Vertrag
    laden = series(date(2025, 4, 2), 2, months=12, amount=-59.90, name="Zalando")
    assert detect_contracts(laden, date(2026, 5, 1)) == []


def test_abo_bei_haendler_mit_vielen_einkaeufen():
    # viele Bestellungen mit wechselnden Beträgen, dazu Prime am 5. jedes Monats
    txs = series(date(2026, 3, 5), 7, amount=-8.99, name="Amazon")
    for m in range(3, 10):
        for tag, betrag in ((2, 23.4), (9, 61.25), (14, 12.9), (21, 45.0), (27, 80.1)):
            txs.append(tx(date(2026, m, (tag + m * 3) % 28 + 1), -round(betrag * (1 + m * 0.37), 2), name="Amazon"))
    [c] = detect_contracts(txs, TODAY)
    assert (c.turnus, c.erwarteter_betrag, c.vorkommen) == ("monatlich", D("-8.99"), 7)


def test_sicherheit_ordnet_vorschlaege():
    sicher = series(date(2026, 3, 15), 7, amount=-13.99, name="Netflix International",
                    cid="DE98ZZZ09999999999", mref="MR-1")
    wackelig = series(date(2025, 3, 10), 2, months=12, amount=-49, name="Irgendein Anbieter")
    [a] = detect_contracts(sicher, TODAY)
    [b] = detect_contracts(wackelig, date(2026, 4, 1))
    assert a.sicherheit >= 90 and b.sicherheit <= 50


def test_sparplan_am_2_und_16_ist_zweimal_im_monat():
    def sparplan(tag, betrag, name):
        return Transaction(tag, D(str(betrag)), name, "Sparplan ausgeführt", buchungstext="TRADING_SAVINGSPLAN_EXECUTED",
                           kategorie="Sparen")
    txs = []
    for m in range(4, 10):  # April bis September, am 2. und 16.
        txs += [sparplan(date(2026, m, 2), -10, "MSCI World"), sparplan(date(2026, m, 16), -10, "MSCI World"),
                sparplan(date(2026, m, 2), -25, "Dow Jones EU")]
    txs.append(sparplan(date(2026, 10, 1), -10, "MSCI World"))  # laufender Monat, erst eine Ausführung
    # ein Einzelkauf desselben Wertpapiers gehört nicht zum Sparplan
    txs.append(Transaction(date(2026, 7, 20), D("-300"), "MSCI World", "Kauforder", buchungstext="TRADING_TRADE_EXECUTED",
                           kategorie="Sparen"))
    dow, welt = sorted(detect_contracts(txs, date(2026, 10, 3)), key=lambda c: c.erwarteter_betrag)
    assert (dow.name, dow.turnus, dow.erwarteter_betrag, dow.kategorie) == ("Dow Jones EU", "monatlich", D("-25"), "Sparen")
    assert (welt.name, welt.turnus, welt.erwarteter_betrag, welt.methode) == (
        "MSCI World", "halbmonatlich", D("-10"), "sparplan")
    assert welt.status == "aktiv" and welt.naechste_faelligkeit == date(2026, 10, 16) and welt.sicherheit >= 90
    assert average_monthly_savings([welt, dow]) == D("45")  # 25 € + zweimal 10 € im Monat


def test_woechentlicher_vertrag_und_woechentlicher_einkauf():
    from datetime import timedelta
    start = date(2026, 7, 6)
    kurs = [tx(start + timedelta(days=7 * i), -12, name="Yogastudio Lotus") for i in range(12)]
    [c] = detect_contracts(kurs, date(2026, 9, 25))
    assert (c.turnus, c.erwarteter_betrag, c.naechste_faelligkeit) == ("woechentlich", D("-12"), date(2026, 9, 28))
    assert round(c.monatlich, 2) == D("52.14")
    # derselbe Rhythmus mit wechselnden Beträgen ist ein Wocheneinkauf
    markt = [tx(start + timedelta(days=7 * i), -(20 + i * 3), name="Wochenmarkt") for i in range(12)]
    assert detect_contracts(markt, date(2026, 9, 25)) == []
    # nach gut einem Monat ohne Zahlung ist der Kurs beendet
    [c] = detect_contracts(kurs, date(2026, 11, 20))
    assert c.status == "inaktiv"


def test_sparplan_an_festen_tagen_ist_zweimal_im_monat():
    def sparplan(tag, name):
        return Transaction(tag, D("-10"), name, "Sparplan ausgeführt", buchungstext="TRADING_SAVINGSPLAN_EXECUTED",
                           kategorie="Sparen")
    from datetime import timedelta
    fest = [sparplan(date(2026, m, t), "Gold") for m in range(4, 10) for t in (2, 16)]
    wandernd = [sparplan(date(2026, 4, 3) + timedelta(days=14 * i), "Welt") for i in range(12)]
    gold, welt = sorted(detect_contracts(fest + wandernd, date(2026, 9, 20)), key=lambda c: c.name)
    assert (gold.turnus, gold.monatlich) == ("halbmonatlich", D("20"))  # 24 Ausführungen im Jahr
    assert welt.turnus == "zweiwoechentlich" and round(welt.monatlich, 2) == D("21.73")


def test_kategorie_aus_der_haendlerart_der_karte():
    from bankpocket.contracts import categorize
    assert categorize("Irgendein Shuttle", "", buchungstext="Transportation Services, Not elsewhe") == "Mobilität"
    assert categorize("SUNEXPRESS.", "", buchungstext="Airlines, Air Carriers ( not listed ") == "Reisen"
    assert categorize("BlaBlaCar", "BlaBlaCar Paris FR") == "Mobilität"
    # der Händlername geht vor: Netflix bleibt Streaming, auch wenn die Karte „digital goods“ meldet
    assert categorize("Netflix", "", buchungstext="DIGITAL GOODS") == "Streaming"
    assert categorize("Unbekannt GmbH", "", buchungstext="Lastschrift") == "Sonstiges"
    assert categorize("AUTOSERVICE KAISER", "", buchungstext="AUTO SERVICE SHOPS/NON DEALER") == "Mobilität"
    assert categorize("Transact GA 7366", "", buchungstext="FINANCIAL INST/AUTO CASH") == "Bargeld"
    assert categorize("WEINHANDLUNG LINDNER", "", buchungstext="PKG STORES/BEER/WINE/LIQUOR") == "Lebensmittel"


def test_consors_export_mit_sender_empfaenger_und_buchungstext():
    from bankpocket.csv_import import parse_transactions
    csv = ("Buchung;Valuta;Sender / Empfänger;IBAN;BIC;Buchungstext;Verwendungszweck;Kategorie;Stichwörter;"
           "Umsatz geteilt;Betrag;Währung\n"
           "02.10.2026;02.10.2026;Telekom Deutschland GmbH;DE55200400000000000003;HYVEDEMM;"
           "Lastschrift (Einzugsermächtigung);Festnetz Vertragskonto;Kommunikation;n/a;n/a;-44,95;EUR\n").encode()
    [t] = parse_transactions(csv)
    assert (t.gegenpartei, t.buchungstext, t.betrag) == ("Telekom Deutschland GmbH", "Lastschrift (Einzugsermächtigung)", D("-44.95"))
    assert t.iban_gegenpartei == "DE55200400000000000003"


def test_beitrag_steigt_oder_faellt_nur_bei_vorher_stabilem_betrag():
    def vertrag(betraege):
        [c] = detect_contracts(series(date(2026, 4, 15), len(betraege), amount=betraege, name="Stadtwerke",
                                      cid="DE98ZZZ09999999999", mref="M1"), TODAY)
        return c.betrag_gestiegen, c.vorheriger_betrag
    assert vertrag([-60, -60, -60, -60, -72]) == (True, D("-60"))      # teurer
    assert vertrag([-60, -60, -60, -60, -49]) == (False, D("-60"))     # günstiger: vorheriger Betrag gesetzt
    assert vertrag([-60, -60, -60, -60, -60]) == (False, None)
    assert vertrag([-60, -52, -61, -48, -57]) == (False, None)         # schwankt ohnehin – kein Hinweis


def test_logo_nur_fuer_bekannte_anbieter(tmp_path):
    import httpx

    from bankpocket.logos import domain_fuer, logo_datei
    assert domain_fuer("congstar - eine Marke der Telekom Deutschland GmbH") == "congstar.de"
    assert domain_fuer("TIDAL Malmo 752") == "tidal.com" and domain_fuer("Anna Beispiel") is None
    # nur am Wortanfang, kurze Stichworte nur als ganzes Wort – Personen bekommen kein Markenlogo
    assert domain_fuer("Jan Bergmann") is None and domain_fuer("Dakota Meier") is None
    assert domain_fuer("REWE Markt GmbH") == "rewe.de" and domain_fuer("O2 Germany") == "o2online.de"
    aufrufe = []

    def antwort(req):
        aufrufe.append(str(req.url))
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG" + b"x" * 900)

    http = httpx.Client(transport=httpx.MockTransport(antwort))
    datei = logo_datei(tmp_path, "congstar.de", http)
    from bankpocket.logos import bildtyp
    assert bildtyp(datei.read_bytes()) == "image/png" and "congstar.de" in aufrufe[0]
    assert bildtyp(b"\x00\x00\x01\x00rest") == "image/x-icon" and bildtyp(b"<html>") is None
    assert logo_datei(tmp_path, "congstar.de", http) == datei and len(aufrufe) == 1  # danach aus dem Speicher
    # fremde oder krumme Adressen ruft der Server gar nicht erst ab
    assert logo_datei(tmp_path, "boese.example", http) is None and logo_datei(tmp_path, "../etc/passwd", http) is None
    assert len(aufrufe) == 1


def test_schwankendes_gehalt_mit_spesen_vom_selben_absender():
    iban = "DE11200400600000000099"
    def eingang(tag, betrag, text="Gehalt/Rente"):
        return Transaction(tag, D(str(betrag)), "Firma GmbH", "Lohn", iban, buchungstext=text)
    txs = []
    for m, gehalt in zip(range(1, 10), [2333.68, 2115.13, 2501.51, 1980.40, 2250.00, 2009.59, 2420.10, 2176.73, 2301.00]):
        txs.append(eingang(date(2026, m, 26), gehalt))
        txs.append(eingang(date(2026, m, 9), 30 + m * 7, "EURO-Überweisung"))   # Spesen, nicht als Gehalt ausgewiesen
        txs.append(eingang(date(2026, m, 17), 12 + m * 3, "EURO-Überweisung"))
    txs.append(eingang(date(2026, 6, 15), 544.50))            # Sonderzahlung im selben Monat
    [c] = [c for c in detect_contracts(txs, TODAY) if c.typ == "einnahme"]
    assert (c.turnus, c.kategorie, c.status, c.vorkommen) == ("monatlich", "Lohn / Gehalt", "aktiv", 9)
    assert c.erwarteter_betrag == D("2301.00") and c.naechste_faelligkeit == date(2026, 10, 26)
    assert not c.betrag_gestiegen and c.vorheriger_betrag is None


def test_dividende_trotz_verkauf_unter_demselben_namen():
    def eingang(tag, betrag, kategorie):
        return Transaction(tag, D(str(betrag)), "Dow Jones EU", "", kategorie=kategorie)
    txs = [eingang(add_months(date(2025, 3, 15), 3 * i), b, "Dividenden") for i, b in enumerate([1.2, 1.44, 0.9, 1.09, 3.03, 1.3, 1.5])]
    txs.append(eingang(date(2026, 5, 4), 119.46, "Sparen"))  # Verkauf
    [c] = detect_contracts(txs, TODAY)
    assert (c.turnus, c.typ, c.vorkommen, c.erwarteter_betrag) == ("quartalsweise", "einnahme", 7, D("1.37"))  # Mitte der letzten sechs


def _txt(d, amount, name, iban, text):
    return Transaction(d, D(str(amount)), name, "", iban, "", "", buchungstext=text)


def test_quartalsbeitrag_von_hand_ueberwiesen_dann_dauerauftrag():
    """Rundfunkbeitrag: erst eine Nachzahlung, dann zweimal 55,08 – Abstände 74 und 104 Tage."""
    txs = [_txt(date(2026, 2, 13), -91.80, "Rundfunk ARD, ZDF, DRadio", "DE24", "ECHTZEIT EURO-UEBERW."),
           _txt(date(2026, 4, 28), -55.08, "Rundfunk ARD, ZDF, DRadio", "DE24", "EURO-Überweisung"),
           _txt(date(2026, 8, 10), -55.08, "Rundfunk ARD, ZDF, DRadio", "DE24", "Dauerauftrag")]
    [c] = detect_contracts(txs, date(2026, 10, 4))
    assert (c.turnus, c.erwarteter_betrag, c.status, c.kategorie) == ("quartalsweise", D("-55.08"), "aktiv", "Gebühren & Steuern")
    # zwei ähnliche Einkäufe im Abstand von drei Monaten sind dagegen kein Vertrag
    laden = [_txt(date(2026, 4, 28), -18.77, "KONSUM LEIPZIG", "", "Lastschrift"), _txt(date(2026, 8, 1), -18.77, "KONSUM LEIPZIG", "", "Lastschrift")]
    assert detect_contracts(laden, date(2026, 10, 4)) == []


def test_quartalsweise_mit_streuenden_abstaenden():
    tage = [date(2025, 1, 6), date(2025, 4, 2), date(2025, 7, 3), date(2025, 10, 1), date(2026, 1, 12), date(2026, 4, 1), date(2026, 7, 2), date(2026, 10, 1)]
    [c] = detect_contracts([_txt(d, -5, "taz Verlagsgenossenschaft", "DE56", "Lastschrift") for d in tage], date(2026, 10, 4))
    assert (c.turnus, c.vorkommen) == ("quartalsweise", 8)


def test_lastschrift_mit_ausreisser_beim_betrag_ist_ein_vertrag():
    """Festnetz 44,95 – im zweiten Monat einmalig 174,29 (Einrichtung): erwartet wird der übliche Betrag."""
    txs = [_txt(date(2026, 8, 3), -44.95, "Telekom Deutschland GmbH", "DE68", "Lastschrift (Einzugsermächtigung)"),
           _txt(date(2026, 9, 2), -174.29, "Telekom Deutschland GmbH", "DE68", "Lastschrift (Einzugsermächtigung)"),
           _txt(date(2026, 10, 2), -44.95, "Telekom Deutschland GmbH", "DE68", "Lastschrift (Einzugsermächtigung)")]
    [c] = detect_contracts(txs, date(2026, 10, 4))
    assert (c.turnus, c.erwarteter_betrag, c.vorkommen, c.betrag_gestiegen) == ("monatlich", D("-44.95"), 3, False)


def test_zwei_abos_beim_selben_anbieter_bleiben_zwei_vertraege():
    """3 € und 3,50 € im selben Monat über dieselbe IBAN: zwei Mitgliedschaften, nicht eine mit wechselndem Betrag."""
    txs = [_txt(date(2026, m, 8), -3, "Steady Media", "FR76", "Lastschrift") for m in range(3, 10)]
    txs += [_txt(date(2026, m, 10), -6, "Steady Media", "FR76", "Lastschrift") for m in range(3, 10)]
    vertraege = detect_contracts(txs, date(2026, 10, 1))
    assert sorted(c.erwarteter_betrag for c in vertraege) == [D("-6"), D("-3")]
    assert len({c.schluessel for c in vertraege}) == 2


def test_jahresbeitrag_neben_kleinen_nachtraegen():
    txs = [_txt(date(2025, 3, 16), -609.03, "ERGO Versicherung AG", "DE67", "Lastschrift"),
           _txt(date(2026, 3, 16), -543.18, "ERGO Versicherung AG", "DE67", "Lastschrift"),
           _txt(date(2026, 5, 8), -18.67, "ERGO Versicherung AG", "DE67", "Lastschrift"),
           _txt(date(2026, 5, 28), -13.55, "ERGO Versicherung AG", "DE67", "Lastschrift")]
    [c] = detect_contracts(txs, date(2026, 10, 4))
    assert (c.turnus, c.vorkommen, c.kategorie) == ("jaehrlich", 2, "Versicherung")


def test_alle_vier_wochen_mit_ausgefallener_aufladung():
    from datetime import timedelta

    tage = [date(2026, 1, 5)]
    for abstand in (28, 28, 56, 28, 27, 28, 28):  # einmal ausgesetzt
        tage.append(tage[-1] + timedelta(days=abstand))
    [c] = detect_contracts([_txt(d, -15, "Alphacomm Solutions B.V.", "NL82", "Lastschrift") for d in tage], tage[-1])
    assert c.turnus == "vierwoechentlich" and c.monatlich == D("15") * 365 / (12 * 28)
    # ein echter Monatsvertrag am Monatsende (28-Tage-Abstände im Februar) bleibt monatlich
    monat = [_txt(date(2026, m, 28), -9.99, "Musikdienst", "DE99", "Lastschrift") for m in range(1, 8)]
    assert detect_contracts(monat, date(2026, 8, 1))[0].turnus == "monatlich"


def test_bestaetigter_vertrag_bleibt_wenn_die_erkennung_die_gruppe_neu_schneidet():
    """Spende 15 → 20 → 22,50: Früher zwei Vorschläge je Betrag, jetzt ein Vertrag mit wechselndem Betrag.
    Der bestätigte von beiden übernimmt die neue Kennung – er wird nicht inaktiv und kein neuer Vorschlag entsteht."""
    from bankpocket.db import Account, ContractRow, TransactionRow, make_sessionmaker
    from bankpocket.service import contract_status, sync_contracts
    from sqlalchemy import select

    s = make_sessionmaker("sqlite://")()
    acc = Account(name="Giro", quelle="ing", typ="giro", gruppe="Tägliche Konten")
    alt = ContractRow(schluessel="gegenpartei|-|IE30|15", name="Spendenverein", kategorie="Spenden", turnus="monatlich",
                      typ="ausgabe", erwarteter_betrag=-15, naechste_faelligkeit=date(2026, 1, 27))
    neu = ContractRow(schluessel="gegenpartei|-|IE30|21", name="Spendenverein", kategorie="Spenden", turnus="monatlich",
                      typ="ausgabe", erwarteter_betrag=-20, naechste_faelligkeit=date(2026, 10, 27), bestaetigt=True)
    s.add_all([acc, alt, neu])
    s.flush()
    for i, (m, betrag, vertrag) in enumerate([(mo, -15, alt) for mo in range(1, 5)] + [(mo, -20, neu) for mo in range(5, 9)]
                                              + [(9, -22.5, None)]):
        s.add(TransactionRow(account_id=acc.id, buchungsdatum=date(2026, m, 27), betrag=betrag, gegenpartei="Spendenverein",
                             iban_gegenpartei="IE30", buchungstext="Lastschrift", contract_id=vertrag and vertrag.id, hash=f"s{i}"))
    s.flush()
    erg = sync_contracts(s, date(2026, 10, 4))
    assert erg.neu == []
    assert (neu.schluessel, neu.vorkommen, neu.erwarteter_betrag, contract_status(neu, date(2026, 10, 4))[0]) == (
        "gegenpartei|-|IE30", 9, D("-20.00"), "aktiv")
    assert alt.nicht_mehr_erkannt and len(list(s.scalars(select(ContractRow)))) == 2
