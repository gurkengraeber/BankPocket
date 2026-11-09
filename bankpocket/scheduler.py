"""Zeitplan für automatische Abrufe (Standard 4× täglich, siehe BANKPOCKET_ABRUFZEITEN)."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)


def naechster_lauf(jetzt: datetime, zeiten: list[time]) -> datetime:
    for z in sorted(zeiten):
        kandidat = jetzt.replace(hour=z.hour, minute=z.minute, second=0, microsecond=0)
        if kandidat > jetzt:
            return kandidat
    morgen = jetzt + timedelta(days=1)
    z = min(zeiten)
    return morgen.replace(hour=z.hour, minute=z.minute, second=0, microsecond=0)


def vorheriger_lauf(jetzt: datetime, zeiten: list[time]) -> datetime:
    """Die letzte geplante Abrufzeit vor jetzt."""
    for z in sorted(zeiten, reverse=True):
        kandidat = jetzt.replace(hour=z.hour, minute=z.minute, second=0, microsecond=0)
        if kandidat <= jetzt:
            return kandidat
    gestern = jetzt - timedelta(days=1)
    z = max(zeiten)
    return gestern.replace(hour=z.hour, minute=z.minute, second=0, microsecond=0)


class Scheduler:
    def __init__(self, zeiten: list[time], zeitzone: str, job: Callable[[], None],
                 verpasst: Callable[[datetime], bool] | None = None, nachhol_pause: float = 60):
        """verpasst(letzte geplante Zeit) → True, wenn dieser Lauf ausgefallen ist (Server war aus): Dann wird er
        kurz nach dem Start nachgeholt."""
        if not zeiten:
            raise ValueError("Mindestens eine Abrufzeit nötig")
        self.zeiten, self.tz, self.job = zeiten, ZoneInfo(zeitzone), job
        self.verpasst, self.nachhol_pause = verpasst, nachhol_pause
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.naechster: datetime | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._schleife, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _nachholen(self) -> None:
        if self.verpasst is None:
            return
        try:
            geplant = vorheriger_lauf(datetime.now(self.tz), self.zeiten)
            if not self.verpasst(geplant):
                return
            log.info("Abruf von %s ist ausgefallen – wird nachgeholt", geplant.strftime("%d.%m. %H:%M"))
            if not self._stop.wait(self.nachhol_pause):  # erst das Netz und die App hochkommen lassen
                self.job()
        except Exception:  # noqa: BLE001 – der Zeitplan läuft immer weiter
            log.exception("Nachgeholter Abruf fehlgeschlagen")

    def _schleife(self) -> None:
        self._nachholen()
        while not self._stop.is_set():
            jetzt = datetime.now(self.tz)
            self.naechster = naechster_lauf(jetzt, self.zeiten)
            log.info("Nächster automatischer Abruf: %s", self.naechster.strftime("%d.%m. %H:%M"))
            # in Etappen warten, damit Uhrzeitsprünge (Sommerzeit, Standby) nicht zu Verspätung führen
            while not self._stop.is_set():
                rest = (self.naechster - datetime.now(self.tz)).total_seconds()
                if rest <= 0:
                    break
                self._stop.wait(min(rest, 300))
            if self._stop.is_set():
                return
            try:
                self.job()
            except Exception:  # noqa: BLE001 – der Zeitplan läuft immer weiter
                log.exception("Automatischer Abruf fehlgeschlagen")
