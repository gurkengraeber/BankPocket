import functools
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest
from fints.utils import mt940_to_array
from sqlalchemy import func, select

from bankpocket.config import Settings
from bankpocket.context import AppContext
from bankpocket.db import (Account, Balance, Connection, ContractRow, Holding, Notice, PushSubscription,
                           TransactionRow, make_sessionmaker)
from bankpocket.fetchers.fints_source import FinTSSource, kontoart, mt940_zu_transaktion, waehle_tan_verfahren
from bankpocket.notify import Notifier
from bankpocket.service import GRUPPE_FUER_TYP
from bankpocket.sync import SyncManager
from bankpocket.vault import Vault
from fints_fake import APP, DEPOT_IBAN, PHOTO, FakeBank

HEUTE = date(2026, 9, 30)


@pytest.fixture
def umgebung(tmp_path):
    def bauen(bank, product_id="TESTPRODUKT", schlafen=lambda s: None):
        settings = Settings(data_dir=tmp_path, fints_product_id=product_id, auth=False, scheduler=False)
        S = make_sessionmaker(settings.db_url)
        gesendet = []
        notifier = Notifier(S, tmp_path, "mailto:t@example.org", sender=lambda abo, p: gesendet.append(p),
                            asynchron=False)
        extra = {"schlafen": schlafen} if schlafen else {}
        ctx = AppContext(settings=settings, session_factory=S, vault=Vault.from_file(settings.key_file),
                         notifier=notifier, today=lambda: HEUTE, now=lambda: datetime(2026, 9, 30, 12, 0),
                         source_factory=functools.partial(FinTSSource, client_factory=bank.factory, **extra))
        ctx.manager = SyncManager(ctx)
        with S() as s:
            s.add(PushSubscription(endpoint="https://push.example/1", p256dh="x", auth="y"))
            s.commit()
        return ctx, gesendet
    return bauen


def verbindung(ctx, pin="1234") -> int:
    with ctx.session_factory() as s:
        c = Connection(bank="ing", name="ING", blz="50010517", server_url="https://fints.ing.de/fints/",
                       login_enc=ctx.vault.encrypt("kunde1"), pin_enc=ctx.vault.encrypt(pin))
        s.add(c)
        s.commit()
        return c.id


def warte_auf(bedingung, sekunden=5.0):
    ende = time.time() + sekunden
    while time.time() < ende:
        if bedingung():
            return
        time.sleep(0.01)
    raise AssertionError("Bedingung nicht erfüllt")


def test_erstverbindung_mit_app_freigabe(umgebung, tmp_path):
    bank = FakeBank(HEUTE)
    ctx, push = umgebung(bank)
    cid = verbindung(ctx)
    assert ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True) == "ok"
    assert bank.polls == 2  # Freigabe kam beim zweiten Nachfragen
    assert bank.zeitraeume[0][1] == HEUTE - timedelta(days=730)  # erste Abfrage holt die Historie

    with ctx.session_factory() as s:
        conn = s.get(Connection, cid)
        assert (conn.status, conn.tan_verfahren, conn.tan_verfahren_name) == ("ok", "902", "App-Freigabe")
        assert conn.letzte_freigabe is not None
        assert ctx.vault.decrypt(conn.client_data_enc) == b"fake-sitzungsdaten-mit-system-id"
        konten = {a.name: a for a in s.scalars(select(Account))}
        assert konten["Girokonto"].gruppe == "Tägliche Konten"
        assert konten["Extra-Konto"].gruppe == "Sparkonten"
        assert konten["Direkt-Depot"].typ == "depot"
        assert s.scalar(select(Balance.saldo).where(Balance.account_id == konten["Direkt-Depot"].id)) == 955
        assert s.scalar(select(func.count()).select_from(Holding)) == 1
        assert s.scalar(select(Balance.saldo).where(Balance.account_id == konten["Girokonto"].id)) == 1500
        giro = list(s.scalars(select(TransactionRow).where(TransactionRow.account_id == konten["Girokonto"].id)))
        assert len(giro) == 12
        assert sum(t.intern for t in giro) == 4  # Daueraufträge aufs eigene Extra-Konto
        assert {t.buchungstext for t in giro} >= {"Lastschrift", "Gehalt/Rente"}
        vertraege = {c.name for c in s.scalars(select(ContractRow))}
        assert vertraege == {"Streamflix GmbH", "Musterfirma AG"}  # Umbuchung ist kein Vertrag
        # Beim ersten Import der Historie keine Flut an „Neuer Vertrag“-Hinweisen
        assert s.scalar(select(func.count()).select_from(Notice)) == 0
    assert push == []


