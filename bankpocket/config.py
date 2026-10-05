"""Konfiguration über Umgebungsvariablen (siehe .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

STANDARD_ABRUFZEITEN = "06:45,11:45,16:45,21:45"


def parse_zeiten(text: str) -> list[time]:
    zeiten = []
    for teil in text.split(","):
        if teil.strip():
            h, m = teil.strip().split(":")
            zeiten.append(time(int(h), int(m)))
    return sorted(zeiten)


@dataclass
class Settings:
    data_dir: Path = Path("data")
    db_url: str | None = None
    key_file: Path | None = None
    fints_product_id: str = ""
    abrufzeiten: list[time] = field(default_factory=lambda: parse_zeiten(STANDARD_ABRUFZEITEN))
    zeitzone: str = "Europe/Berlin"
    push_kontakt: str = "mailto:admin@localhost"
    auth: bool = True  # Login für die Web-App
    scheduler: bool = True  # automatische Abrufe
    frontend_dir: Path | None = None
    backup_passwort: str = ""  # verschlüsselt die tägliche Sicherung
    backup_ziel: str = ""  # rclone-Ziel oder Ordner für die verschlüsselte Sicherung

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        if self.db_url is None:
            self.db_url = f"sqlite:///{self.data_dir / 'bankpocket.db'}"
        if self.key_file is None:
            self.key_file = self.data_dir / "secret.key"
        if self.frontend_dir is None:
            self.frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ.get
        key_file = env("BANKPOCKET_KEY_FILE")
        frontend = env("BANKPOCKET_FRONTEND_DIR")
        return cls(
            data_dir=Path(env("BANKPOCKET_DATA_DIR", "data")),
            db_url=env("BANKPOCKET_DB_URL") or None,
            key_file=Path(key_file) if key_file else None,
            fints_product_id=env("BANKPOCKET_FINTS_PRODUCT_ID", "").strip(),
            abrufzeiten=parse_zeiten(env("BANKPOCKET_ABRUFZEITEN", STANDARD_ABRUFZEITEN)),
            zeitzone=env("TZ", "Europe/Berlin"),
            push_kontakt=env("BANKPOCKET_PUSH_KONTAKT", "mailto:admin@localhost"),
            auth=env("BANKPOCKET_AUTH", "an").lower() != "aus",
            scheduler=env("BANKPOCKET_SCHEDULER", "an").lower() != "aus",
            frontend_dir=Path(frontend) if frontend else None,
            backup_passwort=env("BANKPOCKET_BACKUP_PASSWORT", ""),
            backup_ziel=env("BANKPOCKET_BACKUP_ZIEL", "").strip(),
        )
