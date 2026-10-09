"""Verschlüsselte Datenbank (SQLCipher): Öffnen, Umstellen, Sicherung, Aufräumen – mit erfundenen Beispieldaten."""
import tarfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlcipher3.dbapi2")

from bankpocket import backup, datenbank
from bankpocket.api import create_app
from bankpocket.config import DbSchluesselFehler, Settings
from bankpocket.db import Account, Connection, ist_klartext, make_sessionmaker


def _plain(tmp_path, **kw) -> Settings:
    """Eine unverschlüsselte Datenbank mit einem Konto, noch ohne Schlüssel."""
    settings = Settings(data_dir=tmp_path / "data", **kw)
    settings.data_dir.mkdir()
    with make_sessionmaker(settings.db_url)() as s:
        s.add(Account(name="Girokonto", quelle="ing", typ="giro", gruppe="Tägliche Konten"))
        s.commit()
    settings.key_file.write_text("geheim")
    return settings


def test_verschluesselte_datenbank_ist_ohne_schluessel_nicht_lesbar(tmp_path):
    schluessel = datenbank.neuer_schluessel(tmp_path / "schluessel" / "db.key")
    assert (tmp_path / "schluessel" / "db.key").stat().st_mode & 0o077 == 0
    url = f"sqlite:///{tmp_path}/v.db"
    with make_sessionmaker(url, schluessel)() as s:
        s.add(Account(name="Girokonto", quelle="ing", typ="giro", gruppe="Tägliche Konten"))
        s.commit()
    assert not ist_klartext(tmp_path / "v.db") and b"Girokonto" not in (tmp_path / "v.db").read_bytes()
    with make_sessionmaker(url, schluessel)() as s:
        assert s.get(Account, 1).name == "Girokonto"
    with pytest.raises(DbSchluesselFehler, match="kein Schlüssel"):
        make_sessionmaker(url)
    with pytest.raises(DbSchluesselFehler, match="passt nicht"):
        make_sessionmaker(url, "0" * 64)


def test_unverschluesselte_datenbank_mit_schluessel_verweist_auf_die_umstellung(tmp_path):
    settings = _plain(tmp_path)
    with pytest.raises(DbSchluesselFehler, match="noch nicht verschlüsselt"):
        make_sessionmaker(settings.db_url, "ab" * 32)


def test_schluessel_muss_aus_64_hexzeichen_bestehen(tmp_path):
    assert Settings(data_dir=tmp_path, db_key="zu kurz").db_key_file is None
    with pytest.raises(DbSchluesselFehler, match="64 Hexzeichen"):
        Settings(data_dir=tmp_path, db_key="zu kurz").db_schluessel()
    with pytest.raises(DbSchluesselFehler, match="fehlt"):
        Settings(data_dir=tmp_path, db_key_file=tmp_path / "gibt-es-nicht").db_schluessel()
    assert Settings(data_dir=tmp_path).db_schluessel() is None


def test_umstellen_prueft_und_laesst_das_original_als_klartext_liegen(tmp_path):
    settings = _plain(tmp_path, db_key_file=tmp_path / "schluessel" / "db.key")
    erg = datenbank.verschluesseln(settings, trotzdem=True)
    assert not erg["schon"] and erg["tabellen"] > 5 and erg["zeilen"] >= 1
    datei = settings.data_dir / "bankpocket.db"
    assert not ist_klartext(datei) and b"Girokonto" not in datei.read_bytes()
    assert ist_klartext(erg["klartext"]) and b"Girokonto" in erg["klartext"].read_bytes()
    assert (tmp_path / "schluessel" / "db.key").exists() and datei.stat().st_mode & 0o077 == 0
    # die App öffnet sie mit dem Schlüssel, ein zweiter Lauf ändert nichts
    with make_sessionmaker(settings.db_url, settings.db_schluessel())() as s:
        assert s.get(Account, 1).name == "Girokonto"
    assert datenbank.verschluesseln(settings, trotzdem=True) == {"schon": True}
    assert datenbank.pruefen(settings)["zeilen"] == erg["zeilen"]
    # die Reste werden gefunden, überschrieben und gelöscht – die verschlüsselte Datenbank bleibt
    (settings.data_dir / "bankpocket.db.vor-test").write_bytes(b"irgendwas")
    assert {p.name for p in datenbank.klartext_reste(settings)} == {erg["klartext"].name, "bankpocket.db.vor-test"}
    datenbank.klartext_loeschen(settings, ja=True)
    assert datenbank.klartext_reste(settings) == [] and datei.exists()
    assert datenbank.pruefen(settings)["zeilen"] == erg["zeilen"]


