"""Tägliche Sicherung: Datenbank samt Schlüsseldateien als ein Archiv, auf Wunsch verschlüsselt und in die Cloud.

- Ohne weitere Einstellung liegt jeden Tag ein Archiv in `data/backups/` (hilft bei kaputter Datenbank, nicht bei
  kaputter Festplatte).
- Mit `BANKPOCKET_BACKUP_PASSWORT` wird das Archiv verschlüsselt (AES-256, Format von `openssl enc` – lässt sich
  auch ohne BankPocket wieder öffnen).
- Mit `BANKPOCKET_BACKUP_ZIEL` (ein rclone-Ziel wie `pcloud:Backup/BankPocket` oder ein Ordner) wird es zusätzlich
  dorthin kopiert – nur verschlüsselt, nie im Klartext.

Von Hand:  python -m bankpocket.backup                      (jetzt sichern)
           python -m bankpocket.backup entschluesseln DATEI  (ergibt DATEI ohne „.enc“)
Ohne BankPocket:  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -in DATEI.enc -out DATEI
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .config import Settings
from .db import roh_verbinden

log = logging.getLogger(__name__)

RUNDEN = 600_000
TAGE_BEHALTEN = 14  # die letzten Tage lückenlos …
MONATE_BEHALTEN = 12  # … und je Monat die erste Sicherung
BEILAGEN = ("secret.key", "vapid_private.pem")  # ohne secret.key sind die gespeicherten Bank-Zugänge nicht lesbar
_PREFIX, _MAGIC = "bankpocket-", b"Salted__"


class BackupFehler(Exception):
    pass


@dataclass
class Ergebnis:
    datei: Path
    verschluesselt: bool
    hochgeladen: bool
    ziel: str = ""


def _schluessel(passwort: str, salt: bytes) -> tuple[bytes, bytes]:
    roh = PBKDF2HMAC(hashes.SHA256(), 48, salt, RUNDEN).derive(passwort.encode())
    return roh[:32], roh[32:]


def verschluesseln(daten: bytes, passwort: str) -> bytes:
    salt = os.urandom(8)
    key, iv = _schluessel(passwort, salt)
    pad = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return _MAGIC + salt + enc.update(pad.update(daten) + pad.finalize()) + enc.finalize()


def entschluesseln(daten: bytes, passwort: str) -> bytes:
    if not daten.startswith(_MAGIC):
        raise BackupFehler("Das ist keine verschlüsselte BankPocket-Sicherung.")
    key, iv = _schluessel(passwort, daten[8:16])
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    unpad = padding.PKCS7(128).unpadder()
    try:
        return unpad.update(dec.update(daten[16:]) + dec.finalize()) + unpad.finalize()
    except ValueError as e:
        raise BackupFehler("Entschlüsselung fehlgeschlagen – falsches Passwort?") from e


def _db_pfad(settings: Settings) -> Path | None:
    url = settings.db_url or ""
    return Path(url.removeprefix("sqlite:///")) if url.startswith("sqlite:///") else None


def _archiv(settings: Settings) -> bytes:
    """Datenbank (als in sich stimmige Kopie, auch während die App läuft) plus Schlüsseldateien als tar.gz."""
    db = _db_pfad(settings)
    if db is None or not db.exists():
        raise BackupFehler("Keine SQLite-Datenbank gefunden – nichts zu sichern.")
    puffer = io.BytesIO()
    with tempfile.TemporaryDirectory(dir=settings.data_dir) as tmp:
        kopie = Path(tmp) / "bankpocket.db"
        schluessel = settings.db_schluessel()  # verschlüsselte Datenbank: die Kopie ist ebenso verschlüsselt
        quelle, ziel = roh_verbinden(db, schluessel), roh_verbinden(kopie, schluessel)
        try:
            quelle.backup(ziel)
            if ziel.execute("pragma integrity_check").fetchone()[0] != "ok":
                raise BackupFehler("Die Kopie der Datenbank ist beschädigt.")
        finally:
            quelle.close()
            ziel.close()
        with tarfile.open(fileobj=puffer, mode="w:gz") as tar:
            tar.add(kopie, arcname="bankpocket.db")
            for name in BEILAGEN:
                pfad = settings.key_file if name == "secret.key" else settings.data_dir / name
                if pfad and Path(pfad).exists():
                    tar.add(pfad, arcname=name)
            if schluessel:  # zur Wiederherstellung genügt dann das Sicherungspasswort
                schluesseldatei = Path(tmp) / "db.key"
                schluesseldatei.write_text(schluessel + "\n")
                tar.add(schluesseldatei, arcname="db.key")
    return puffer.getvalue()


def _tag(datei: Path) -> date | None:
    try:
        return date.fromisoformat(datei.name[len(_PREFIX):len(_PREFIX) + 10])
    except ValueError:
        return None


def _ausmisten(ordner: Path, heute: date) -> list[str]:
    """Alte Sicherungen löschen; gibt die Namen der gelöschten zurück (für das Ziel in der Cloud)."""
    dateien = sorted((d for d in ordner.glob(f"{_PREFIX}*") if _tag(d)), key=_tag, reverse=True)
    behalten = set(dateien[:TAGE_BEHALTEN])
    monate: dict[tuple[int, int], Path] = {}
    for d in dateien:
        monate[(_tag(d).year, _tag(d).month)] = d  # absteigend sortiert: am Ende steht die früheste des Monats
    behalten |= {d for (j, m), d in monate.items() if (heute.year - j) * 12 + heute.month - m < MONATE_BEHALTEN}
    weg = [d for d in dateien if d not in behalten]
    for d in weg:
        d.unlink()
    return [d.name for d in weg]


def _hochladen(datei: Path, ziel: str, geloescht: list[str]) -> None:
    if ":" in ziel and not Path(ziel).is_absolute():  # rclone-Ziel („pcloud:Ordner“)
        if not shutil.which("rclone"):
            raise BackupFehler("rclone ist nicht installiert – ohne geht kein Hochladen in die Cloud.")
        r = subprocess.run(["rclone", "copy", str(datei), ziel], capture_output=True, text=True, timeout=600)
        if r.returncode:
            raise BackupFehler(f"Hochladen fehlgeschlagen: {r.stderr.strip()[-300:]}")
        for name in geloescht:
            subprocess.run(["rclone", "deletefile", f"{ziel.rstrip('/')}/{name}"], capture_output=True, timeout=120)
        return
    ordner = Path(ziel)
    ordner.mkdir(parents=True, exist_ok=True)
    shutil.copy2(datei, ordner / datei.name)
    for name in geloescht:
        (ordner / name).unlink(missing_ok=True)


def sichern(settings: Settings, heute: date | None = None) -> Ergebnis:
    heute = heute or date.today()
    passwort, ziel = settings.backup_passwort, settings.backup_ziel
    daten = _archiv(settings)
    ordner = settings.data_dir / "backups"
    ordner.mkdir(mode=0o700, exist_ok=True)
    for alt in ordner.glob(f"{_PREFIX}{heute.isoformat()}*"):  # erneuter Lauf am selben Tag ersetzt die Sicherung
        alt.unlink()
    datei = ordner / f"{_PREFIX}{heute.isoformat()}.tar.gz{'.enc' if passwort else ''}"
    fd = os.open(datei, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(verschluesseln(daten, passwort) if passwort else daten)
    geloescht = _ausmisten(ordner, heute)
    hochgeladen = False
    if ziel:
        if not passwort:
            raise BackupFehler("Ohne BANKPOCKET_BACKUP_PASSWORT wird nichts hochgeladen – die Sicherung wäre unverschlüsselt.")
        _hochladen(datei, ziel, geloescht)
        hochgeladen = True
    return Ergebnis(datei, bool(passwort), hochgeladen, ziel)


def stand(session) -> dict:
    from .db import kv_get
    return {"zuletzt": kv_get(session, "backup_zuletzt"), "fehler": kv_get(session, "backup_fehler") or None,
            "verschluesselt": kv_get(session, "backup_verschluesselt") == "1",
            "hochgeladen": kv_get(session, "backup_hochgeladen") == "1"}


def taeglich(ctx, erzwingen: bool = False) -> None:
    """Einmal am Tag sichern (nach dem ersten automatischen Abruf). Ein Fehler landet als Hinweis in der App."""
    from .db import kv_get, kv_set
    heute = ctx.today()
    with ctx.session_factory() as s:
        if not erzwingen and (kv_get(s, "backup_zuletzt") or "")[:10] == heute.isoformat() and not kv_get(s, "backup_fehler"):
            return
    try:
        erg, fehler = sichern(ctx.settings, heute), ""
        log.info("Sicherung geschrieben: %s%s", erg.datei.name, f" → {erg.ziel}" if erg.hochgeladen else "")
    except Exception as e:  # noqa: BLE001 – eine misslungene Sicherung darf die Abrufe nicht stören
        log.exception("Sicherung fehlgeschlagen")
        erg, fehler = None, str(e) or type(e).__name__
    with ctx.session_factory() as s:
        kv_set(s, "backup_fehler", fehler)
        if erg:
            kv_set(s, "backup_zuletzt", datetime.now().isoformat(timespec="seconds"))
            kv_set(s, "backup_verschluesselt", "1" if erg.verschluesselt else "0")
            kv_set(s, "backup_hochgeladen", "1" if erg.hochgeladen else "0")
        else:
            ctx.notifier.hinweis(s, "sicherung", "Sicherung fehlgeschlagen", fehler[:200], link="#/einstellungen",
                                 schluessel=f"sicherung|{heute}")
        s.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_env()
    if len(sys.argv) >= 3 and sys.argv[1] == "entschluesseln":
        quelle = Path(sys.argv[2])
        if not settings.backup_passwort:
            sys.exit("BANKPOCKET_BACKUP_PASSWORT ist nicht gesetzt.")
        ziel = quelle.with_suffix("") if quelle.suffix == ".enc" else quelle.with_name(quelle.name + ".tar.gz")
        ziel.write_bytes(entschluesseln(quelle.read_bytes(), settings.backup_passwort))
        ziel.chmod(0o600)
        print(f"Entschlüsselt: {ziel}  (enthält bankpocket.db und die Schlüsseldateien – nach data/ entpacken; db.key gehört an den Ort aus BANKPOCKET_DB_KEY_FILE)")
        return
    try:
        erg = sichern(settings)
    except BackupFehler as e:
        sys.exit(str(e))
    print(f"Gesichert: {erg.datei}" + (" (verschlüsselt)" if erg.verschluesselt else " (unverschlüsselt)")
          + (f", hochgeladen nach {erg.ziel}" if erg.hochgeladen else ""))


if __name__ == "__main__":
    main()
