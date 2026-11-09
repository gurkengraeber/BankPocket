"""Zahltag-Muster: an welchem Tag kommt das Gehalt – und wann kommt es das nächste Mal?

Arbeitgeber zahlen meist nach einem von drei Mustern:
- fester Tag (z. B. 15.), fällt er aufs Wochenende/Feiertag, kommt das Geld vorher (oder danach)
- n-letzter Bankarbeitstag (z. B. immer am letzten Bankarbeitstag des Monats)
- n-ter Bankarbeitstag (z. B. am ersten Bankarbeitstag)
"""
from __future__ import annotations

import calendar
from collections import Counter
from datetime import date, timedelta
from functools import cache

from .contracts import add_months


def _ostersonntag(jahr: int) -> date:
    a, b, c = jahr % 19, jahr // 100, jahr % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    monat, tag = divmod(h + l - 7 * m + 114, 31)
    return date(jahr, monat, tag + 1)


@cache
def _feiertage(jahr: int) -> frozenset[date]:
    """Bundesweite Feiertage plus Heiligabend und Silvester – an diesen Tagen buchen deutsche Banken nicht."""
    ostern = _ostersonntag(jahr)
    return frozenset({
        date(jahr, 1, 1), ostern - timedelta(days=2), ostern + timedelta(days=1), date(jahr, 5, 1),
        ostern + timedelta(days=39), ostern + timedelta(days=50), date(jahr, 10, 3),
        date(jahr, 12, 24), date(jahr, 12, 25), date(jahr, 12, 26), date(jahr, 12, 31),
    })


def bankarbeitstag(d: date) -> bool:
    return d.weekday() < 5 and d not in _feiertage(d.year)


def _bankarbeitstage(jahr: int, monat: int) -> list[date]:
    tage = calendar.monthrange(jahr, monat)[1]
    return [d for d in (date(jahr, monat, t) for t in range(1, tage + 1)) if bankarbeitstag(d)]


def _verschieben(d: date, rueckwaerts: bool) -> date:
    while not bankarbeitstag(d):
        d += timedelta(days=-1 if rueckwaerts else 1)
    return d


def _termin(muster: tuple, jahr: int, monat: int) -> date:
    art, wert, *rest = muster
    if art == "tag":
        return _verschieben(date(jahr, monat, min(wert, calendar.monthrange(jahr, monat)[1])), rest[0])
    tage = _bankarbeitstage(jahr, monat)
    return tage[-1 - wert] if art == "letzter" else tage[wert]


def _kandidaten(daten: list[date]) -> list[tuple]:
    tage = Counter(d.day for d in daten if bankarbeitstag(d))
    kandidaten = [("tag", t, rw) for t, _ in tage.most_common(2) for rw in (True, False)]
    for d in daten:
        arbeitstage = _bankarbeitstage(d.year, d.month)
        if d in arbeitstage:
            i = arbeitstage.index(d)
            if len(arbeitstage) - 1 - i <= 4:
                kandidaten.append(("letzter", len(arbeitstage) - 1 - i))
            if i <= 4:
                kandidaten.append(("erster", i))
    if tage and tage.most_common(1)[0][0] >= 28:  # Monatsende: „letzter Bankarbeitstag“ ist die bessere Beschreibung
        kandidaten.sort(key=lambda m: m[0] != "letzter")
    return list(dict.fromkeys(kandidaten))


def _monate_um(d: date) -> list[tuple[int, int]]:
    return [(m.year, m.month) for m in (add_months(d.replace(day=1), n) for n in (-1, 0, 1))]


def muster_erkennen(daten: list[date]) -> tuple | None:
    """Das Muster, das die meisten der letzten (bis zu sechs) Zahlungen genau trifft."""
    daten = sorted(set(daten))[-6:]
    if len(daten) < 2:
        return None
    bestes, treffer_max = None, 0
    for m in _kandidaten(daten):
        treffer = sum(1 for d in daten if any(_termin(m, j, mo) == d for j, mo in _monate_um(d)))
        if treffer > treffer_max:  # bei Gleichstand gewinnt der zuerst geprüfte Kandidat
            bestes, treffer_max = m, treffer
    return bestes if treffer_max * 2 > len(daten) else None


def naechster_zahltag(daten: list[date]) -> date | None:
    """Nächster erwarteter Zahltag nach der letzten Zahlung – oder None, wenn kein Muster erkennbar ist."""
    muster = muster_erkennen(daten)
    if not muster:
        return None
    letzte = max(daten)
    termine = sorted(_termin(muster, m.year, m.month)
                     for m in (add_months(letzte.replace(day=1), n) for n in range(0, 3)))
    return next(t for t in termine if t > letzte + timedelta(days=10))


def beschreibung(muster: tuple | None) -> str | None:
    if not muster:
        return None
    art, wert, *rest = muster
    if art == "tag":
        return (f"am {wert}. – fällt der auf ein Wochenende oder einen Feiertag, "
                f"{'schon am Bankarbeitstag davor' if rest[0] else 'erst am Bankarbeitstag danach'}")
    if art == "letzter":
        return f"am {('', 'zweit', 'dritt', 'viert', 'fünft')[wert]}letzten Bankarbeitstag"
    return f"am {('ersten', 'zweiten', 'dritten', 'vierten', 'fünften')[wert]} Bankarbeitstag"
