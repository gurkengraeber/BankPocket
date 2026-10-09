"""Gemeinsamer Zustand der laufenden App (Datenbank, Schlüssel, Dienste)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy.orm import sessionmaker

from .config import Settings
from .notify import Notifier
from .vault import Vault


@dataclass
class AppContext:
    settings: Settings
    session_factory: sessionmaker
    vault: Vault
    notifier: Notifier
    today: Callable[[], date]
    now: Callable[[], datetime]
    source_factory: Callable[..., Any]  # FinTS
    manager: Any = None  # SyncManager
    quellen: dict[str, Callable[..., Any]] | None = None  # weitere Quellen nach Verbindungsart
    ki_client: Callable[[str], Any] | None = None  # API-Schlüssel → Anthropic-Client (in Tests ersetzbar)

    def quelle(self, art: str) -> Callable[..., Any] | None:
        if self.quellen and art in self.quellen:
            return self.quellen[art]
        return self.source_factory if art == "fints" else None