def test_pin_niemals_im_klartext(umgebung, tmp_path):
    ctx, _ = umgebung(FakeBank(HEUTE))
    verbindung(ctx, pin="geheim-4711")
    assert b"geheim-4711" not in (tmp_path / "bankpocket.db").read_bytes()


def test_folgeabruf_ohne_neue_freigabe_und_ohne_duplikate(umgebung):
    bank = FakeBank(HEUTE)
    ctx, _ = umgebung(bank)
    cid = verbindung(ctx)
    ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True)
    bank.zeitraeume.clear()
    polls = bank.polls

    assert ctx.manager.ausfuehren(cid, interaktiv=False) == "ok"
    assert bank.polls == polls  # keine neue Freigabe nötig
    assert bank.clients[-1].from_data == b"fake-sitzungsdaten-mit-system-id"  # gleiche System-ID
    giro_start = next(start for nr, start, _ in bank.zeitraeume if nr == "0000000001")
    assert giro_start == date(2026, 9, 28) - timedelta(days=14)  # inkrementell mit Puffer
    with ctx.session_factory() as s:
        assert s.scalar(select(func.count()).select_from(TransactionRow)) == 12


def test_falsche_pin_stoppt_automatische_abrufe(umgebung):
    bank = FakeBank(HEUTE, pin="1234")
    ctx, push = umgebung(bank)
    cid = verbindung(ctx, pin="9999")
    assert ctx.manager.ausfuehren(cid, interaktiv=False) == "pin_falsch"
    assert push[0]["titel"] == "ING: Anmeldung fehlgeschlagen"

    versuche = len(bank.clients)
    ctx.manager.automatisch_abrufen()
    ctx.manager.alle_starten()  # auch der Aktualisieren-Knopf versucht es nicht mit derselben PIN
    assert len(bank.clients) == versuche


def test_hintergrund_abruf_pausiert_ohne_freigabe(umgebung):
    bank = FakeBank(HEUTE, freigabe_kommt=False)
    ctx, push = umgebung(bank)
    cid = verbindung(ctx)
    assert ctx.manager.ausfuehren(cid, interaktiv=False) == "freigabe_noetig"
    titel = [p["titel"] for p in push]
    assert titel == ["ING: Freigabe angefragt", "ING: Abruf pausiert"]

    versuche = len(bank.clients)
    ctx.manager.automatisch_abrufen()  # kein erneutes Anfragen in der Banking-App
    assert len(bank.clients) == versuche

    bank.freigabe_kommt, bank.polls = True, 0
    assert ctx.manager.ausfuehren(cid, interaktiv=True) == "ok"  # „Jetzt freigeben“ in der App


def test_tan_verfahren_auswahl_in_der_app(umgebung):
    verfahren = {"910": NS(name="chipTAN manuell"), "920": NS(name="smsTAN")}
    bank = FakeBank(HEUTE, sca_bei_init=False, verfahren=verfahren)
    ctx, _ = umgebung(bank)
    cid = verbindung(ctx)
    assert ctx.manager.starten(cid, interaktiv=True, erstverbindung=True)
    warte_auf(lambda: (ctx.manager.live(cid) or {}).get("phase") == "auswahl")
    assert {o["id"] for o in ctx.manager.live(cid)["optionen"]} == {"910", "920"}
    ctx.manager.eingabe(cid, {"tan_verfahren": "920"})
    warte_auf(lambda: not ctx.manager.live(cid)["laeuft"])
    with ctx.session_factory() as s:
        conn = s.get(Connection, cid)
        assert (conn.status, conn.tan_verfahren) == ("ok", "920")


