import shutil
import subprocess
import tarfile
from datetime import date, timedelta

import pytest

from bankpocket import backup
from bankpocket.config import Settings
from bankpocket.db import Account, make_sessionmaker


def _settings(tmp_path, **kw):
    settings = Settings(data_dir=tmp_path / "data", **kw)
    settings.data_dir.mkdir()
    with make_sessionmaker(settings.db_url)() as s:
        s.add(Account(name="Girokonto", quelle="ing", typ="giro", gruppe="Tägliche Konten"))
        s.commit()
    settings.key_file.write_text("geheim")
    return settings


def test_unverschluesselt_bleibt_auf_dem_server(tmp_path):
    settings = _settings(tmp_path)
    erg = backup.sichern(settings, date(2026, 10, 4))
    assert (erg.verschluesselt, erg.hochgeladen) == (False, False)
    with tarfile.open(erg.datei) as tar:
        assert set(tar.getnames()) == {"bankpocket.db", "secret.key"}
    # ohne Passwort wird nie hochgeladen
    settings.backup_ziel = str(tmp_path / "cloud")
    with pytest.raises(backup.BackupFehler):
        backup.sichern(settings, date(2026, 10, 4))
    assert not (tmp_path / "cloud").exists()


def test_verschluesselt_hochladen_und_wiederherstellen(tmp_path):
    ziel = tmp_path / "cloud"
    settings = _settings(tmp_path, backup_passwort="sehr geheim", backup_ziel=str(ziel))
    erg = backup.sichern(settings, date(2026, 10, 4))
    kopie = ziel / erg.datei.name
    assert erg.verschluesselt and erg.hochgeladen and kopie.name == "bankpocket-2026-10-04.tar.gz.enc"
    assert b"SQLite format" not in kopie.read_bytes()
    with pytest.raises(backup.BackupFehler):
        backup.entschluesseln(kopie.read_bytes(), "falsch")
    archiv = tmp_path / "zurueck.tar.gz"
    archiv.write_bytes(backup.entschluesseln(kopie.read_bytes(), "sehr geheim"))
    with tarfile.open(archiv) as tar:
        tar.extractall(tmp_path / "zurueck", filter="data")
    with make_sessionmaker(f"sqlite:///{tmp_path}/zurueck/bankpocket.db")() as s:
        assert s.get(Account, 1).name == "Girokonto"
    assert (tmp_path / "zurueck" / "secret.key").read_text() == "geheim"


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl fehlt")
def test_laesst_sich_ohne_bankpocket_mit_openssl_oeffnen(tmp_path):
    settings = _settings(tmp_path, backup_passwort="sehr geheim")
    erg = backup.sichern(settings, date(2026, 10, 4))
    aus = tmp_path / "aus.tar.gz"
    subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", str(backup.RUNDEN), "-md", "sha256",
                    "-in", str(erg.datei), "-out", str(aus), "-pass", "pass:sehr geheim"], check=True)
    with tarfile.open(aus) as tar:
        assert "bankpocket.db" in tar.getnames()


def test_alte_sicherungen_werden_ausgemistet(tmp_path):
    ziel = tmp_path / "cloud"
    settings = _settings(tmp_path, backup_passwort="x", backup_ziel=str(ziel))
    start = date(2026, 7, 1)
    for n in range(100):
        backup.sichern(settings, start + timedelta(days=n))
    namen = sorted(d.name[11:21] for d in ziel.iterdir())
    # die letzten 14 Tage lückenlos, davor je Monat die erste
    assert namen[:3] == ["2026-07-01", "2026-08-01", "2026-09-01"] and len(namen) == 3 + 14
    assert namen[-1] == "2026-10-08" and sorted(d.name for d in (settings.data_dir / "backups").iterdir()) == sorted(
        d.name for d in ziel.iterdir())
