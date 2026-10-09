"""Verschlüsselte Ablage für Geheimnisse (Bank-PINs, FinTS-Sitzungsdaten).

Der Schlüssel liegt getrennt von der Datenbank in einer eigenen Datei (Standard: data/secret.key,
Rechte 600). Das schützt Datenbank-Dumps und Backups ohne Schlüsseldatei. Wer den laufenden Server
samt Schlüsseldatei übernimmt, kann entschlüsseln – deshalb Server-Festplatte zusätzlich verschlüsseln.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)


class VaultError(Exception):
    pass


class Vault:
    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    @classmethod
    def from_file(cls, path: str | Path) -> Vault:
        p = Path(path)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(Fernet.generate_key())
            log.info("Neuen Schlüssel angelegt: %s – unbedingt sichern, ohne ihn sind gespeicherte PINs verloren", p)
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o077:
            log.warning("Schlüsseldatei %s ist für andere lesbar (Rechte %o) – bitte 'chmod 600' setzen", p, mode)
        return cls(p.read_bytes().strip())

    def encrypt(self, data: bytes | str) -> str:
        if isinstance(data, str):
            data = data.encode()
        return self._fernet.encrypt(data).decode()

    def decrypt(self, token: str) -> bytes:
        try:
            return self._fernet.decrypt(token.encode())
        except InvalidToken as e:
            raise VaultError("Entschlüsselung fehlgeschlagen – falsche oder geänderte Schlüsseldatei?") from e

    def decrypt_str(self, token: str) -> str:
        return self.decrypt(token).decode()