def test_tan_eingabe_fuer_nicht_app_verfahren(umgebung):
    bank = FakeBank(HEUTE, verfahren={"910": NS(name="chipTAN manuell")})
    ctx, _ = umgebung(bank)
    cid = verbindung(ctx)
    ctx.manager.starten(cid, interaktiv=True, erstverbindung=True)
    warte_auf(lambda: (ctx.manager.live(cid) or {}).get("phase") == "tan")
    ctx.manager.eingabe(cid, {"tan": "123456"})
    warte_auf(lambda: not ctx.manager.live(cid)["laeuft"])
    assert ctx.manager.live(cid)["phase"] == "fertig"


def test_auswahl_im_hintergrund_nicht_moeglich(umgebung):
    bank = FakeBank(HEUTE, verfahren={"910": NS(name="chipTAN manuell"), "920": NS(name="smsTAN")})
    ctx, _ = umgebung(bank)
    assert ctx.manager.ausfuehren(verbindung(ctx), interaktiv=False) == "auswahl_noetig"


def test_abbrechen_waehrend_freigabe(umgebung):
    bank = FakeBank(HEUTE, freigabe_kommt=False)
    ctx, _ = umgebung(bank, schlafen=None)  # echtes, unterbrechbares Warten
    cid = verbindung(ctx)
    ctx.manager.starten(cid, interaktiv=True, erstverbindung=True)
    warte_auf(lambda: (ctx.manager.live(cid) or {}).get("phase") == "freigabe")
    assert ctx.manager.abbrechen(cid)
    warte_auf(lambda: not ctx.manager.live(cid)["laeuft"], sekunden=3)
    with ctx.session_factory() as s:
        assert s.get(Connection, cid).status == "neu"


def test_ohne_produkt_id_klare_meldung(umgebung):
    ctx, _ = umgebung(FakeBank(HEUTE), product_id="")
    cid = verbindung(ctx)
    assert ctx.manager.ausfuehren(cid, interaktiv=True) == "fehler"
    with ctx.session_factory() as s:
        assert "Produkt-ID" in s.get(Connection, cid).meldung


def test_neuer_vertrag_und_preiserhoehung_werden_gemeldet(umgebung):
    from fints_fake import umsatz
    bank = FakeBank(HEUTE)
    giro = bank.umsaetze["0000000001"]
    for m in (8, 9):  # zwei Zahlungen reichen noch nicht für einen monatlichen Vertrag
        giro.append(umsatz(date(2026, m, 5), "-29.90", "FitBox Studio", "Mitgliedschaft", "DE44"))
    ctx, push = umgebung(bank)
    cid = verbindung(ctx)
    ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True)
    giro.append(umsatz(date(2026, 10, 15), "-15.99", "Streamflix GmbH", "Abo", "DE02100100100006820101",
                       "DE98ZZZ09999999999", "MR-100", "Lastschrift"))
    giro.append(umsatz(date(2026, 10, 5), "-29.90", "FitBox Studio", "Mitgliedschaft", "DE44"))
    bank.heute = date(2026, 10, 20)
    ctx.today = lambda: date(2026, 10, 20)
    assert ctx.manager.ausfuehren(cid, interaktiv=False) == "ok"
    titel = {p["titel"] for p in push}
    assert "Ist FitBox Studio ein Vertrag?" in titel
    assert "Streamflix GmbH ist teurer geworden" in titel


def test_mt940_von_der_bank_wird_korrekt_uebersetzt():
    mt940 = (":20:STARTUMSE\r\n:25:50010517/0123456789\r\n:28C:00000/001\r\n:60F:C260901EUR1000,00\r\n"
             ":61:2609150915D12,99N005NONREF\r\n"
             ":86:105?00FOLGELASTSCHRIFT?109310?20EREF+123456?21MREF+MR-100?22CRED+DE98ZZZ09999999999"
             "?23SVWZ+Abo September?30INGDDEFFXXX?31DE02100100100006820101?32Streamflix GmbH?34992\r\n"
             ":62F:C260915EUR987,01\r\n-")
    [roh] = mt940_to_array(mt940)
    t = mt940_zu_transaktion(roh.data)
    assert (t.buchungsdatum, t.betrag) == (date(2026, 9, 15), Decimal("-12.99"))
    assert (t.gegenpartei, t.iban_gegenpartei) == ("Streamflix GmbH", "DE02100100100006820101")
    assert (t.glaeubiger_id, t.mandatsreferenz) == ("DE98ZZZ09999999999", "MR-100")
    assert (t.verwendungszweck, t.buchungstext) == ("Abo September", "FOLGELASTSCHRIFT")


