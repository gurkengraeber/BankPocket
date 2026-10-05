"""FinTS-Anbindung (ING, Consorsbank, …) über python-fints.

Ablauf eines Abrufs:
  1. Client aus gespeicherten Sitzungsdaten erzeugen (System-ID bleibt gleich → Bank kennt das „Gerät“)
  2. TAN-Verfahren wählen (App-Freigabe bevorzugt) und ggf. TAN-Medium
  3. Dialog öffnen; verlangt die Bank eine starke Authentifizierung (alle ~90 Tage), wird die Freigabe
     in der Banking-App abgewartet (Polling)
  4. Konten, Salden, Umsätze und Depotbestände laden
  5. Sitzungsdaten zurückgeben, damit der nächste Abruf ohne neue Freigabe auskommt
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from fints.client import FinTS3PinTanClient, FinTSOperations, NeedTANResponse
from fints.exceptions import (FinTSClientPINError, FinTSClientTemporaryAuthError, FinTSConnectionError,
                              FinTSError, FinTSSCARequiredError)
from fints.formals import SecurityMethod, SecurityProfile
from fints.models import SEPAAccount

from ..csv_import import extract_sepa_ids
from ..models import Transaction
from .base import (AuswahlNoetig, FetchedAccount, FetchedHolding, FetchError, FetchResult, FreigabeNoetig,
                   Interaktion, PinFalsch, ZugangGesperrt)

log = logging.getLogger(__name__)

# FinTS-Zugänge aus öffentlichen Bankverzeichnissen; über „Andere Bank“ frei eintragbar.
BANKEN = {
    "ing": {"name": "ING", "blz": "50010517", "url": "https://fints.ing.de/fints/"},
    "consorsbank": {"name": "Consorsbank", "blz": "76030080", "url": "https://brokerage-hbci.consorsbank.de/hbci"},
}

ERSTABRUF_TAGE = 730  # beim ersten freigegebenen Abruf so viel Historie wie die Bank hergibt
HINTERGRUND_TAGE = 89  # ohne neue Freigabe liefern Banken nur ~90 Tage
UEBERLAPPUNG_TAGE = 14  # Puffer für nachträglich gebuchte Umsätze; Duplikate fängt der Hash ab
FREIGABE_TIMEOUT = 300  # Sekunden, die auf eine App-Freigabe oder TAN gewartet wird

_APP_STICHWORTE = ("app", "decoupled", "push", "freigabe", "securego", "bestsign", "seal")
_GERAET_STICHWORTE = ("generator", "chiptan", "sms", "photo", "foto", "qr", "manuell", "optisch", "lesegerät")
# Kontoabfragen, für die eine Bank nach PSD2 eine starke Authentifizierung verlangen kann
SEGMENTE_MIT_SCA = {"HKSAL", "HKKAZ", "HKCAZ", "HKWPD"}
OHNE_HKKAZ7 = {"76030080"}  # Consorsbank
_AUTH_FEHLER = (FinTSClientPINError, FinTSClientTemporaryAuthError, FinTSSCARequiredError)


def kontoart(code) -> str:
    """FinTS-Kontoart aus den Benutzerparametern (UPD) → unser Kontotyp."""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "giro"
    if 10 <= c <= 29 or 70 <= c <= 79:
        return "spar"
    if 30 <= c <= 39 or 60 <= c <= 69:
        return "depot"
    if 50 <= c <= 59:
        return "kreditkarte"
    return "giro"


def waehle_tan_verfahren(verfahren: dict) -> str | None:
    """App-Freigabe (decoupled) bevorzugen; None, wenn die Wahl nicht eindeutig ist."""
    if len(verfahren) == 1:
        return next(iter(verfahren))

    def punkte(p) -> int:
        n = 2 if getattr(p, "decoupled_max_poll_number", None) is not None else 0
        name = (getattr(p, "name", "") or "").lower()
        n += 1 if any(w in name for w in _APP_STICHWORTE) else 0
        return n - (1 if any(w in name for w in _GERAET_STICHWORTE) else 0)

    wertung = sorted(((punkte(p), k) for k, p in verfahren.items()), reverse=True)
    if wertung and wertung[0][0] > 0 and (len(wertung) == 1 or wertung[0][0] > wertung[1][0]):
        return wertung[0][1]
    return None


# IBAN-Längen der SEPA-Länder (für das Abtrennen der IBAN vom Namen)
_IBAN_LAENGE = {"AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "EE": 20,
                "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HR": 21, "HU": 28, "IE": 22, "IS": 26,
                "IT": 27, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MT": 31, "NL": 18, "NO": 15,
                "PL": 28, "PT": 25, "RO": 24, "SE": 24, "SI": 19, "SK": 24, "SM": 27}
_RE_KONTONUMMER_VORN = re.compile(r"^\d{5,12}(?=\D)")


def iban_gueltig(iban: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    umgestellt = iban[4:] + iban[:4]
    return int("".join(str(int(ch, 36)) for ch in umgestellt)) % 97 == 1


def gegenpartei_trennen(name: str) -> tuple[str, str]:
    """mt940 5.x setzt Feld ?31 (Konto des Gegenübers) vor den Namen: 'DE02…0101Streamflix GmbH'.
    Gibt (IBAN, Name) zurück; die IBAN nur, wenn ihre Prüfziffer stimmt."""
    laenge = _IBAN_LAENGE.get(name[:2])
    if laenge and len(name) >= laenge and iban_gueltig(name[:laenge]):
        return name[:laenge], name[laenge:].strip()
    m = _RE_KONTONUMMER_VORN.match(name)  # alte Kontonummer statt IBAN
    if m:
        return "", name[m.end():].strip()
    return "", name


def _datum(x) -> date | None:
    return date(x.year, x.month, x.day) if x is not None else None


def _text(x) -> str:
    return " ".join(str(x).split()) if x else ""


def mt940_zu_transaktion(daten: dict) -> Transaction | None:
    """Umsatz aus python-fints (MT940 oder CAMT) in unser Format übersetzen."""
    amount = daten.get("amount")
    buchung = _datum(daten.get("entry_date") or daten.get("date"))
    if amount is None or buchung is None:
        return None
    zweck = _text(daten.get("purpose"))
    cid = _text(daten.get("applicant_creditor_id"))
    mref = _text(daten.get("additional_position_reference")
                 or daten.get("EntryDetails.TransactionDetails.References.MandateIdentification"))
    if not (cid and mref):
        cid2, mref2 = extract_sepa_ids(zweck)
        cid, mref = cid or cid2, mref or mref2
    iban = (daten.get("applicant_iban") or daten.get("gvc_applicant_iban") or "").replace(" ", "")
    name = _text(daten.get("applicant_name"))
    if not iban:
        iban, name = gegenpartei_trennen(name)
    return Transaction(
        buchungsdatum=buchung,
        betrag=Decimal(amount.amount),
        gegenpartei=name,
        verwendungszweck=zweck,
        iban_gegenpartei=iban,
        glaeubiger_id=cid,
        mandatsreferenz=mref,
        rohdaten=json.dumps(daten, default=str, ensure_ascii=False),
        buchungstext=_text(daten.get("posting_text")),
    )


def holding_zu_daten(h, heute: date) -> FetchedHolding:
    def dec(x):
        return None if x is None else Decimal(str(x))

    menge, kurs, wert = dec(h.pieces) or Decimal(0), dec(h.market_value), dec(h.total_value)
    if wert is None and kurs is not None:
        wert = menge * kurs
    return FetchedHolding(symbol=h.ISIN or "", name=(h.name or "").strip(), menge=menge, kurs=kurs,
                          wert=(wert or Decimal(0)).quantize(Decimal("0.01")),
                          datum=h.valuation_date or heute)


def signaturprofil_korrigieren(client) -> None:
    """python-fints schreibt in den Signaturkopf immer Sicherheitsprofil „PIN, Version 1“. Beim Zwei-Schritt-Verfahren
    gehört dort Version 2 hin (wie im Verschlüsselungskopf); die Consorsbank lehnt die Nachricht sonst mit
    „9010 Ungültiger Signaturaufbau“ ab."""
    original = getattr(client, "_new_dialog", None)
    if original is None:
        return

    def neuer_dialog(*args, **kw):
        dialog = original(*args, **kw)
        for auth in getattr(dialog, "auth_mechanisms", None) or []:
            if str(getattr(auth, "security_function", "999")) == "999":
                continue

            def sign_prepare(message, _auth=auth, _original=auth.sign_prepare):
                _original(message)
                _auth.pending_signature.security_profile = SecurityProfile(SecurityMethod.PIN, 2)

            auth.sign_prepare = sign_prepare
        return dialog

    client._new_dialog = neuer_dialog


def umsatzabfrage_ohne_version_7(client) -> None:
    """Die Consorsbank kündigt die Umsatzabfrage in Version 7 an, lehnt sie aber ab („9010 Verarbeitung nicht
    möglich“); Version 6 funktioniert."""
    original = getattr(client, "_find_highest_supported_command", None)
    if original is None:
        return

    def hoechste(*kommandos, **kw):
        ohne = tuple(k for k in kommandos if k.__name__ != "HKKAZ7")
        return original(*(ohne or kommandos), **kw)

    client._find_highest_supported_command = hoechste


def _challenge_text(resp) -> str:
    return _text(getattr(resp, "challenge", None))


class FinTSSource:
    def __init__(self, *, blz: str, url: str, login: str, pin: str, product_id: str, interaktion: Interaktion,
                 client_data: bytes | None = None, tan_medium: str | None = None,
                 letzte_buchung: dict[str, date] | None = None, heute: date | None = None,
                 bei_freigabe: Callable[[str], None] | None = None,
                 client_factory=FinTS3PinTanClient, freigabe_timeout: float = FREIGABE_TIMEOUT,
                 schlafen: Callable[[float], None] | None = None, uhr: Callable[[], float] = time.monotonic,
                 **_andere):
        if not product_id:
            raise FetchError("Keine FinTS-Produkt-ID eingetragen (BANKPOCKET_FINTS_PRODUCT_ID in der .env).")
        self.blz, self.url, self.login, self.pin, self.product_id = blz, url, login, pin, product_id
        self.ia = interaktion
        self.client_data, self.tan_medium = client_data, tan_medium
        self.letzte_buchung = letzte_buchung or {}
        self.heute = heute or date.today()
        self.bei_freigabe = bei_freigabe
        self.client_factory = client_factory
        self.freigabe_timeout = freigabe_timeout
        self.schlafen = schlafen or self.ia.warten
        self.uhr = uhr
        self.freigabe_erfolgt = False
        self.tan_erzwingen = blz in OHNE_HKKAZ7  # die Consorsbank verlangt das TAN-Segment bei jedem Kontoabruf

    # ---------- Ablauf ----------
    def abrufen(self) -> FetchResult:
        """Abrufen; verlangt die Bank dabei eine starke Authentifizierung, die sie nicht angekündigt hat
        (Rückmeldung 9075, z. B. Consorsbank), ein zweites Mal mit TAN-Segment bei jedem Kontoabruf."""
        try:
            ergebnis = self._abrufen()
        except FreigabeNoetig as e:
            if self.tan_erzwingen or not self._sca_verlangt():
                raise
            self.client_data = e.client_data or self.client_data
        else:
            if self.tan_erzwingen or not self._sca_verlangt():
                return ergebnis
            self.client_data = ergebnis.client_data or self.client_data
        log.info("Bank verlangt starke Authentifizierung (9075) – neuer Versuch mit TAN-Segment")
        self.tan_erzwingen = True
        return self._abrufen()

    def _sca_verlangt(self) -> bool:
        return any(code == "9075" for code, _ in getattr(self, "bank_meldungen", []))

    def _tan_segment_erzwingen(self, client) -> None:
        original = getattr(client, "_need_twostep_tan_for_segment", None)
        if original is None:
            return

        def noetig(seg):
            if original(seg):
                return True
            zwei_schritt = client.get_current_tan_mechanism() not in (None, "999")
            return zwei_schritt and seg.header.type in SEGMENTE_MIT_SCA

        client._need_twostep_tan_for_segment = noetig

    def _abrufen(self) -> FetchResult:
        client = None
        try:
            self.ia.melden("verbinde", "Verbinde mit der Bank …")
            client = self.client_factory(self.blz, self.login, self.pin, self.url, product_id=self.product_id,
                                         from_data=self.client_data, tan_medium=self.tan_medium)
            self._bank_meldungen_merken(client)
            signaturprofil_korrigieren(client)
            if self.tan_erzwingen:
                self._tan_segment_erzwingen(client)
            if self.blz in OHNE_HKKAZ7:
                umsatzabfrage_ohne_version_7(client)
            self._tan_verfahren_waehlen(client)
            self._tan_medium_waehlen(client)
            with client:
                if client.init_tan_response:
                    self._tan(client, client.init_tan_response)
                self.ia.melden("abruf", "Lade Konten …")
                sepa = self._call(client, client.get_sepa_accounts) or []
                konten = self._konten(client, sepa)
            return FetchResult(
                konten=konten,
                client_data=client.deconstruct(including_private=True),
                tan_verfahren=client.get_current_tan_mechanism(),
                tan_verfahren_name=self._verfahren_name(client),
                tan_medium=client.selected_tan_medium,
                freigabe_erfolgt=self.freigabe_erfolgt,
            )
        except FetchError as e:
            e.client_data = e.client_data or self._sichern(client)
            raise
        except FinTSClientPINError as e:
            raise PinFalsch("Die Bank hat die Anmeldung abgelehnt – PIN oder Login falsch? Automatische Abrufe "
                            "sind gestoppt, damit dein Zugang nicht gesperrt wird." + self._bank_fehlertext(),
                            self._sichern(client)) from e
        except FinTSClientTemporaryAuthError as e:
            raise ZugangGesperrt("Der Zugang ist vorübergehend gesperrt – bitte im Online-Banking prüfen."
                                 + self._bank_fehlertext(), self._sichern(client)) from e
        except FinTSSCARequiredError as e:
            raise FreigabeNoetig("Die Bank verlangt eine Freigabe.", self._sichern(client)) from e
        except FinTSConnectionError as e:
            raise FetchError(f"Bank nicht erreichbar: {e}", self._sichern(client)) from e
        except FinTSError as e:
            raise FetchError(f"Fehler der Bank: {e}" + self._bank_fehlertext(), self._sichern(client)) from e

    @staticmethod
    def _sichern(client) -> bytes | None:
        try:
            return client.deconstruct(including_private=True) if client is not None else None
        except Exception:  # noqa: BLE001 – Sitzungsdaten sind nur ein Bonus
            return None

    def _verfahren_name(self, client) -> str | None:
        try:
            return client.get_tan_mechanisms()[client.get_current_tan_mechanism()].name
        except Exception:  # noqa: BLE001
            return None

    def _bank_meldungen_merken(self, client) -> None:
        """Antworten der Bank mitschreiben – python-fints meldet jeden Fehler beim Verbindungsaufbau als PIN-Fehler."""
        self.bank_meldungen: list[tuple[str, str]] = []
        original = getattr(client, "_process_response", None)
        if original is None:
            return

        def merken(dialog, segment, response):
            self.bank_meldungen.append((str(response.code), str(response.text)))
            return original(dialog, segment, response)

        client._process_response = merken

    def _bank_fehlertext(self) -> str:
        fehler = list(dict.fromkeys(f"{code} – {text}" for code, text in getattr(self, "bank_meldungen", [])
                                    if code.startswith("9")))
        if not fehler:
            return ""
        log.warning("Bank lehnt die Anmeldung ab: %s", "; ".join(fehler))
        return " Meldung der Bank: " + "; ".join(fehler)

    def _call(self, client, fn, *args):
        res = fn(*args)
        while isinstance(res, NeedTANResponse):
            res = self._tan(client, res)
        return res

    # ---------- TAN-Verfahren ----------
    def _tan_verfahren_waehlen(self, client) -> None:
        if self.client_data and client.get_current_tan_mechanism():
            return  # aus gespeicherten Sitzungsdaten
        self.ia.melden("verbinde", "Frage TAN-Verfahren ab …")
        client.fetch_tan_mechanisms()
        verfahren = {k: v for k, v in client.get_tan_mechanisms().items() if k != "999"}
        erlaubt = getattr(client, "allowed_security_functions", None) or []
        if erlaubt:
            verfahren = {k: v for k, v in verfahren.items() if k in erlaubt} or verfahren
        if not verfahren:
            return
        wahl = waehle_tan_verfahren(verfahren)
        if wahl is None:
            if not self.ia.interaktiv:
                raise AuswahlNoetig("Bitte wähle in der App dein TAN-Verfahren.")
            optionen = [{"id": k, "name": getattr(v, "name", None) or k} for k, v in verfahren.items()]
            self.ia.melden("auswahl", "Welches TAN-Verfahren nutzt du?", optionen=optionen)
            eingabe = self.ia.warte_auf_eingabe(self.freigabe_timeout)
            if not eingabe or eingabe.get("tan_verfahren") not in verfahren:
                raise AuswahlNoetig("Kein TAN-Verfahren gewählt.")
            wahl = eingabe["tan_verfahren"]
        client.set_tan_mechanism(wahl)

    def _tan_medium_waehlen(self, client) -> None:
        if client.selected_tan_medium is not None:
            return
        try:
            noetig = client.is_tan_media_required()
        except (KeyError, AttributeError):
            noetig = False
        if not noetig:
            return
        _, medien = client.get_tan_media()
        namen = [m.tan_medium_name for m in medien if getattr(m, "tan_medium_name", None)]
        if len(namen) <= 1:
            client.selected_tan_medium = namen[0] if namen else ""
            return
        if not self.ia.interaktiv:
            raise AuswahlNoetig("Bitte wähle in der App dein TAN-Gerät.")
        self.ia.melden("auswahl", "Welches Gerät nutzt du für Freigaben?",
                       optionen=[{"id": n, "name": n} for n in namen], feld="tan_medium")
        eingabe = self.ia.warte_auf_eingabe(self.freigabe_timeout)
        if not eingabe or eingabe.get("tan_medium") not in namen:
            raise AuswahlNoetig("Kein TAN-Gerät gewählt.")
        client.selected_tan_medium = eingabe["tan_medium"]

    # ---------- TAN / Freigabe ----------
    def _tan(self, client, resp):
        if resp.decoupled:
            return self._freigabe_abwarten(client, resp)
        return self._tan_eingeben(client, resp)

    def _poll_parameter(self, client) -> tuple[float, float, int, bool]:
        try:
            p = client.get_tan_mechanisms()[client.get_current_tan_mechanism()]
        except Exception:  # noqa: BLE001
            p = None
        erst = getattr(p, "wait_before_first_poll", None) or 3
        weiter = getattr(p, "wait_before_next_poll", None) or 2
        max_n = getattr(p, "decoupled_max_poll_number", None) or 999
        auto = getattr(p, "automated_polling_allowed", None)
        return min(max(erst, 1), 30), min(max(weiter, 1), 30), max_n, True if auto is None else bool(auto)

    def _freigabe_abwarten(self, client, resp):
        erst, weiter, max_n, auto = self._poll_parameter(client)
        text = _challenge_text(resp) or "Bitte bestätige den Zugriff in deiner Banking-App."
        ende = self.uhr() + self.freigabe_timeout
        self.ia.melden("freigabe", text, manuell_bestaetigen=not auto, sekunden=self.freigabe_timeout)
        if self.bei_freigabe:
            self.bei_freigabe(text)
        if auto:
            self.schlafen(erst)
        polls = 0
        while True:
            if not auto and self.ia.warte_auf_eingabe(ende - self.uhr()) is None:
                raise FreigabeNoetig("Die Freigabe wurde nicht bestätigt.")
            res = client.send_tan(resp, "")
            polls += 1
            if not (isinstance(res, NeedTANResponse) and res.decoupled):
                self.freigabe_erfolgt = True
                self.ia.melden("abruf", "Freigegeben – lade Daten …")
                return res
            resp = res
            if self.uhr() >= ende or polls >= max_n:
                raise FreigabeNoetig("Die Freigabe ist nicht rechtzeitig erfolgt. Starte den Abruf erneut, "
                                     "sobald du die Banking-App zur Hand hast.")
            if auto:
                self.schlafen(weiter)

    def _tan_eingeben(self, client, resp):
        if not self.ia.interaktiv:
            raise FreigabeNoetig("Die Bank verlangt eine TAN – bitte den Abruf in der App starten.")
        bild = None
        matrix = getattr(resp, "challenge_matrix", None)
        if matrix:
            mime, data = matrix
            bild = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        self.ia.melden("tan", _challenge_text(resp) or "Bitte gib die TAN ein.", bild=bild)
        eingabe = self.ia.warte_auf_eingabe(self.freigabe_timeout)
        tan = str((eingabe or {}).get("tan", "")).strip()
        if not tan:
            raise FreigabeNoetig("Es wurde keine TAN eingegeben.")
        self.freigabe_erfolgt = True
        self.ia.melden("abruf", "TAN gesendet – lade Daten …")
        return client.send_tan(resp, tan)

    # ---------- Konten ----------
    def _speicherzeitraum(self, client) -> int | None:
        try:
            seg = client.bpd.find_segment_first("HIKAZS")
            if seg is None:
                return None
            if hasattr(seg, "parameter"):
                tage = seg.parameter.storage_duration
            else:  # von python-fints nicht zerlegt (Consorsbank): …, [Speicherzeitraum, Anzahl erlaubt, alle Konten]
                tage = seg._additional_data[-1][0]
            return int(tage) if tage else None
        except Exception:  # noqa: BLE001
            return None

    def _startdatum(self, schluessel: str, speicher: int | None) -> date:
        letzte = self.letzte_buchung.get(schluessel)
        if letzte:
            start = letzte - timedelta(days=UEBERLAPPUNG_TAGE)
        else:
            start = self.heute - timedelta(days=ERSTABRUF_TAGE if self.ia.interaktiv else HINTERGRUND_TAGE)
        if speicher:
            start = max(start, self.heute - timedelta(days=speicher))
        if not self.ia.interaktiv:
            start = max(start, self.heute - timedelta(days=HINTERGRUND_TAGE))
        return start

    def _konten(self, client, sepa: list) -> list[FetchedAccount]:
        upd = client.get_information().get("accounts", [])

        def meta_fuer(iban, nummer) -> dict:
            for a in upd:
                if (iban and a.get("iban") == iban) or (nummer and a.get("account_number") == nummer):
                    return a
            return {}

        def name(meta: dict, iban, nummer) -> str:
            return _text(meta.get("product_name")) or f"Konto …{(iban or nummer or '')[-4:]}"

        def typ(meta: dict) -> str:
            # Manche Banken (ING) nennen keine Kontoart: Ein Konto, das nur Depotbestände liefert, ist ein Depot.
            ops = meta.get("supported_operations") or {}
            if ops.get(FinTSOperations.GET_HOLDINGS) and not (
                    ops.get(FinTSOperations.GET_TRANSACTIONS) or ops.get(FinTSOperations.GET_BALANCE)):
                return "depot"
            return kontoart(meta.get("type"))

        speicher = self._speicherzeitraum(client)
        konten, gesehen = [], set()
        for acc in sepa:
            meta = meta_fuer(acc.iban, acc.accountnumber)
            gesehen.add(acc.accountnumber)
            fa = FetchedAccount(kontonummer=acc.accountnumber, unterkonto=acc.subaccount, iban=acc.iban,
                                name=name(meta, acc.iban, acc.accountnumber), typ=typ(meta),
                                waehrung=meta.get("currency") or "EUR")
            self._konto_laden(client, acc, fa, meta.get("supported_operations") or {}, speicher)
            konten.append(fa)

        # Depots haben keine IBAN und fehlen deshalb in der SEPA-Kontoliste
        for meta in upd:
            ops = meta.get("supported_operations") or {}
            if (typ(meta) != "depot" or meta.get("account_number") in gesehen
                    or not ops.get(FinTSOperations.GET_HOLDINGS)):
                continue
            # python-fints liest das Land der Bank aus der BIC – ohne BIC scheitert die Depotabfrage
            bic = next((k.bic for k in sepa if k.bic), None)
            if not bic:
                continue
            acc = SEPAAccount(iban=None, bic=bic, accountnumber=meta["account_number"],
                              subaccount=meta.get("subaccount_number"), blz=self.blz)
            fa = FetchedAccount(kontonummer=meta["account_number"], unterkonto=meta.get("subaccount_number"),
                                name=name(meta, None, meta["account_number"]), typ="depot",
                                waehrung=meta.get("currency") or "EUR")
            self._konto_laden(client, acc, fa, ops, speicher)
            konten.append(fa)
        return konten

    def _konto_laden(self, client, acc, fa: FetchedAccount, ops: dict, speicher: int | None) -> None:
        """Ein Konto laden. Fehler bei einem Konto stoppen nicht die anderen (außer Anmeldefehler)."""
        self.ia.melden("abruf", f"Lade {fa.name} …")
        try:
            if fa.typ == "depot":
                holdings = self._call(client, client.get_holdings, acc) or []
                fa.holdings = [holding_zu_daten(h, self.heute) for h in holdings]
                fa.saldo = sum((h.wert for h in fa.holdings), Decimal(0))
                fa.saldo_datum = self.heute
                return
            if ops.get(FinTSOperations.GET_BALANCE, True):
                saldo = self._call(client, client.get_balance, acc)
                if saldo is not None:
                    fa.saldo = Decimal(saldo.amount.amount)
                    fa.saldo_datum = _datum(saldo.date)
            start = self._startdatum(acc.iban or acc.accountnumber, speicher)
            umsaetze = self._call(client, client.get_transactions, acc, start, self.heute) or []
            fa.transaktionen = [t for t in (mt940_zu_transaktion(u.data) for u in umsaetze) if t]
        except _AUTH_FEHLER:
            raise
        except FinTSError as e:
            log.warning("Abruf für %s fehlgeschlagen: %s", fa.name, e)
        except (TypeError, KeyError, ValueError, AttributeError) as e:  # Eigenheiten einzelner Banken in python-fints
            log.warning("Abruf für %s fehlgeschlagen: %s", fa.name, e, exc_info=True)
