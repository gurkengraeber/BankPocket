"""Erzeugt bankpocket/fints_banken.json aus der FinTS-Institutsliste von fints-institute-db (CC0).

    npm pack fints-institute-db && tar xzf fints-institute-db-*.tgz
    python scripts/bankliste_bauen.py package/fints-institutes.json

Die Liste ist schon etwas älter – bekannte Server-Umzüge werden hier korrigiert.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ZIEL = Path(__file__).resolve().parent.parent / "bankpocket" / "fints_banken.json"

# Server-Umzüge seit Erstellung der Liste (Volksbanken: Fiducia & GAD → Atruvia)
UMZUEGE = {
    "https://hbci11.fiducia.de/cgi-bin/hbciservlet": "https://fints1.atruvia.de/cgi-bin/hbciservlet",
    "https://hbci-pintan.gad.de/cgi-bin/hbciservlet": "https://fints2.atruvia.de/cgi-bin/hbciservlet",
    "https://fints.ing-diba.de/fints/": "https://fints.ing.de/fints/",
}
NAMEN = {"ING-DiBa": "ING", "Bnp Paribas S.A. Niederlassung Deutschland - Consorsbank": "Consorsbank"}


def main(quelle: str) -> None:
    eintraege = json.loads(Path(quelle).read_text(encoding="utf-8"))
    banken: dict[str, list[str]] = {}
    for e in eintraege:
        url = (e.get("pinTanURL") or "").strip()
        blz = (e.get("blz") or "").strip()
        if not url.startswith("https://") or len(blz) != 8 or blz in banken:
            continue
        name = " ".join(e["name"].split())
        banken[blz] = [NAMEN.get(name, name), (e.get("location") or "").strip(), UMZUEGE.get(url, url)]
    ZIEL.write_text(json.dumps(dict(sorted(banken.items())), ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    print(f"{len(banken)} Banken → {ZIEL}")


if __name__ == "__main__":
    main(sys.argv[1])
