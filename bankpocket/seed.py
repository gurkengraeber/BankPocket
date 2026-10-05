"""Legt die Konten ohne Bankanbindung aus dem Projekt-Brief an (nur wenn noch keine existieren).

Bankkonten, Trade Republic, Binance und Splitwise entstehen automatisch, sobald du sie in der App verbindest.

    python -m bankpocket.seed
"""
from sqlalchemy import select

from .config import Settings
from .db import Account, make_sessionmaker

KONTEN = [
    # (Quelle, Name, Typ, Gruppe) – „manuell“: Buchungen trägst du in der App ein
    ("manuell", "Bargeld", "giro", "Tägliche Konten"),
    ("paypal", "PayPal", "giro", "Tägliche Konten"),  # CSV-Import
    ("norwegian", "Norwegian Kreditkarte", "kreditkarte", "Tägliche Konten"),  # CSV-Import
    ("manuell", "Exodus + Monero", "krypto", "Crypto"),
    ("manuell", "Kautionen & Schulden", "virtuell", "Virtuell"),
]


def main() -> None:
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with make_sessionmaker(settings.db_url)() as s:
        if s.scalar(select(Account).limit(1)):
            print("Konten existieren bereits – nichts zu tun.")
            return
        for quelle, name, typ, gruppe in KONTEN:
            s.add(Account(quelle=quelle, name=name, typ=typ, gruppe=gruppe))
        s.commit()
        print(f"{len(KONTEN)} Konten angelegt.")


if __name__ == "__main__":
    main()
