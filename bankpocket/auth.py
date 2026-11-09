"""Login für die Web-App: Passwort (scrypt) + signiertes Session-Cookie."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time

from sqlalchemy.orm import Session

from .db import kv_get, kv_set

COOKIE = "bp_session"
SESSION_TAGE = 180
MAX_FEHLVERSUCHE = 5
SPERRE_SEKUNDEN = 300


def hash_passwort(passwort: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(passwort.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def pruefe_passwort(passwort: str, gespeichert: str | None) -> bool:
    try:
        _, salt, dk = (gespeichert or "").split("$")
        neu = hashlib.scrypt(passwort.encode(), salt=base64.b64decode(salt), n=2**15, r=8, p=1,
                             maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(neu, base64.b64decode(dk))
    except ValueError:
        return False


def passwort_setzen(s: Session, passwort: str) -> None:
    kv_set(s, "passwort_hash", hash_passwort(passwort))
    kv_set(s, "session_secret", secrets.token_hex(32))  # meldet alle bisherigen Sitzungen ab


def session_secret(s: Session) -> bytes:
    secret = kv_get(s, "session_secret")
    if not secret:
        secret = secrets.token_hex(32)
        kv_set(s, "session_secret", secret)
        s.commit()
    return secret.encode()


def erzeuge_token(secret: bytes, jetzt: float | None = None) -> str:
    ablauf = int(jetzt if jetzt is not None else time.time()) + SESSION_TAGE * 86400
    nachricht = f"{ablauf}.{secrets.token_hex(8)}"
    return nachricht + "." + hmac.new(secret, nachricht.encode(), hashlib.sha256).hexdigest()


def pruefe_token(secret: bytes, token: str | None, jetzt: float | None = None) -> bool:
    try:
        ablauf, zufall, signatur = (token or "").split(".")
        erwartet = hmac.new(secret, f"{ablauf}.{zufall}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signatur, erwartet) and int(ablauf) > (jetzt or time.time())
    except ValueError:
        return False


class LoginBremse:
    """Nach 5 Fehlversuchen 5 Minuten Pause."""

    def __init__(self):
        self._fehler: list[float] = []
        self._lock = threading.Lock()

    def gesperrt(self) -> bool:
        with self._lock:
            grenze = time.time() - SPERRE_SEKUNDEN
            self._fehler = [t for t in self._fehler if t > grenze]
            return len(self._fehler) >= MAX_FEHLVERSUCHE

    def fehlversuch(self) -> None:
        with self._lock:
            self._fehler.append(time.time())

    def erfolg(self) -> None:
        with self._lock:
            self._fehler.clear()
