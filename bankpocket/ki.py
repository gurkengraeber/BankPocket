"""KI-Einordnung von Händlern, die keine Regel erkennt – über die API von Mistral (La Plateforme).

Datenschutz: Gesendet werden nur Händlername und ein bereinigter, gekürzter Verwendungszweck – ohne IBANs,
Beträge, Kontostände oder Nummern. Überweisungen an Privatpersonen werden gar nicht gesendet: Nur Buchungen,
die nach Händler aussehen (Lastschrift mit Gläubiger-ID, Kartenzahlung, PayPal-Einkauf, Firmenname), gehen raus.
Jeder Händler wird nur einmal gefragt; das Ergebnis bleibt in der Datenbank.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

import httpx

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .contracts import (AUSGABEN_REGELN, EINNAHMEN_REGELN, FALLBACK, KI_KATEGORIEN, haendler_schluessel,
                        paypal_merchant, regelkategorie)
from .db import Account, KeyValue, KiKategorieRow, KategorieRow, TransactionRow
from .service import _to_dataclass

log = logging.getLogger(__name__)

MODELL = "mistral-small-latest"  # Einordnen ist eine einfache Aufgabe – das kleine Modell reicht und ist günstig
API_URL = "https://api.mistral.ai/v1/chat/completions"
PRO_ANFRAGE = 50  # Händler je Anfrage
MAX_JE_LAUF = 300  # Obergrenze je Lauf – hält Kosten und Laufzeit klein

_KARTE_ODER_LASTSCHRIFT = ("karte", "lastschrift", "debit", "visa", "mastercard", "girocard", "abbuchung",
                           "einzug", "apple pay", "google pay")
_FIRMA = re.compile(r"\b(gmbh|ag|se|kg|ug|e\.?\s?v|ohg|gbr|ltd|limited|inc|llc|s\.?a\.?r\.?l|s\.?a|b\.?v|"
                    r"plc|co|corp|eg|kgaa|mbh)\b|\.(com|de|net|eu|io)\b|\*", re.I)
_RE_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")
_RE_SEPA_FELD = re.compile(r"\b(EREF|MREF|CRED|SVWZ|ABWA|ABWE|KREF|IBAN|BIC)\+\S*", re.I)
_RE_MAIL = re.compile(r"\S+@\S+")
_RE_ZAHLEN = re.compile(r"[\d/.:-]*\d{3,}[\d/.:-]*")

SYSTEM = (
    "Du ordnest Buchungen von deutschen Bankkonten Kategorien zu. Je Buchung bekommst du den Namen des Händlers "
    "oder Zahlungsempfängers und einen gekürzten Verwendungszweck. Wähle für jede Nummer genau eine Kategorie "
    "aus der vorgegebenen Liste. Nutze dein Wissen über Firmen und Marken (z. B. Ketten, Online-Shops, "
    "Abodienste). Wenn keine Kategorie wirklich passt oder du den Händler nicht kennst, wähle „{fallback}“ – "
    "lieber das als raten."
)
FORMAT = (
    ' Antworte ausschließlich mit JSON in dieser Form: {"zuordnungen": [{"nr": 1, "kategorie": "…"}, …]} – '
    "mit einem Eintrag je Nummer und der Kategorie genau so geschrieben wie in der Liste."
)


# ---------- Einstellungen ----------
def _wert(s: Session, key: str) -> str | None:
    kv = s.get(KeyValue, key)
    return kv.value if kv else None


def _setzen(s: Session, key: str, value: str | None) -> None:
    kv = s.get(KeyValue, key)
    if value is None:
        if kv:
            s.delete(kv)
    elif kv:
        kv.value = value
    else:
        s.add(KeyValue(key=key, value=value))


def einstellungen(s: Session) -> dict:
    return {"aktiv": _wert(s, "ki_aktiv") == "1", "schluessel_gesetzt": bool(_wert(s, "ki_schluessel")),
            "letzte_meldung": _wert(s, "ki_meldung")}


def einstellungen_setzen(s: Session, vault, aktiv: bool | None = None, schluessel: str | None = None) -> None:
    if schluessel is not None:
        _setzen(s, "ki_schluessel", vault.encrypt(schluessel.strip()) if schluessel.strip() else None)
        _setzen(s, "ki_meldung", None)
    if aktiv is not None:
        _setzen(s, "ki_aktiv", "1" if aktiv else "0")


def laden(s: Session) -> None:
    KI_KATEGORIEN.clear()
    KI_KATEGORIEN.update({(r.typ, r.schluessel): r.kategorie for r in s.scalars(select(KiKategorieRow))})


def vergessen(s: Session) -> None:
    s.execute(delete(KiKategorieRow))
    KI_KATEGORIEN.clear()


# ---------- Was wird gefragt? ----------
def haendlerartig(t: TransactionRow) -> bool:
    """Sieht die Buchung nach Händler aus? Überweisungen an Privatleute sollen das Haus nicht verlassen."""
    return bool(t.glaeubiger_id or paypal_merchant(_to_dataclass(t))
                or any(w in t.buchungstext.lower() for w in _KARTE_ODER_LASTSCHRIFT)
                or _FIRMA.search(t.gegenpartei))


def bereinigen(zweck: str, laenge: int = 80) -> str:
    """Verwendungszweck ohne IBANs, SEPA-Referenzen, E-Mail-Adressen und längere Nummern."""
    for rx in (_RE_SEPA_FELD, _RE_IBAN, _RE_MAIL, _RE_ZAHLEN):
        zweck = rx.sub(" ", zweck)
    zweck = " ".join(zweck.split())
    return zweck[:laenge].rstrip()


def offene_haendler(s: Session) -> dict[tuple[str, str], dict]:
    """(typ, händlerschlüssel) → Beispiel für alle Händler ohne Regel, ohne KI-Ergebnis und ohne eigene Wahl."""
    konten = {a.id for a in s.scalars(select(Account).where(Account.typ != "depot", Account.quelle != "splitwise"))}
    offen: dict[tuple[str, str], dict] = {}
    anzahl: dict[tuple[str, str], int] = defaultdict(int)
    for t in s.scalars(select(TransactionRow).where(TransactionRow.intern.is_(False),
                                                    TransactionRow.kategorie.is_(None))):
        if t.account_id not in konten or t.betrag == 0:
            continue
        typ = "einnahme" if t.betrag > 0 else "ausgabe"
        schluessel = haendler_schluessel(t.gegenpartei, t.verwendungszweck)
        if not schluessel or (typ, schluessel) in KI_KATEGORIEN:
            continue
        if regelkategorie(t.gegenpartei, t.verwendungszweck, typ, t.buchungstext) or not haendlerartig(t):
            continue
        anzahl[(typ, schluessel)] += 1
        offen.setdefault((typ, schluessel), {
            "name": (paypal_merchant(_to_dataclass(t)) or t.gegenpartei).strip()[:80],
            "zweck": bereinigen(t.verwendungszweck),
        })
    # Häufige Händler zuerst – die bringen am meisten
    return dict(sorted(offen.items(), key=lambda kv: -anzahl[kv[0]]))


def _kategorien(s: Session, typ: str) -> list[str]:
    eingebaut = EINNAHMEN_REGELN if typ == "einnahme" else AUSGABEN_REGELN
    eigene = [k.name for k in s.scalars(select(KategorieRow).where(KategorieRow.typ == typ).order_by(KategorieRow.name))]
    return [*eingebaut, *eigene, FALLBACK[typ]]


def _kategorie_liste(s: Session, typ: str) -> str:
    eingebaut = EINNAHMEN_REGELN if typ == "einnahme" else AUSGABEN_REGELN
    zeilen = []
    for k in _kategorien(s, typ):
        beispiele = ", ".join(eingebaut.get(k, [])[:6])
        zeilen.append(f"- {k}" + (f" (z. B. {beispiele})" if beispiele else ""))
    return "\n".join(zeilen)


# ---------- Anfrage ----------
class KiFehler(Exception):
    """Die Mistral-API hat abgelehnt oder ist nicht erreichbar – mit einer Meldung für die Oberfläche."""


class MistralClient:
    """Schmaler Zugang zur Chat-Schnittstelle von Mistral (La Plateforme, Server in der EU)."""

    def __init__(self, schluessel: str, http: httpx.Client | None = None):
        self.schluessel = schluessel
        self.http = http or httpx.Client(timeout=120.0)

    def chat(self, modell: str, system: str, frage: str) -> str:
        try:
            r = self.http.post(API_URL, headers={"Authorization": f"Bearer {self.schluessel}"}, json={
                "model": modell, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": frage}]})
        except httpx.HTTPError as e:
            raise KiFehler("Mistral-API nicht erreichbar.") from e
        if r.status_code == 401:
            raise KiFehler("Der API-Schlüssel wurde abgelehnt.")
        if r.status_code in (402, 403):
            raise KiFehler("Der API-Schlüssel hat keine Berechtigung (Abo oder Guthaben prüfen).")
        if r.status_code == 429:
            raise KiFehler("Zu viele Anfragen – später erneut versuchen.")
        if r.status_code >= 400:
            raise KiFehler(f"Mistral-API-Fehler ({r.status_code}).")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise KiFehler("Unerwartete Antwort der Mistral-API.") from e


def _fragen(client: Any, s: Session, typ: str, posten: list[dict]) -> dict[int, str]:
    kategorien = _kategorien(s, typ)
    art = "Einnahmen" if typ == "einnahme" else "Ausgaben"
    zeilen = "\n".join(f"{i}. Name: {p['name']}" + (f" | Zweck: {p['zweck']}" if p["zweck"] else "")
                       for i, p in enumerate(posten, 1))
    text = client.chat(MODELL, SYSTEM.format(fallback=FALLBACK[typ]) + FORMAT,
                       f"Kategorien für {art}:\n{_kategorie_liste(s, typ)}\n\nBuchungen:\n{zeilen}")
    try:
        zuordnungen = json.loads(text)["zuordnungen"]
        # nur Kategorien aus der Liste zählen – erfundene fallen weg
        return {int(z["nr"]): z["kategorie"] for z in zuordnungen if z.get("kategorie") in kategorien}
    except (KeyError, TypeError, ValueError):
        log.warning("KI-Einordnung ohne verwertbares Ergebnis")
        return {}


def _client(ctx, s: Session):
    enc = _wert(s, "ki_schluessel")
    if not enc:
        return None
    schluessel = ctx.vault.decrypt_str(enc)
    if ctx.ki_client:
        return ctx.ki_client(schluessel)
    return MistralClient(schluessel)


def einordnen(ctx, s: Session, limit: int = MAX_JE_LAUF) -> dict:
    """Offene Händler von der KI einordnen lassen. Gibt {eingeordnet, offen} zurück."""
    client = _client(ctx, s)
    if client is None:
        raise RuntimeError("Kein API-Schlüssel hinterlegt.")
    offen = list(offene_haendler(s).items())[:limit]
    eingeordnet = 0
    for typ in ("ausgabe", "einnahme"):
        auswahl = [(k, v) for k, v in offen if k[0] == typ]
        for start in range(0, len(auswahl), PRO_ANFRAGE):
            teil = auswahl[start:start + PRO_ANFRAGE]
            ergebnis = _fragen(client, s, typ, [v for _, v in teil])
            for nr, kategorie in ergebnis.items():
                if 1 <= nr <= len(teil):
                    (t, schluessel), _ = teil[nr - 1]
                    s.merge(KiKategorieRow(typ=t, schluessel=schluessel, kategorie=kategorie))
                    eingeordnet += 1
            s.flush()
    laden(s)
    return {"eingeordnet": eingeordnet, "offen": len(offene_haendler(s))}


def einzeln_erkennen(ctx, s: Session, t: TransactionRow) -> str | None:
    """Eine einzelne Buchung auf ausdrücklichen Wunsch einordnen lassen – auch wenn sie nicht nach Händler
    aussieht. Das Ergebnis gilt für alle Buchungen desselben Händlers. None, wenn die KI nichts Passendes findet."""
    client = _client(ctx, s)
    if client is None:
        raise RuntimeError("Kein API-Schlüssel hinterlegt (Einstellungen → Kategorien mit KI).")
    typ = "einnahme" if t.betrag > 0 else "ausgabe"
    name = (paypal_merchant(_to_dataclass(t)) or t.gegenpartei).strip()[:80]
    ergebnis = _fragen(client, s, typ, [{"name": name or "unbekannt", "zweck": bereinigen(t.verwendungszweck)}])
    kategorie = ergebnis.get(1)
    if not kategorie or kategorie == FALLBACK[typ]:
        return None
    schluessel = haendler_schluessel(t.gegenpartei, t.verwendungszweck)
    if schluessel:
        s.merge(KiKategorieRow(typ=typ, schluessel=schluessel, kategorie=kategorie))
        s.flush()
        laden(s)
    else:  # kein Händlername: nur diese eine Buchung
        t.kategorie = kategorie
    return kategorie


def nachlauf(ctx, s: Session) -> None:
    """Nach einem Abruf: neue Händler einordnen, falls eingeschaltet. Fehler landen nur in der Meldung."""
    if _wert(s, "ki_aktiv") != "1" or not _wert(s, "ki_schluessel"):
        return
    from .service import sync_contracts
    try:
        erg = einordnen(ctx, s)
        if erg["eingeordnet"]:
            sync_contracts(s, ctx.today())  # Verträge übernehmen die neuen Kategorien
        _setzen(s, "ki_meldung", None)
    except Exception as e:  # noqa: BLE001 – die KI darf keinen Abruf verderben
        log.warning("KI-Einordnung fehlgeschlagen: %s", e)
        _setzen(s, "ki_meldung", fehlertext(e))
    s.commit()


def fehlertext(e: Exception) -> str:
    return str(e) or type(e).__name__
