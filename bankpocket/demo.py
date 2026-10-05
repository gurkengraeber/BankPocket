"""Demo-Datenbank mit synthetischen Daten – zum Ausprobieren der Oberfläche ohne Bankzugang.

    BANKPOCKET_DATA_DIR=demo-daten python -m bankpocket.demo
    BANKPOCKET_DATA_DIR=demo-daten BANKPOCKET_AUTH=aus BANKPOCKET_SCHEDULER=aus uvicorn bankpocket.main:app

Alle Namen, IBANs und Beträge sind erfunden.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from .config import Settings
from .contracts import add_months
from .db import Account, Budget, Connection, Notice, make_sessionmaker
from .fetchers.base import FetchedHolding
from .fetchers.splitwise import SplitwiseSource
from .fetchers.trade_republic import tr_umsatz
from .models import Transaction
from .service import (holdings_setzen, markiere_interne_umbuchungen, saldo_setzen, speichere_transaktionen,
                      sync_contracts)
from .vault import Vault

GIRO, EXTRA, CONS_GIRO, TAGESGELD = ("DE02500105170000000001", "DE02500105170000000002",
                                     "DE50760300800000000003", "DE50760300800000000004")
TR_IBAN = "DE99100123450000000006"


def d(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


def _buchungen(heute: date, rnd: random.Random) -> dict[str, list[Transaction]]:
    start = add_months(heute.replace(day=1), -14)
    giro, extra, cons, tg, paypal = [], [], [], [], []

    def monatlich(liste, tag, betrag, name, zweck="", iban="", cid="", mref="", ab=start, bis=heute, text=""):
        m = ab
        while m <= bis:
            datum = m.replace(day=min(tag, 28))
            if start <= datum <= heute and datum <= bis:
                wert = betrag(datum) if callable(betrag) else betrag
                liste.append(Transaction(datum, d(wert), name, zweck, iban, cid, mref, buchungstext=text))
            m = add_months(m, 1)

    monatlich(giro, 27, 2850, "Musterwerk GmbH", "Gehalt", "DE11200400600000000099", text="Gehalt/Rente")
    monatlich(giro, 1, -890, "Hausverwaltung Lindenhof", "Miete Wohnung 3.OG", "DE88100700000000000001", text="Dauerauftrag")
    monatlich(giro, 15, lambda t: -58 if t < add_months(heute, -3) else -62, "immergrün! (365 AG)", "Abschlag Strom",
              "DE44300500000000000002", "DE12ZZZ00000123456", "IMG-77812", text="Lastschrift")
    monatlich(giro, 5, lambda t: -17 if t < add_months(heute, -1) else -20, "Congstar", "Mobilfunk",
              "DE55200400000000000003", "DE33ZZZ00000234567", "CS-1029", text="Lastschrift")
    monatlich(giro, 3, -28.50, "ver.di", "Mitgliedsbeitrag", "DE66500500000000000004", "DE21ZZZ00000345678",
              "VD-55", text="Lastschrift")
    monatlich(giro, 9, -21.42, "ANTHROPIC", "Claude Pro", text="Kartenzahlung")
    monatlich(giro, 2, -150, "Paula Beispiel", "Coworking-Platz", "DE77700500000000000005", text="Dauerauftrag")
    monatlich(giro, 12, -13.99, "PayPal Europe S.a.r.l. et Cie S.C.A", "PP.7712.PP . Netflix, Ihr Einkauf bei Netflix",
              "LU89751000135104200E", "LU96ZZZ0000000000000000058", "4XAJ2", text="Lastschrift")
    monatlich(giro, 20, -10.99, "PayPal Europe S.a.r.l. et Cie S.C.A", "PP.7712.PP . Spotify, Ihr Einkauf bei Spotify",
              "LU89751000135104200E", "LU96ZZZ0000000000000000058", "4XAJ3", text="Lastschrift")
    monatlich(giro, 4, -200, "Trade Republic Bank GmbH", "Sparplan Dow Jones ETF", "DE99100123450000000006",
              text="Überweisung")
    monatlich(giro, 6, -300, "Max Mustermann", "Sparen", EXTRA, text="Dauerauftrag")
    monatlich(extra, 6, 300, "Max Mustermann", "Sparen", GIRO, text="Gutschrift")
    monatlich(giro, 18, 120, "Jonas Beispiel", "Untermiete Abstellraum", "DE12700100800000000007",
              bis=add_months(heute, -2), text="Gutschrift")
    # Haftpflicht vierteljährlich
    q = start
    while q <= heute:
        giro.append(Transaction(q.replace(day=10), d(-23.10), "HUK-Coburg", "Haftpflichtversicherung",
                                "DE33700500000000000008", "DE09ZZZ00000456789", "HUK-3381", buchungstext="Lastschrift"))
        q = add_months(q, 3)
    # Alltag
    laeden = [("REWE Markt GmbH", 9, 78), ("EDEKA", 6, 55), ("ALDI SUED", 5, 42), ("dm-drogerie markt", 4, 31),
              ("Lieferando", 14, 38), ("Cafe Kranich", 4, 16), ("AMAZON EU S.A R.L.", 9, 89), ("DB Vertrieb GmbH", 19, 69)]
    tag = start
    while tag <= heute:
        for name, lo, hi in laeden:
            chance = 0.33 if name in ("REWE Markt GmbH", "EDEKA", "ALDI SUED") else 0.07
            if rnd.random() < chance:
                giro.append(Transaction(tag, d(-rnd.uniform(lo, hi)), name, f"Kartenzahlung {tag:%d.%m.}",
                                        buchungstext="Kartenzahlung"))
        if rnd.random() < 0.04:
            giro.append(Transaction(tag, d(-rnd.choice([50, 100])), "Geldautomat", "Bargeldauszahlung",
                                    buchungstext="Auszahlung"))
        tag += timedelta(days=1)
    # Consorsbank: Tagesgeld-Zinsen, ein paar Umbuchungen
    monatlich(tg, 28, lambda t: 12 + (t.month % 3), "Consorsbank", "Zinsgutschrift", text="Zinsen")
    monatlich(cons, 14, -45, "Stadtbibliothek", "Jahresgebühr", ab=add_months(start, 2), bis=add_months(start, 2))
    paypal += [Transaction(heute - timedelta(days=n), d(-v), name, "PayPal-Zahlung")
               for n, v, name in [(3, 24.90, "Vinted"), (11, 12.50, "Kleinanzeigen"), (40, 59.0, "Steam")]]

    # Trade Republic: Einzahlung vom Girokonto, Sparplan, ab und zu Kartenzahlungen – über den echten Übersetzer
    ereignisse, m = [], start
    while m <= heute:
        for tag, wert, titel, typ in ((4, 200, "Max Mustermann", "INCOMING_TRANSFER"),
                                      (5, -200, "Core MSCI World USD (Acc)", "SAVINGS_PLAN_EXECUTED"),
                                      (28, round(rnd.uniform(1.5, 3.5), 2), "Zinsen", "INTEREST_PAYOUT")):
            datum = m.replace(day=tag)
            if datum <= heute:
                ereignisse.append({"id": f"demo-{datum}-{typ}", "timestamp": f"{datum}T08:00:00.000+0000",
                                   "title": titel, "subtitle": "", "amount": {"currency": "EUR", "value": wert},
                                   "eventType": typ, "status": "EXECUTED"})
        m = add_months(m, 1)
    for n, wert, titel in ((2, -18.40, "Edeka"), (6, -42.00, "Decathlon"), (17, -9.80, "Cafe Kranich")):
        datum = heute - timedelta(days=n)
        ereignisse.append({"id": f"demo-karte-{n}", "timestamp": f"{datum}T12:00:00.000+0000", "title": titel,
                           "subtitle": "Kartenzahlung", "amount": {"currency": "EUR", "value": wert},
                           "eventType": "card_successful_transaction", "status": "EXECUTED"})
    tr = [t for t in map(tr_umsatz, ereignisse) if t]

    # Splitwise über den echten Übersetzer
    def sw(id_, tage, text, ich, andere, kategorie, zahlung=False):
        users = [{"user": {"id": 1, "first_name": "Ich"}, "net_balance": ich}]
        users += [{"user": {"id": 10 + i, "first_name": n}, "net_balance": b} for i, (n, b) in enumerate(andere)]
        return {"id": id_, "date": f"{heute - timedelta(days=tage)}T19:00:00Z", "description": text,
                "currency_code": "EUR", "payment": zahlung, "category": {"name": kategorie}, "users": users}
    splitwise = [t for t in (SplitwiseSource._buchung(e, 1) for e in [
        sw(1, 3, "Pizza-Abend", "40.00", [("Anna", "-20"), ("Ben", "-20")], "Dining out"),
        sw(2, 8, "Einkauf WG", "-12.50", [("Ben", "12.50")], "Groceries"),
        sw(3, 20, "Konzerttickets", "35.00", [("Anna", "-35")], "Entertainment"),
        sw(4, 15, "Ausgleich", "-35.00", [("Anna", "35")], "General", zahlung=True),
    ]) if t]
    return {"giro": giro, "extra": extra, "cons": cons, "tg": tg, "paypal": paypal, "tr": tr, "splitwise": splitwise}


def erzeugen(settings: Settings, heute: date | None = None) -> None:
    heute = heute or date.today()
    rnd = random.Random(42)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    S = make_sessionmaker(settings.db_url)
    vault = Vault.from_file(settings.key_file)
    jetzt = datetime.now()
    with S() as s:
        if s.scalar(select(Account).limit(1)):
            raise SystemExit("Die Datenbank enthält schon Daten – bitte ein leeres Verzeichnis verwenden.")
        dummy = vault.encrypt("demo")
        ing = Connection(bank="ing", name="ING", blz="50010517", server_url="https://fints.ing.de/fints/",
                         login_enc=dummy, pin_enc=dummy, status="ok", tan_verfahren_name="App-Freigabe",
                         letzter_erfolg=jetzt - timedelta(minutes=37), letzte_freigabe=jetzt - timedelta(days=24))
        cons = Connection(bank="consorsbank", name="Consorsbank", blz="76030080",
                          server_url="https://brokerage-hbci.consorsbank.de/hbci", login_enc=dummy, pin_enc=dummy,
                          status="freigabe_noetig", tan_verfahren_name="SecurePlus App",
                          meldung="Die Freigabe ist nicht rechtzeitig erfolgt.",
                          letzter_erfolg=jetzt - timedelta(days=2, hours=3), letzte_freigabe=jetzt - timedelta(days=91))
        tr_conn = Connection(art="trade_republic", bank="trade_republic", name="Trade Republic", blz="", server_url="",
                             login_enc=dummy, pin_enc=dummy, status="ok", letzter_erfolg=jetzt - timedelta(minutes=37))
        binance = Connection(art="binance", bank="binance", name="Binance", blz="", server_url="", login_enc=dummy,
                             pin_enc=dummy, status="ok", letzter_erfolg=jetzt - timedelta(minutes=36))
        sw_conn = Connection(art="splitwise", bank="splitwise", name="Splitwise", blz="", server_url="",
                             login_enc=dummy, pin_enc=dummy, status="ok", letzter_erfolg=jetzt - timedelta(minutes=36))
        s.add_all([ing, cons, tr_conn, binance, sw_conn])
        s.flush()

        def konto(name, quelle, typ, gruppe, iban=None, conn=None, stand=None):
            a = Account(name=name, quelle=quelle, typ=typ, gruppe=gruppe, iban=iban,
                        connection_id=conn.id if conn else None, zuletzt_aktualisiert=stand)
            s.add(a)
            s.flush()
            return a

        giro = konto("Girokonto", "ing", "giro", "Tägliche Konten", GIRO, ing, ing.letzter_erfolg)
        cgiro = konto("Girokonto", "consorsbank", "giro", "Tägliche Konten", CONS_GIRO, cons, cons.letzter_erfolg)
        konto("Norwegian Kreditkarte", "norwegian", "kreditkarte", "Tägliche Konten")
        paypal = konto("PayPal", "paypal", "giro", "Tägliche Konten", stand=jetzt - timedelta(days=6))
        bargeld = konto("Bargeld", "manuell", "giro", "Tägliche Konten")
        verrechnung = konto("Verrechnungskonto", "trade_republic", "giro", "Tägliche Konten", TR_IBAN, tr_conn,
                            tr_conn.letzter_erfolg)
        barclays = konto("Barclays Visa", "csv", "kreditkarte", "Tägliche Konten")
        barclays.aktiv = False
        extra = konto("Extra-Konto", "ing", "spar", "Sparkonten", EXTRA, ing, ing.letzter_erfolg)
        depot = konto("Direkt-Depot", "ing", "depot", "Sparkonten", None, ing, ing.letzter_erfolg)
        tg = konto("Tagesgeldkonto", "consorsbank", "spar", "Sparkonten", TAGESGELD, cons, cons.letzter_erfolg)
        tr_depot = konto("Depot", "trade_republic", "depot", "Sparkonten", None, tr_conn, tr_conn.letzter_erfolg)
        bn = konto("Binance", "binance", "krypto", "Crypto", None, binance, binance.letzter_erfolg)
        krypto = konto("Exodus + Monero", "manuell", "krypto", "Crypto")
        splitwise = konto("Splitwise", "splitwise", "virtuell", "Virtuell", None, sw_conn, sw_conn.letzter_erfolg)
        kaution = konto("Kautionen & Schulden", "manuell", "virtuell", "Virtuell")

        b = _buchungen(heute, rnd)
        for acc, liste in ((giro, b["giro"]), (extra, b["extra"]), (cgiro, b["cons"]), (tg, b["tg"]),
                           (paypal, b["paypal"]), (verrechnung, b["tr"]), (splitwise, b["splitwise"])):
            speichere_transaktionen(s, acc, liste)
        speichere_transaktionen(s, bargeld, [Transaction(heute - timedelta(days=9), d(150), "Geldautomat", ""),
                                             Transaction(heute - timedelta(days=4), d(-23.40), "Wochenmarkt", ""),
                                             Transaction(heute - timedelta(days=1), d(-8.90), "Bäckerei", "")], True)
        speichere_transaktionen(s, krypto, [Transaction(heute - timedelta(days=300), d(3180), "Bestand BTC/XMR", "")], True)
        speichere_transaktionen(s, kaution, [Transaction(heute - timedelta(days=400), d(1800), "Mietkaution", "")], True)

        saldo_setzen(s, giro, heute, d(2431.77))
        saldo_setzen(s, extra, heute, d(12400))
        saldo_setzen(s, cgiro, heute - timedelta(days=2), d(640.15))
        saldo_setzen(s, tg, heute - timedelta(days=2), d(5212.40))
        saldo_setzen(s, paypal, heute, d(18.42))
        # Depot: monatliche Snapshots mit Wertentwicklung
        for i in range(14, -1, -1):
            tag = add_months(heute, -i)
            saldo_setzen(s, depot, tag, d(18000 * (1 + 0.012 * (14 - i)) + rnd.uniform(-450, 450)))
        holdings_setzen(s, depot, heute, [
            FetchedHolding("IE00B4L5Y983", "iShares Core MSCI World", Decimal("181.4"), Decimal("98.20"), d(17813.48), heute),
            FetchedHolding("IE00BKM4GZ66", "iShares Core MSCI EM IMI", Decimal("140"), Decimal("34.10"), d(4774.0), heute),
        ])
        saldo_setzen(s, verrechnung, heute, d(312.40))
        saldo_setzen(s, splitwise, heute, d(27.50))
        for i in range(14, -1, -1):
            tag = add_months(heute, -i)
            saldo_setzen(s, tr_depot, tag, d(2400 + 210 * (14 - i) + rnd.uniform(-120, 120)))
            saldo_setzen(s, bn, tag, d(2200 + 70 * (14 - i) + rnd.uniform(-400, 400)))
        holdings_setzen(s, tr_depot, heute, [
            FetchedHolding("IE00B4L5Y983", "Core MSCI World USD (Acc)", Decimal("52.31"), Decimal("98.20"), d(5136.84), heute)])
        holdings_setzen(s, bn, heute, [
            FetchedHolding("BTC", "Bitcoin", Decimal("0.031"), Decimal("58400"), d(1810.40), heute),
            FetchedHolding("ETH", "Ethereum", Decimal("0.42"), Decimal("2380"), d(999.60), heute),
            FetchedHolding("SOL", "Solana", Decimal("2.1"), Decimal("131.50"), d(276.15), heute)])
        s.add_all([Budget(kategorie="Lebensmittel", limit=d(400)), Budget(kategorie="Restaurants", limit=d(120)),
                   Budget(kategorie="Shopping", limit=d(150))])
        markiere_interne_umbuchungen(s)
        s.flush()
        for c in sync_contracts(s, heute).neu:
            c.bestaetigt = c.name not in ("Netflix", "HUK-Coburg")  # zwei Vorschläge bleiben zum Ausprobieren offen
        s.add_all([
            Notice(art="neuer_vertrag", titel="Neuer Vertrag erkannt: ANTHROPIC", text="21,42 € monatlich",
                   erstellt_am=jetzt - timedelta(days=5)),
            Notice(art="betrag_gestiegen", titel="Congstar ist teurer geworden", text="17,00 € → 20,00 €",
                   erstellt_am=jetzt - timedelta(days=2)),
            Notice(art="freigabe_noetig", titel="Consorsbank: Abruf pausiert",
                   text="Die Bank verlangt eine Freigabe. Tippe hier und starte den Abruf, wenn du deine Banking-App zur Hand hast.",
                   link=f"#/verbindung/{cons.id}", erstellt_am=jetzt - timedelta(hours=20)),
        ])
        s.commit()
    print(f"Demo-Daten angelegt in {settings.data_dir}")


if __name__ == "__main__":
    erzeugen(Settings.from_env())