def test_laufende_abrufe_werden_aus_der_verschluesselten_datenbank_gezaehlt(tmp_path):
    settings = _plain(tmp_path, db_key_file=tmp_path / "db.key")
    datenbank.verschluesseln(settings, trotzdem=True)
    assert datenbank.abrufe_laufen(settings) == 0
    with make_sessionmaker(settings.db_url, settings.db_schluessel())() as s:
        s.add(Connection(art="fints", bank="ing", name="ING", blz="", server_url="", status="laeuft", login_enc="x", pin_enc="y"))
        s.commit()
    assert datenbank.abrufe_laufen(settings) == 1


def test_sicherung_der_verschluesselten_datenbank_enthaelt_den_schluessel(tmp_path):
    settings = _plain(tmp_path, db_key_file=tmp_path / "schluessel" / "db.key", backup_passwort="sehr geheim")
    datenbank.verschluesseln(settings, trotzdem=True)
    erg = backup.sichern(settings, date(2026, 10, 9))
    assert b"SQLite format" not in erg.datei.read_bytes()
    archiv = tmp_path / "zurueck.tar.gz"
    archiv.write_bytes(backup.entschluesseln(erg.datei.read_bytes(), "sehr geheim"))
    with tarfile.open(archiv) as tar:
        assert set(tar.getnames()) == {"bankpocket.db", "secret.key", "db.key"}
        tar.extractall(tmp_path / "zurueck", filter="data")
    kopie, schluessel = tmp_path / "zurueck" / "bankpocket.db", (tmp_path / "zurueck" / "db.key").read_text().strip()
    assert not ist_klartext(kopie)
    with make_sessionmaker(f"sqlite:///{kopie}", schluessel)() as s:
        assert s.get(Account, 1).name == "Girokonto"


def test_app_laeuft_mit_verschluesselter_datenbank(tmp_path):
    schluessel_datei = tmp_path / "schluessel" / "db.key"
    datenbank.neuer_schluessel(schluessel_datei)
    settings = Settings(data_dir=tmp_path / "data", auth=False, scheduler=False, db_key_file=schluessel_datei)
    client = TestClient(create_app(settings))
    r = client.post("/api/accounts", json={"name": "Girokonto", "quelle": "manuell", "typ": "giro", "gruppe": "Tägliche Konten"})
    assert r.status_code == 201
    assert [k["name"] for g in client.get("/api/accounts").json()["gruppen"] for k in g["konten"]] == ["Girokonto"]
    assert b"Girokonto" not in (settings.data_dir / "bankpocket.db").read_bytes()


def test_verbindungsdiagnose_zeigt_nur_anmeldezustand(tmp_path):
    from bankpocket.db import Notice
    settings = _plain(tmp_path, db_key_file=tmp_path / "db.key")
    datenbank.verschluesseln(settings, trotzdem=True)
    with make_sessionmaker(settings.db_url, settings.db_schluessel())() as s:
        s.add(Connection(art="trade_republic", bank="trade_republic", name="Trade Republic", blz="", server_url="",
                         status="freigabe_noetig", meldung="Die Anmeldung ist abgelaufen", login_enc="x", pin_enc="y"))
        s.add(Notice(art="freigabe_noetig", titel="Trade Republic: Abruf pausiert"))
        s.add(Notice(art="neuer_vertrag", titel="Ist Streamflix ein Vertrag?"))
        s.commit()
    text = "\n".join(datenbank.verbindungen(settings))
    assert "trade_republic/trade_republic" in text and "freigabe_noetig" in text and "Abruf pausiert" in text
    assert "Streamflix" not in text and "Girokonto" not in text