def test_tan_verfahren_heuristik():
    assert waehle_tan_verfahren({"900": PHOTO, "902": APP}) == "902"
    assert waehle_tan_verfahren({"930": NS(name="SecurePlus App"), "931": NS(name="SecurePlus Generator")}) == "930"
    assert waehle_tan_verfahren({"910": NS(name="chipTAN"), "920": NS(name="smsTAN")}) is None
    assert waehle_tan_verfahren({"999": NS(name="irgendwas")}) == "999"


def test_kontoarten():
    assert [kontoart(x) for x in (1, 10, 20, 30, 50, None)] == ["giro", "spar", "spar", "depot", "kreditkarte", "giro"]


def test_depot_ohne_kontoart_wird_erkannt(umgebung):
    """Die ING nennt keine Kontoart und führt das Depot mit IBAN: Es zählt trotzdem als Depot – auch nachträglich."""
    bank = FakeBank(HEUTE, ohne_kontoart=True)
    ctx, _ = umgebung(bank)
    cid = verbindung(ctx)
    with ctx.session_factory() as s:  # aus einem früheren Abruf fälschlich als Girokonto angelegt
        s.add(Account(quelle="ing", name="ING Direkt-Depot", typ="giro", gruppe="Sparkonten", iban=DEPOT_IBAN,
                      kontonummer="5550001", connection_id=cid))
        s.commit()
    assert ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True) == "ok"
    with ctx.session_factory() as s:
        depot = s.scalar(select(Account).where(Account.iban == DEPOT_IBAN))
        assert (depot.name, depot.typ, depot.gruppe) == ("ING Direkt-Depot", "depot", GRUPPE_FUER_TYP["depot"])
        assert s.scalar(select(Balance.saldo).where(Balance.account_id == depot.id)) == 955
        assert s.scalar(select(func.count()).select_from(Holding)) == 1
        assert s.scalar(select(func.count()).select_from(Account)) == 3


def test_signaturprofil_im_zwei_schritt_verfahren():
    """Signaturkopf und Verschlüsselungskopf nennen dieselbe Profilversion: 1 im Ein-Schritt-, 2 im Zwei-Schritt-Verfahren."""
    from fints.client import FinTS3PinTanClient

    from bankpocket.fetchers.fints_source import signaturprofil_korrigieren

    def version(verfahren: str) -> tuple[int, int]:
        client = FinTS3PinTanClient("76030080", "kunde001", "12345", "https://bank.invalid/hbci", product_id="TEST")
        signaturprofil_korrigieren(client)
        client.selected_security_function = verfahren
        dialog = client._new_dialog(lazy_init=True)
        segmente = []

        class Nachricht:
            def __iadd__(self, segment):
                segmente.append(segment)
                return self
        nachricht = Nachricht()
        nachricht.dialog = dialog
        dialog.auth_mechanisms[0].sign_prepare(nachricht)
        return (int(segmente[0].security_profile.security_method_version),
                int(dialog.enc_mechanism.security_method_version))

    assert version("999") == (1, 1)
    assert version("900") == (2, 2)


def test_unangekuendigte_starke_authentifizierung_fuehrt_zum_zweiten_versuch():
    """Consorsbank: Die Bank bricht den Kontoabruf mit 9075 ab – der zweite Versuch schickt das TAN-Segment mit."""
    from fints.client import FinTS3PinTanClient
    from fints.segments.saldo import HKSAL6

    from bankpocket.fetchers.base import FetchResult

    q = FinTSSource.__new__(FinTSSource)
    q.tan_erzwingen, q.client_data, versuche = False, None, []

    def _abrufen():
        versuche.append(q.tan_erzwingen)
        q.bank_meldungen = [] if q.tan_erzwingen else [("9050", "Nachricht teilweise fehlerhaft."),
                                                       ("9075", "Starke Authentifizierung erforderlich.")]
        return FetchResult(konten=[], client_data=b"sitzung-%d" % len(versuche))

    q._abrufen = _abrufen
    assert q.abrufen().client_data == b"sitzung-2" and versuche == [False, True]

    client = FinTS3PinTanClient("76030080", "kunde001", "12345", "https://bank.invalid/hbci", product_id="TEST")
    q._tan_segment_erzwingen(client)
    client.selected_security_function = "901"
    assert client._need_twostep_tan_for_segment(HKSAL6()) is True
    client.selected_security_function = "999"
    assert client._need_twostep_tan_for_segment(HKSAL6()) is False


