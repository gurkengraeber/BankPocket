"""Bank Norwegian (und weitere Banken) über Enable Banking, die PSD2-Schnittstelle für Privatpersonen.

Einrichtung bei Enable Banking (kostenlos, nur eigene Konten): eine Anwendung für „Production“ registrieren,
Application-ID und privaten Schlüssel (PEM) in BankPocket eintragen, die Adresse von BankPocket als Redirect-URL
hinterlegen und die eigenen Konten freischalten.

Ablauf: Beim ersten Abruf (und etwa alle 90 Tage) öffnest du einen Link, bestätigst den Zugriff bei der Bank
und landest wieder in BankPocket. Die Sitzung wird verschlüsselt gespeichert; Hintergrund-Abrufe nutzen sie.
Läuft sie ab, fordern Hintergrund-Abrufe bewusst keine neue an – du bekommst einen Hinweis.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..models import Transaction
from .base import (FetchedAccount, FetchError, FetchResult, FreigabeNoetig, Interaktion, PinFalsch, ZugangGesperrt)

log = logging.getLogger(__name__)

BASIS = "https://api.enablebanking.com"
CENT = Decimal("0.01")
ZUGRIFF_TAGE = 89  # etwas unter den üblichen 90 Tagen, falls die Bank keine längere Dauer nennt
AUSGLEICH_CODES = ("einzahlung",)  # Kreditkarte: Ausgleich vom eigenen Konto, keine Einnahme
ERSTABRUF_TAGE = 730
HINTERGRUND_TAGE = 89
WARTEN_AUF_BANK = 900  # Sekunden für Link öffnen, Freigabe, Rückkehr
# Bevorzugte Saldenarten (ISO 20022): abgeschlossen/gebucht vor vorläufig vor verfügbar
SALDO_ARTEN = ("CLBD", "ITBD", "XPCD", "OPBD", "ITAV", "CLAV", "FWAV")
SITZUNG_VORBEI = ("SESSION", "EXPIRED", "CONSENT", "REVOKED", "CLOSED", "ACCESS")


# Banken, die BankPocket über Enable Banking anbietet (Kürzel der Verbindung → Name bei Enable Banking)
BANKEN = {"norwegian": "Bank Norwegian", "consorsbank": "Consorsbank"}


def _b64(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).rstrip(b"=").decode()


def jwt_erzeugen(app_id: str, pem: str, jetzt: float | None = None) -> str:
    """Kurzlebiges JWT (RS256), mit dem sich BankPocket bei Enable Banking ausweist."""
    schluessel = serialization.load_pem_private_key(pem.strip().encode(), password=None)
    t = int(jetzt if jetzt is not None else time.time())
    kopf = {"typ": "JWT", "alg": "RS256", "kid": app_id}
    inhalt = {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": t, "exp": t + 3600}
    text = _b64(json.dumps(kopf, separators=(",", ":")).encode()) + "." + _b64(json.dumps(inhalt, separators=(",", ":")).encode())
    signatur = schluessel.sign(text.encode(), padding.PKCS1v15(), hashes.SHA256())
    return text + "." + _b64(signatur)


def code_aus_eingabe(text: str) -> tuple[str, str | None]:
    """Der Code steht in der Adresse, auf die die Bank zurückleitet. Eingefügt werden darf die ganze Adresse."""
    text = (text or "").strip()
    if "code=" in text:
        q = parse_qs(urlparse(text).query or text.lstrip("?"))
        if q.get("code"):
            return q["code"][0], (q.get("state") or [None])[0]
    return text, None


def fehler_aus_eingabe(text: str) -> str | None:
    """Lehnt die Bank ab, steht in der Rückkehr-Adresse statt des Codes ein Fehler (error, error_description)."""
    text = (text or "").strip()
    if "error=" not in text:
        return None
    q = parse_qs(urlparse(text).query or text.lstrip("?"))
    if q.get("code") or not q.get("error"):
        return None
    return " – ".join(x for x in (q["error"][0], (q.get("error_description") or [""])[0]) if x)


def _betrag(daten: dict | None) -> Decimal | None:
    try:
        return Decimal(str((daten or {})["amount"]))
    except (KeyError, InvalidOperation):
        return None


def umsatz(e: dict, karte: bool = False) -> Transaction | None:
    """Eine Enable-Banking-Buchung als BankPocket-Umsatz (nur gebuchte)."""
    if str(e.get("status", "BOOK")).upper() != "BOOK":
        return None
    betrag = _betrag(e.get("transaction_amount"))
    tag = e.get("booking_date") or e.get("value_date") or e.get("transaction_date")
    if betrag is None or not tag:
        return None
    betrag = abs(betrag) if e.get("credit_debit_indicator") == "CRDT" else -abs(betrag)
    # Bei Ausgaben ist die Gegenpartei der Empfänger, bei Eingängen der Absender
    partei = (e.get("creditor") if betrag < 0 else e.get("debtor")) or e.get("creditor") or e.get("debtor") or {}
    zweck = " ".join(str(z) for z in (e.get("remittance_information") or []) if z).strip()
    kennung = e.get("entry_reference") or e.get("transaction_id")
    if not kennung:  # sehr selten: stabile Ersatz-ID
        kennung = hashlib.sha256(f"{tag}|{betrag}|{partei.get('name')}|{zweck}".encode()).hexdigest()[:20]
    art = e.get("bank_transaction_code") if isinstance(e.get("bank_transaction_code"), dict) else {}
    return Transaction(
        buchungsdatum=date.fromisoformat(str(tag)[:10]), betrag=betrag.quantize(CENT),
        gegenpartei=(partei.get("name") or "").strip(), verwendungszweck=zweck,
        buchungstext=str(art.get("description") or ""),
        intern=karte and str(art.get("code") or "").strip().lower() in AUSGLEICH_CODES,
        extern_id=f"eb-{kennung}", rohdaten=json.dumps(e, default=str))


class EnableBankingSource:
    def __init__(self, *, login: str, pin: str, interaktion: Interaktion, url: str = "",
                 client_data: bytes | None = None, letzte_buchung: dict[str, date] | None = None,
                 heute: date | None = None, verbindung_id: int = 0, http: httpx.Client | None = None,
                 uhr=time.time, bank_name: str | None = None, bank: str = "norwegian", land: str = "DE",
                 **_andere):
        self.app_id, self.pem = login.strip(), pin.strip()
        self.redirect = url
        self.ia = interaktion
        self.sitzung = json.loads(client_data) if client_data else None
        self.letzte_buchung = letzte_buchung or {}
        self.heute = heute or date.today()
        self.verbindung_id = verbindung_id
        self.http = http or httpx.Client(timeout=30)
        self.uhr = uhr
        self.bank_name, self.land = bank_name or BANKEN.get(bank, BANKEN["norwegian"]), land
        self.neu_freigegeben = False
        self.zugriff_tage = ZUGRIFF_TAGE

    # ---------- HTTP ----------
    def _anfrage(self, methode: str, pfad: str, **kw) -> dict:
        try:
            token = jwt_erzeugen(self.app_id, self.pem, self.uhr())
        except (ValueError, TypeError) as e:
            raise PinFalsch("Der private Schlüssel ist ungültig – bitte die komplette PEM-Datei einfügen "
                            "(von „BEGIN“ bis „END PRIVATE KEY“). Automatische Abrufe sind gestoppt.") from e
        try:
            r = self.http.request(methode, f"{BASIS}{pfad}", headers={"Authorization": f"Bearer {token}"}, **kw)
        except httpx.HTTPError as e:
            raise FetchError(f"Enable Banking nicht erreichbar: {e}") from e
        if r.status_code < 400:
            return r.json() if r.content else {}
        try:
            daten = r.json()
        except ValueError:
            daten = {}
        meldung = str(daten.get("message") or daten.get("error") or "")
        fehler = FehlerAntwort(f"Enable Banking: {meldung or f'Fehler {r.status_code}'}")
        fehler.status, fehler.code = r.status_code, str(daten.get("error") or daten.get("code") or "")
        fehler.text = f"{fehler.code} {meldung}".upper()
        raise fehler

    def _app_pruefen(self) -> None:
        try:
            self._anfrage("GET", "/application")
        except FehlerAntwort as e:
            if e.status in (401, 403):
                raise PinFalsch("Enable Banking lehnt Application-ID oder Schlüssel ab. "
                                "Automatische Abrufe sind gestoppt.") from e
            raise

    # ---------- Freigabe ----------
    def _bank(self) -> dict:
        antwort = self._anfrage("GET", "/aspsps", params={"country": self.land, "service": "AIS"})
        liste = antwort.get("aspsps", antwort) if isinstance(antwort, dict) else antwort
        treffer = [b for b in liste or [] if self.bank_name.lower() in str(b.get("name", "")).lower()]
        if not treffer:
            raise FetchError(f"{self.bank_name} wird von Enable Banking für {self.land} gerade nicht angeboten.")
        genau = [b for b in treffer if str(b["name"]).lower() == self.bank_name.lower()]
        wahl = (genau or treffer)[0]
        try:  # so lange freigeben, wie die Bank erlaubt (Sekunden), einen Tag Luft lassen
            self.zugriff_tage = max(1, int(wahl["maximum_consent_validity"]) // 86400 - 1)
        except (KeyError, TypeError, ValueError):
            self.zugriff_tage = ZUGRIFF_TAGE
        return {"name": wahl["name"], "country": wahl.get("country", self.land)}

    def _freigeben(self) -> dict:
        if not self.ia.interaktiv:
            raise FreigabeNoetig("Die Freigabe bei der Bank ist abgelaufen – bitte in BankPocket neu freigeben.")
        if not self.redirect:
            raise FetchError("Für diese Verbindung ist keine Rückkehr-Adresse (Redirect-URL) gespeichert.")
        state = f"bp{self.verbindung_id}-{uuid.uuid4().hex[:12]}"
        bank = self._bank()
        ablauf = datetime.now(timezone.utc) + timedelta(days=self.zugriff_tage)
        start = self._anfrage("POST", "/auth", json={
            "access": {"valid_until": ablauf.strftime("%Y-%m-%dT%H:%M:%SZ")}, "aspsp": bank,
            "state": state, "redirect_url": self.redirect, "psu_type": "personal", "language": "de"})
        self.ia.melden("link", "Öffne den Link und bestätige den Zugriff bei deiner Bank.", url=start["url"],
                       redirect=self.redirect)
        ende = self.uhr() + WARTEN_AUF_BANK
        while True:
            eingabe = self.ia.warte_auf_eingabe(max(0.05, ende - self.uhr()))
            if not eingabe or not eingabe.get("code"):
                raise FreigabeNoetig("Die Freigabe bei der Bank wurde nicht abgeschlossen.")
            abgelehnt = fehler_aus_eingabe(str(eingabe["code"]))
            if abgelehnt:
                raise FetchError(f"Die Freigabe bei {self.bank_name} ist gescheitert. Meldung: {abgelehnt}")
            code, zurueck_state = code_aus_eingabe(str(eingabe["code"]))
            if not zurueck_state or zurueck_state == state:
                break
            # Fremder oder veralteter state (alte Adresse, fremder Aufruf der Rückkehr-Adresse): nicht abbrechen,
            # sondern weiter auf die richtige Rückkehr warten.
            if self.uhr() >= ende:
                raise FetchError("Die eingefügte Adresse gehört zu einer anderen Freigabe – bitte den Link neu öffnen.")
            self.ia.melden("link", "Diese Adresse gehört zu einer anderen Freigabe – bitte den Link neu öffnen.",
                           url=start["url"], redirect=self.redirect)
        self.ia.melden("abruf", "Freigabe erhalten – lade Konten …")
        try:
            s = self._anfrage("POST", "/sessions", json={"code": code})
        except FehlerAntwort as e:
            log.warning("Enable Banking lehnt die Sitzung ab (%s): %s", e.status, e)
            raise FetchError("Die Bank hat die Freigabe nicht bestätigt (der Code ist ungültig oder abgelaufen). "
                             f"Meldung von {e}") from e
        self.neu_freigegeben = True
        return {"session_id": s.get("session_id"), "accounts": [
            {"uid": a["uid"], "hash": a.get("identification_hash") or a["uid"], "name": a.get("name") or "",
             "iban": (a.get("account_id") or {}).get("iban"), "currency": a.get("currency") or "EUR",
             "typ": a.get("cash_account_type")} for a in s.get("accounts", [])],
            "valid_until": (s.get("access") or {}).get("valid_until")}

    def _sitzung_gueltig(self) -> bool:
        s = self.sitzung
        if not s or not s.get("accounts"):
            return False
        bis = s.get("valid_until")
        if bis:
            try:
                if datetime.fromisoformat(bis.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    return False
            except ValueError:
                pass
        return True

    # ---------- Ablauf ----------
    def abrufen(self) -> FetchResult:
        self.ia.melden("verbinde", "Verbinde mit Enable Banking …")
        self._app_pruefen()
        if not self._sitzung_gueltig():
            self.sitzung = self._freigeben()
        try:
            konten = self._konten()
        except FehlerAntwort as e:
            if e.status in (401, 403, 422) and any(w in e.text for w in SITZUNG_VORBEI):
                if not self.ia.interaktiv:
                    raise FreigabeNoetig("Die Freigabe bei der Bank ist abgelaufen – bitte in BankPocket neu freigeben.") from e
                self.sitzung = self._freigeben()
                konten = self._konten()
            else:
                raise self._uebersetzen(e) from e
        return FetchResult(konten=konten, client_data=json.dumps(self.sitzung).encode(),
                           freigabe_erfolgt=self.neu_freigegeben)

    @staticmethod
    def _uebersetzen(e: "FehlerAntwort") -> FetchError:
        if e.status == 429:
            return ZugangGesperrt("Die Bank erlaubt Abrufe ohne deine Mitwirkung nur wenige Male am Tag – "
                                  "bitte später erneut versuchen.")
        return e

    def _konten(self) -> list[FetchedAccount]:
        konten = []
        for i, a in enumerate(self.sitzung["accounts"], 1):
            self.ia.melden("abruf", f"Lade Konto {i} von {len(self.sitzung['accounts'])} …")
            kreditkarte = (a.get("typ") or "").upper() == "CARD" or not a.get("iban")
            nummer = f"eb-{a['hash']}"
            saldo, saldo_tag = self._saldo(a["uid"])
            tx = [t for t in (umsatz(e, kreditkarte) for e in self._umsaetze(a["uid"], nummer)) if t]
            konten.append(FetchedAccount(
                kontonummer=nummer, iban=a.get("iban"), name=a.get("name") or self.bank_name,
                typ="kreditkarte" if kreditkarte else "giro", waehrung=a.get("currency") or "EUR",
                saldo=saldo, saldo_datum=saldo_tag or self.heute, transaktionen=tx))
        return konten

    def _saldo(self, uid: str) -> tuple[Decimal | None, date | None]:
        salden = self._anfrage("GET", f"/accounts/{uid}/balances").get("balances", [])
        for art in SALDO_ARTEN:
            for b in salden:
                if b.get("balance_type") == art and _betrag(b.get("balance_amount")) is not None:
                    tag = b.get("reference_date")
                    return _betrag(b["balance_amount"]).quantize(CENT), date.fromisoformat(tag) if tag else None
        return None, None

    def _startdatum(self, nummer: str) -> date:
        letzte = self.letzte_buchung.get(nummer)
        if letzte:
            return letzte - timedelta(days=14)
        return self.heute - timedelta(days=ERSTABRUF_TAGE if self.ia.interaktiv else HINTERGRUND_TAGE)

    def _umsaetze(self, uid: str, nummer: str) -> list[dict]:
        ab = self._startdatum(nummer)
        try:
            return self._seiten(uid, ab)
        except FehlerAntwort as e:
            # Zu weit zurück liegender Starttag: ohne neue Freigabe erlauben Banken meist nur etwa 90 Tage
            if e.status in (400, 422) and (self.heute - ab).days > HINTERGRUND_TAGE and not any(
                    w in e.text for w in SITZUNG_VORBEI):
                return self._seiten(uid, self.heute - timedelta(days=HINTERGRUND_TAGE))
            raise

    def _seiten(self, uid: str, ab: date) -> list[dict]:
        ergebnis, schluessel = [], None
        for _ in range(100):
            params = {"date_from": ab.isoformat(), "date_to": self.heute.isoformat()}
            if schluessel:
                params["continuation_key"] = schluessel
            antwort = self._anfrage("GET", f"/accounts/{uid}/transactions", params=params)
            ergebnis += antwort.get("transactions", [])
            schluessel = antwort.get("continuation_key")
            if not schluessel:
                break
        return ergebnis


class FehlerAntwort(FetchError):
    """Fehlerantwort von Enable Banking mit Statuscode für die Weiterverarbeitung."""
    status: int = 0
    code: str = ""
    text: str = ""

    def __init__(self, meldung: str):
        super().__init__(meldung)
