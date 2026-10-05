"""Simulierte Bank für Tests der FinTS-Anbindung (verhält sich wie python-fints' FinTS3PinTanClient)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

from fints.client import FinTSOperations, NeedTANResponse
from fints.exceptions import FinTSClientPINError
from fints.models import Holding, SEPAAccount

from bankpocket.contracts import add_months

GIRO_IBAN = "DE11500105170000000001"
EXTRA_IBAN = "DE22500105170000000002"
DEPOT_IBAN = "DE33500105170005550001"


def need_tan(decoupled: bool = True, text: str = "Bitte bestätige den Zugriff in der ING-App.") -> NeedTANResponse:
    r = NeedTANResponse.__new__(NeedTANResponse)
    r.decoupled, r.challenge, r.challenge_matrix = decoupled, text, None
    return r


def umsatz(d: date, betrag: str, name: str, zweck: str = "", iban: str = "", cid: str = "", mref: str = "",
           text: str = "") -> NS:
    return NS(data={"amount": NS(amount=Decimal(betrag)), "entry_date": d, "date": d, "applicant_name": name,
                    "purpose": zweck, "applicant_iban": iban, "applicant_creditor_id": cid or None,
                    "additional_position_reference": mref or None, "posting_text": text})


APP = NS(name="App-Freigabe", decoupled_max_poll_number=60, wait_before_first_poll=1, wait_before_next_poll=1,
         automated_polling_allowed=True)
PHOTO = NS(name="photoTAN", decoupled_max_poll_number=None)


class FakeBank:
    def __init__(self, heute: date, pin: str = "1234", sca_bei_init: bool = True, polls_bis_freigabe: int = 2,
                 freigabe_kommt: bool = True, verfahren: dict | None = None, ohne_kontoart: bool = False):
        self.heute, self.pin = heute, pin
        self.ohne_kontoart = ohne_kontoart  # wie die ING: keine Kontoart, das Depot hat eine IBAN
        self.sca_bei_init, self.polls_bis_freigabe, self.freigabe_kommt = sca_bei_init, polls_bis_freigabe, freigabe_kommt
        self.verfahren = verfahren or {"900": PHOTO, "902": APP}
        self.sca_erledigt = False
        self.clients: list[FakeClient] = []
        self.zeitraeume: list[tuple[str, date, date]] = []
        self.polls = 0
        self.umsaetze = {"0000000001": self._giro_umsaetze(), "0000000002": []}

    def _giro_umsaetze(self) -> list[NS]:
        out = []
        for i in range(4):
            monat = add_months(date(2026, 6, 1), i)
            out.append(umsatz(monat.replace(day=15), "-12.99", "Streamflix GmbH", "Abo", "DE02100100100006820101",
                              "DE98ZZZ09999999999", "MR-100", "Lastschrift"))
            out.append(umsatz(monat.replace(day=28), "2500.00", "Musterfirma AG", "Gehalt", "DE33",
                              text="Gehalt/Rente"))
            out.append(umsatz(monat.replace(day=2), "-200.00", "Max Mustermann", "Sparen", EXTRA_IBAN,
                              text="Dauerauftrag"))
        return [u for u in out if u.data["entry_date"] <= self.heute]

    def factory(self, blz, login, pin, url, product_id=None, from_data=None, tan_medium=None):
        c = FakeClient(self, login, pin, from_data, tan_medium)
        self.clients.append(c)
        return c


class FakeClient:
    def __init__(self, bank: FakeBank, login, pin, from_data, tan_medium):
        self.bank, self.login, self.pin, self.from_data = bank, login, pin, from_data
        self.selected = "902" if from_data else None
        self.selected_tan_medium = tan_medium
        self.init_tan_response = None
        self.allowed_security_functions: list[str] = []
        self.bpd = NS(find_segment_first=lambda name: None)

    def _auth(self):
        if self.pin != self.bank.pin:
            raise FinTSClientPINError("Error during dialog initialization, PIN wrong?")

    def get_current_tan_mechanism(self):
        return self.selected

    def fetch_tan_mechanisms(self):
        self._auth()
        self.allowed_security_functions = list(self.bank.verfahren)

    def get_tan_mechanisms(self):
        return self.bank.verfahren

    def set_tan_mechanism(self, k):
        self.selected = k

    def is_tan_media_required(self):
        return False

    def __enter__(self):
        self._auth()
        if self.bank.sca_bei_init and not self.bank.sca_erledigt:
            self.init_tan_response = need_tan(decoupled=self.bank.verfahren[self.selected] is APP)
        return self

    def __exit__(self, *exc):
        return False

    def send_tan(self, resp, tan):
        self.bank.polls += 1
        if not resp.decoupled:
            if tan == "123456":
                self.bank.sca_erledigt = True
                return "ok"
            raise AssertionError("falsche TAN im Test")
        if self.bank.freigabe_kommt and self.bank.polls >= self.bank.polls_bis_freigabe:
            self.bank.sca_erledigt = True
            return "dialog-init-ok"
        return need_tan()

    def get_sepa_accounts(self):
        konten = [SEPAAccount(GIRO_IBAN, "INGDDEFFXXX", "0000000001", None, "50010517"),
                  SEPAAccount(EXTRA_IBAN, "INGDDEFFXXX", "0000000002", None, "50010517")]
        if self.bank.ohne_kontoart:
            konten.append(SEPAAccount(DEPOT_IBAN, "INGDDEFFXXX", "5550001", None, "50010517"))
        return konten

    def get_information(self):
        konto = {FinTSOperations.GET_BALANCE: True, FinTSOperations.GET_TRANSACTIONS: True}
        if self.bank.ohne_kontoart:
            return {"accounts": [
                {"iban": iban, "account_number": nummer, "subaccount_number": None, "type": None,
                 "product_name": name, "currency": "EUR", "supported_operations": ops}
                for iban, nummer, name, ops in (
                    (GIRO_IBAN, "0000000001", "Girokonto", konto), (EXTRA_IBAN, "0000000002", "Extra-Konto", konto),
                    (DEPOT_IBAN, "5550001", "Direkt-Depot", {FinTSOperations.GET_HOLDINGS: True}))]}
        return {"accounts": [
            {"iban": GIRO_IBAN, "account_number": "0000000001", "subaccount_number": None, "type": 1,
             "product_name": "Girokonto", "currency": "EUR", "supported_operations": konto},
            {"iban": EXTRA_IBAN, "account_number": "0000000002", "subaccount_number": None, "type": 10,
             "product_name": "Extra-Konto", "currency": "EUR", "supported_operations": konto},
            {"iban": None, "account_number": "5550001", "subaccount_number": None, "type": 30,
             "product_name": "Direkt-Depot", "currency": "EUR",
             "supported_operations": {FinTSOperations.GET_HOLDINGS: True}},
        ]}

    def get_balance(self, acc):
        assert acc.accountnumber != "5550001", "ein Depot hat keinen Saldo-Abruf"
        betrag = Decimal("1500.00") if acc.accountnumber == "0000000001" else Decimal("8000.00")
        return NS(amount=NS(amount=betrag), date=self.bank.heute)

    def get_transactions(self, acc, start, end):
        self.bank.zeitraeume.append((acc.accountnumber, start, end))
        return [u for u in self.bank.umsaetze.get(acc.accountnumber, []) if start <= u.data["entry_date"] <= end]

    def get_holdings(self, acc):
        return [Holding(ISIN="IE00B4L5Y983", name="iShares Core MSCI World", market_value=95.5,
                        value_symbol="EUR", valuation_date=self.bank.heute, pieces=10.0, total_value=955.0,
                        acquisitionprice=80.0)]

    def deconstruct(self, including_private=False):
        return b"fake-sitzungsdaten-mit-system-id"


def tage_vor(heute: date, n: int) -> date:
    return heute - timedelta(days=n)
