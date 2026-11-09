"""Passwort für die Web-App setzen:  python -m bankpocket.passwort
(im Container: docker compose exec -u bankpocket bankpocket python -m bankpocket.passwort)"""
from getpass import getpass

from .auth import passwort_setzen
from .config import Settings
from .db import make_sessionmaker


def main() -> None:
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    pw = getpass("Neues Passwort für BankPocket: ")
    if len(pw) < 10:
        raise SystemExit("Bitte mindestens 10 Zeichen verwenden.")
    if getpass("Passwort wiederholen: ") != pw:
        raise SystemExit("Die Passwörter stimmen nicht überein.")
    with make_sessionmaker(settings.db_url, settings.db_schluessel())() as s:
        passwort_setzen(s, pw)
        s.commit()
    print("Passwort gesetzt. Bestehende Anmeldungen wurden abgemeldet.")


if __name__ == "__main__":
    main()
