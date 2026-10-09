"""Umbuchungen zwischen eigenen Konten paaren: Abgang hier, Zugang dort.

Sichere Paare verbindet BankPocket selbst, unsichere legt es zur Bestätigung vor. Ein Paar besteht immer aus
zwei Buchungen auf verschiedenen eigenen Konten mit entgegengesetztem, gleich hohem Betrag in zeitlicher Nähe.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import FALLBACK, categorize
from .db import Account, TransactionRow

FENSTER_TAGE = 5  # so lange kann eine Überweisung zwischen zwei Banken unterwegs sein
SICHER, FRAGEN = 80, 55  # ab hier automatisch paaren bzw. nachfragen
# Kategorien, die einer Umbuchung nicht widersprechen (Sparplan-Einzahlung, Geld abheben)
NEUTRAL = {*FALLBACK.values(), "Sparen", "Bargeld", "Umbuchung"}
_HINWEISE = ("umbuchung", "übertrag", "uebertrag", "eigene", "einzahlung", "auszahlung", "transfer", "payment")
_QUELLE_NAME = {"trade_republic": "trade republic", "norwegian": "norwegian", "consorsbank": "consors", "ing": "ing",
                "paypal": "paypal", "binance": "binance", "n26": "n26", "revolut": "revolut"}


def _abgelehnt(t: TransactionRow) -> set[int]:
    return {int(x) for x in (t.paar_nein or "").split(",") if x}


def bewerten(a: TransactionRow, b: TransactionRow, konten: dict[int, Account]) -> int:
    """Wie sicher gehören a und b zusammen? 0, wenn sie gar nicht zusammenpassen können."""
    if a.account_id == b.account_id or a.betrag == 0 or a.betrag != -b.betrag:
        return 0
    abstand = abs((a.buchungsdatum - b.buchungsdatum).days)
    if abstand > FENSTER_TAGE or b.id in _abgelehnt(a) or a.id in _abgelehnt(b):
        return 0
    punkte = 40 + (10 if abstand <= 1 else -4 * (abstand - 1))
    if a.intern or b.intern:
        punkte += 25  # eine Seite gilt schon als Umbuchung (z. B. Einzahlung beim Broker, Kartenausgleich)
    ka, kb = konten[a.account_id], konten[b.account_id]
    if (kb.iban and a.iban_gegenpartei == kb.iban) or (ka.iban and b.iban_gegenpartei == ka.iban):
        punkte += 30
    for t, gegenkonto in ((a, kb), (b, ka)):
        text = f"{t.gegenpartei} {t.verwendungszweck} {t.buchungstext}".lower()
        name = _QUELLE_NAME.get(gegenkonto.quelle, "") or gegenkonto.name.lower()
        if (len(name) >= 3 and name in text) or any(h in text for h in _HINWEISE):
            punkte += 10
        if not t.intern:
            typ = "einnahme" if t.betrag > 0 else "ausgabe"
            kategorie = t.kategorie or categorize(t.gegenpartei, t.verwendungszweck, typ, buchungstext=t.buchungstext)
            if kategorie not in NEUTRAL:
                punkte -= 30  # erkannter Händler oder Vertrag – eher ein Zufall gleicher Beträge
    return max(punkte, 0)


def kandidaten(s: Session, t: TransactionRow, konten: dict[int, Account] | None = None) -> list[tuple[int, TransactionRow]]:
    """Mögliche Gegenbuchungen zu t, die wahrscheinlichste zuerst."""
    konten = konten or {a.id: a for a in s.scalars(select(Account))}
    rows = s.scalars(select(TransactionRow).where(
        TransactionRow.betrag == -t.betrag, TransactionRow.account_id != t.account_id,
        TransactionRow.gegenbuchung_id.is_(None),
        TransactionRow.buchungsdatum >= t.buchungsdatum - timedelta(days=FENSTER_TAGE),
        TransactionRow.buchungsdatum <= t.buchungsdatum + timedelta(days=FENSTER_TAGE)))
    bewertet = [(bewerten(t, r, konten), r) for r in rows]
    return sorted(((p, r) for p, r in bewertet if p > 0), key=lambda x: (-x[0], abs((x[1].buchungsdatum - t.buchungsdatum).days)))


def paaren(a: TransactionRow, b: TransactionRow) -> None:
    for t, gegen in ((a, b), (b, a)):
        t.gegenbuchung_id, t.intern, t.intern_fix = gegen.id, True, True


def loesen(s: Session, t: TransactionRow) -> None:
    gegen = s.get(TransactionRow, t.gegenbuchung_id) if t.gegenbuchung_id else None
    for x in (t, gegen):
        if x is not None:
            x.gegenbuchung_id = None


def vorschlaege(s: Session) -> list[tuple[int, TransactionRow, TransactionRow]]:
    """Alle denkbaren Paare (Abgang, Zugang) ohne Gegenbuchung – eindeutig zugeordnet, sicherste zuerst."""
    konten = {a.id: a for a in s.scalars(select(Account))}
    offen = list(s.scalars(select(TransactionRow).where(TransactionRow.betrag != 0,
                                                        TransactionRow.gegenbuchung_id.is_(None))))
    # Zugänge nach Betrag ablegen – so braucht es keine Datenbankabfrage je Abgang
    zugaenge: dict = {}
    for t in offen:
        if t.betrag > 0:
            zugaenge.setdefault(t.betrag, []).append(t)
    paare = []
    for a in (t for t in offen if t.betrag < 0):
        moeglich = sorted(((bewerten(a, b, konten), b) for b in zugaenge.get(-a.betrag, [])),
                          key=lambda x: (-x[0], abs((x[1].buchungsdatum - a.buchungsdatum).days)))
        moeglich = [m for m in moeglich if m[0] > 0]
        if not moeglich:
            continue
        punkte, b = moeglich[0]
        # Gibt es eine zweite, fast gleich gute Möglichkeit, ist nichts davon sicher
        if len(moeglich) > 1 and moeglich[1][0] >= punkte - 5:
            punkte = min(punkte, SICHER - 1)
        paare.append((punkte, a, b))
    paare.sort(key=lambda p: -p[0])
    vergeben: set[int] = set()
    out = []
    for punkte, a, b in paare:  # jede Buchung nur in ihrem besten Paar
        if a.id in vergeben or b.id in vergeben:
            continue
        vergeben.update((a.id, b.id))
        out.append((punkte, a, b))
    return out


def automatisch_paaren(s: Session) -> int:
    """Sichere Paare verbinden. Gibt die Zahl der neuen Paare zurück; unsichere bleiben für die Rückfrage."""
    s.flush()
    neu = 0
    for punkte, a, b in vorschlaege(s):
        if punkte >= SICHER:
            paaren(a, b)
            neu += 1
    return neu


def offene_fragen(s: Session) -> list[tuple[int, TransactionRow, TransactionRow]]:
    return [(p, a, b) for p, a, b in vorschlaege(s) if FRAGEN <= p < SICHER]
