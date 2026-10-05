"""Deutsche Banken mit FinTS-Adresse – Suche nach BLZ, IBAN oder Name."""
from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

DATEI = Path(__file__).with_name("fints_banken.json")

# Bankgruppen für Kachel, Hinweise und Login-Bezeichnung in der Oberfläche
FAMILIEN = (
    ("dkb", ("dkb",)),  # vor Sparkasse: läuft über die Sparkassen-Server
    ("sparkasse", ("sparkasse", "landesbank", "s-fints-pt")),
    ("volksbank", ("volksbank", "raiffeisen", "vr bank", "vr-bank", "vr ", "spardabank", "sparda", "psd bank",
                   "genossenschaft", "atruvia")),
    ("comdirect", ("comdirect",)),
    ("postbank", ("postbank",)),
    ("deutsche_bank", ("deutsche bank",)),
    ("commerzbank", ("commerzbank",)),
)


@cache
def _banken() -> dict[str, tuple[str, str, str]]:
    return {blz: tuple(v) for blz, v in json.loads(DATEI.read_text(encoding="utf-8")).items()}


def familie(name: str, url: str = "") -> str:
    text = f"{name} {url}".lower()
    for fam, stichworte in FAMILIEN:
        if any(w in text for w in stichworte):
            return fam
    return "andere"


def _eintrag(blz: str) -> dict:
    name, ort, url = _banken()[blz]
    return {"blz": blz, "name": name, "ort": ort, "url": url, "familie": familie(name, url)}


def nach_blz(blz: str) -> dict | None:
    return _eintrag(blz) if blz in _banken() else None


def suche(q: str, limit: int = 20) -> list[dict]:
    q = q.strip()
    kompakt = re.sub(r"\s", "", q).upper()
    if re.fullmatch(r"DE\d{2}\d{8}\d*", kompakt):  # IBAN: Zeichen 5–12 sind die BLZ
        kompakt = kompakt[4:12]
    if re.fullmatch(r"\d{3,8}", kompakt):
        return [_eintrag(b) for b in _banken() if b.startswith(kompakt)][:limit]
    worte = q.lower().split()
    if not worte or len(q) < 2:
        return []
    treffer = [blz for blz, (name, ort, _) in _banken().items()
               if all(w in f"{name} {ort}".lower() for w in worte)]
    # Namen, die mit dem ersten Suchwort beginnen, zuerst – danach kürzere (meist genauere) Namen
    treffer.sort(key=lambda b: (not _banken()[b][0].lower().startswith(worte[0]), len(_banken()[b][0])))
    return [_eintrag(b) for b in treffer[:limit]]
