"""Hinweise in der App + Web-Push aufs Handy.

Web-Push-Inhalte sind Ende-zu-Ende verschlüsselt (RFC 8291): der Push-Dienst des Browsers
(bei Chrome: Google) sieht nur, dass eine Nachricht kommt, nicht ihren Inhalt.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .db import Notice, PushSubscription

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, session_factory: sessionmaker, data_dir: Path, kontakt: str,
                 sender: Callable | None = None, asynchron: bool = True):
        self.session_factory = session_factory
        self.key_path = Path(data_dir) / "vapid_private.pem"
        self.kontakt = kontakt
        self._sender = sender or self._webpush
        self.asynchron = asynchron
        self._public_key: str | None = None
        self._lock = threading.Lock()

    def public_key(self) -> str:
        """Öffentlicher VAPID-Schlüssel für die Push-Anmeldung im Browser (wird beim ersten Aufruf erzeugt)."""
        with self._lock:
            if self._public_key is None:
                from cryptography.hazmat.primitives import serialization
                from py_vapid import Vapid

                if not self.key_path.exists():
                    self.key_path.parent.mkdir(parents=True, exist_ok=True)
                    v = Vapid()
                    v.generate_keys()
                    v.save_key(str(self.key_path))
                    os.chmod(self.key_path, 0o600)
                v = Vapid.from_file(str(self.key_path))
                raw = v.public_key.public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint)
                self._public_key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            return self._public_key

    def hinweis(self, session: Session, art: str, titel: str, text: str = "", link: str = "",
                schluessel: str | None = None, push: bool = True) -> Notice | None:
        """Hinweis anlegen (höchstens einmal pro Schlüssel) und optional als Push senden."""
        if schluessel and session.scalar(select(Notice.id).where(Notice.schluessel == schluessel)):
            return None
        n = Notice(art=art, titel=titel, text=text, link=link, schluessel=schluessel)
        session.add(n)
        session.flush()
        if push:
            self.push({"titel": titel, "text": text, "link": link, "tag": f"{art}-{n.id}"})
        return n

    def push(self, payload: dict) -> None:
        if self.asynchron:  # Netzwerk nicht im Request/DB-Transaktion blockieren
            threading.Thread(target=self._push_alle, args=(payload,), daemon=True).start()
        else:
            self._push_alle(payload)

    def _push_alle(self, payload: dict) -> int:
        gesendet = 0
        try:
            self.public_key()
        except Exception:  # noqa: BLE001
            log.exception("VAPID-Schlüssel nicht verfügbar")
            return 0
        with self.session_factory() as s:
            for abo in s.scalars(select(PushSubscription)).all():
                try:
                    self._sender(abo, payload)
                    gesendet += 1
                except Exception as e:  # noqa: BLE001
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    if status in (404, 410):  # Abo im Browser abgelaufen/entfernt
                        s.delete(abo)
                    else:
                        log.warning("Push fehlgeschlagen: %s", e)
            s.commit()
        return gesendet

    def _webpush(self, abo: PushSubscription, payload: dict) -> None:
        from pywebpush import webpush

        webpush(
            subscription_info={"endpoint": abo.endpoint, "keys": {"p256dh": abo.p256dh, "auth": abo.auth}},
            data=json.dumps(payload),
            vapid_private_key=str(self.key_path),
            vapid_claims={"sub": self.kontakt},
            ttl=24 * 3600,
        )