def test_speicherzeitraum_auch_aus_unzerlegtem_segment():
    """Consorsbank: python-fints zerlegt HIKAZS nicht – die 90 Tage stehen trotzdem drin."""
    roh = NS(_additional_data=["1", "1", "0", ["90", "J", "N"]])
    zerlegt = NS(parameter=NS(storage_duration=360))
    q = FinTSSource.__new__(FinTSSource)
    for seg, tage in ((roh, 90), (zerlegt, 360), (None, None)):
        assert q._speicherzeitraum(NS(bpd=NS(find_segment_first=lambda _typ, seg=seg: seg))) == tage


def test_consorsbank_fragt_umsaetze_nicht_in_version_7_ab():
    from fints.segments.saldo import HKSAL5, HKSAL6
    from fints.segments.statement import HKKAZ5, HKKAZ6, HKKAZ7

    from bankpocket.fetchers.fints_source import umsatzabfrage_ohne_version_7

    client = NS(_find_highest_supported_command=lambda *kommandos, **kw: kommandos[-1])
    umsatzabfrage_ohne_version_7(client)
    assert client._find_highest_supported_command(HKKAZ5, HKKAZ6, HKKAZ7) is HKKAZ6
    assert client._find_highest_supported_command(HKSAL5, HKSAL6) is HKSAL6


def test_kaufkurs_kontoart_und_rueckfall_der_umsatzabfrage(umgebung):
    """Depot mit Kaufkurs; „Extra-Konto“ ohne Kontoart ist ein Sparkonto; eine Bank, die die neueste Fassung der
    Umsatzabfrage mit 9010 ablehnt, bekommt die ältere – ohne dass die Bank dafür bekannt sein muss."""
    from fints.exceptions import FinTSClientError

    from fints_fake import FakeClient

    abgelehnt, zustand = [], {"aeltere_fassung": False}

    class Zickig(FakeClient):
        def _process_response(self, dialog, segment, response):
            pass

        def _find_highest_supported_command(self, *kommandos, **kw):
            zustand["aeltere_fassung"] = True
            return kommandos[-1]

        def get_transactions(self, acc, start, end):
            if not zustand["aeltere_fassung"] and not abgelehnt:
                abgelehnt.append(acc.accountnumber)
                self._process_response(None, None, NS(code="9010", text="Verarbeitung nicht möglich."))
                raise FinTSClientError("abgelehnt")
            return super().get_transactions(acc, start, end)

    class ZickigeBank(FakeBank):
        def factory(self, blz, login, pin, url, product_id=None, from_data=None, tan_medium=None):
            c = Zickig(self, login, pin, from_data, tan_medium)
            self.clients.append(c)
            return c

    bank = ZickigeBank(HEUTE, ohne_kontoart=True)
    ctx, _ = umgebung(bank)
    cid = verbindung(ctx)
    assert ctx.manager.ausfuehren(cid, interaktiv=True, erstverbindung=True) == "ok"
    assert abgelehnt == ["0000000001"]
    with ctx.session_factory() as s:
        konten = {a.name: a for a in s.scalars(select(Account))}
        assert (konten["Girokonto"].typ, konten["Extra-Konto"].typ, konten["Direkt-Depot"].typ) == ("giro", "spar", "depot")
        assert s.scalar(select(func.count()).select_from(TransactionRow).where(
            TransactionRow.account_id == konten["Girokonto"].id)) > 5  # trotz Ablehnung beim ersten Versuch
        assert s.scalar(select(Holding.einstand)) == 80
