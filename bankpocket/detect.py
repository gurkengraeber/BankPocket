"""CLI: python -m bankpocket.detect export.csv [--json] [--today JJJJ-MM-TT]"""
from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal

from .contracts import (average_monthly_expenses, average_monthly_savings, detect_contracts,
                        summary_by_turnus)
from .csv_import import load_transactions
from .models import Contract


def _row(c: Contract) -> str:
    flag = {"aktiv": "", "ueberfaellig": f" ⚠ {c.tage_ueberfaellig} Tage überfällig",
            "inaktiv": " (inaktiv)"}[c.status]
    up = f" ↑ vorher {abs(c.vorheriger_betrag):.2f}" if c.betrag_gestiegen else ""
    return (f"{c.name[:32]:<32} {c.kategorie:<18} {c.turnus:<14} {c.erwarteter_betrag:>10.2f} "
            f"fällig {c.naechste_faelligkeit:%d.%m.%Y} [{c.methode}, {c.vorkommen}x]{flag}{up}")


def main() -> None:
    p = argparse.ArgumentParser(description="Verträge/Abos aus einem Bank-CSV-Export erkennen")
    p.add_argument("csv")
    p.add_argument("--delimiter", default=";")
    p.add_argument("--today", type=date.fromisoformat, default=None)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    txs = load_transactions(a.csv, a.delimiter)
    contracts = detect_contracts(txs, a.today)
    if a.json:
        print(json.dumps([{k: (str(v) if isinstance(v, (date, Decimal)) else v)
                           for k, v in vars(c).items() if k != "transaktionen"} for c in contracts],
                         ensure_ascii=False, indent=2))
        return
    print(f"{len(txs)} Transaktionen, {len(contracts)} Verträge erkannt\n")
    summary = summary_by_turnus(contracts)
    for title, typ in (("AUSGABEN", "ausgabe"), ("EINNAHMEN", "einnahme")):
        for turnus, s in summary[typ].items():
            print(f"== {title} – {turnus.capitalize()} ({s['anzahl']}) – {s['summe']:.2f} EUR ==")
            print("\n".join(_row(c) for c in contracts
                            if c.typ == typ and c.turnus == turnus and c.status != "inaktiv"))
            print()
    inaktiv = [c for c in contracts if c.status == "inaktiv"]
    if inaktiv:
        print("== INAKTIV ==\n" + "\n".join(_row(c) for c in inaktiv) + "\n")
    print(f"Ø Ausgaben/Monat (ohne Sparen): {average_monthly_expenses(contracts):.2f} EUR")
    print(f"Ø Sparen/Monat:                 {average_monthly_savings(contracts):.2f} EUR")


if __name__ == "__main__":
    main()
