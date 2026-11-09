"""Verschlüsselung der Datenbank (SQLCipher, AES-256): auch eine kopierte Datei lässt sich ohne den Schlüssel nicht lesen.

Der Schlüssel (64 Hexzeichen) liegt in einer eigenen Datei außerhalb von data/ (BANKPOCKET_DB_KEY_FILE, Rechte 600) –
Datenbank und Schlüssel sind so nie zusammen in einer Kopie von data/. Die tägliche Sicherung legt ihn als db.key
mit ins (passwortverschlüsselte) Archiv, damit zur Wiederherstellung das Sicherungspasswort genügt.

    python -m bankpocket.datenbank verschluesseln       einmalig: unverschlüsselte Datenbank umstellen (BankPocket vorher beenden)
    python -m bankpocket.datenbank pruefen              öffnet die Datenbank mit dem Schlüssel und nennt Tabellen und Zeilen
    python -m bankpocket.datenbank abrufe               Zahl der gerade laufenden Abrufe (für das Update-Skript)
    python -m bankpocket.datenbank klartext-loeschen    Reste unverschlüsselter Kopien überschreiben und löschen
    python -m bankpocket.datenbank verbindungen         Zustand der Bankverbindungen und Anmelde-Hinweise (ohne Umsätze)
"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

from .config import DbSchluesselFehler, Settings
from .db import _sqlcipher, ist_klartext, roh_verbinden


def _db_datei(settings: Settings) -> Path:
    url = settings.db_url or ""
    if not url.startswith("sqlite:///"):
        raise DbSchluesselFehler("Die Verschlüsselung gibt es nur für die SQLite-Datenbank.")
    return Path(url.removeprefix("sqlite:///"))


def neuer_schluessel(pfad: Path) -> str:
    pfad.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    schluessel = secrets.token_hex(32)
    fd = os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(schluessel + "\n")
    return schluessel


def _app_laeuft() -> bool:
    """Läuft BankPocket (uvicorn) auf diesem Rechner? Unter Linux über /proc."""
    ich = os.getpid()
    proc = Path("/proc")
    if not proc.exists():
        return False
    for p in proc.iterdir():
        if p.name.isdigit() and int(p.name) != ich:
            try:
                befehl = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            if "uvicorn" in befehl and "bankpocket" in befehl:
                return True
    return False


def _zaehlen(con) -> dict[str, int]:
    tabellen = [r[0] for r in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    return {t: con.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tabellen}


def verschluesseln(settings: Settings, trotzdem: bool = False) -> dict:
    """Die unverschlüsselte Datenbank in eine verschlüsselte umschreiben und prüfen, bevor sie die alte ersetzt.
    Die alte bleibt als bankpocket.db.klartext-… liegen (siehe klartext_loeschen)."""
    datei = _db_datei(settings)
    if not datei.exists():
        raise DbSchluesselFehler(f"Keine Datenbank gefunden: {datei}")
    if not ist_klartext(datei):
        return {"schon": True}
    if not settings.db_key and not settings.db_key_file:
        raise DbSchluesselFehler("Bitte BANKPOCKET_DB_KEY_FILE setzen (Pfad der Schlüsseldatei, wird bei Bedarf angelegt).")
    if _app_laeuft() and not trotzdem:
        raise DbSchluesselFehler("BankPocket läuft noch – bitte zuerst beenden.")
    if settings.db_key or Path(settings.db_key_file).exists():
        schluessel = settings.db_schluessel()
    else:
        schluessel = neuer_schluessel(Path(settings.db_key_file))
    neu = datei.with_name(datei.name + ".neu")
    neu.unlink(missing_ok=True)
    alt = _sqlcipher().connect(str(datei))  # ohne Schlüssel gelesen: eine normale SQLite-Datenbank, aber mit sqlcipher_export
    try:
        alt.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        alt.execute("ATTACH DATABASE ? AS enc KEY ?", (str(neu), f"x'{schluessel}'"))
        alt.execute("SELECT sqlcipher_export('enc')")
        alt.execute("DETACH DATABASE enc")
        vorher = _zaehlen(alt)
    finally:
        alt.close()
    pruef = roh_verbinden(neu, schluessel)
    try:
        in_ordnung = pruef.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        nachher = _zaehlen(pruef)
    finally:
        pruef.close()
    if not in_ordnung or vorher != nachher or ist_klartext(neu):
        neu.unlink(missing_ok=True)
        raise DbSchluesselFehler("Die verschlüsselte Kopie stimmt nicht mit dem Original überein – nichts geändert.")
    klartext = datei.with_name(f"{datei.name}.klartext-{datetime.now():%Y%m%d-%H%M%S}")
    os.replace(datei, klartext)
    for endung in ("-wal", "-shm"):
        rest = datei.with_name(datei.name + endung)
        if rest.exists():
            os.replace(rest, klartext.with_name(klartext.name + endung))
    os.replace(neu, datei)
    datei.chmod(0o600)
    return {"schon": False, "tabellen": len(nachher), "zeilen": sum(nachher.values()), "klartext": klartext}


def pruefen(settings: Settings) -> dict:
    datei = _db_datei(settings)
    schluessel = settings.db_schluessel()
    if not schluessel:
        raise DbSchluesselFehler("Kein Schlüssel eingestellt.")
    if ist_klartext(datei):
        raise DbSchluesselFehler("Die Datenbank ist nicht verschlüsselt.")
    con = roh_verbinden(datei, schluessel, nur_lesen=True)
    try:
        zaehlung = _zaehlen(con)
    finally:
        con.close()
    return {"tabellen": len(zaehlung), "zeilen": sum(zaehlung.values())}


def abrufe_laufen(settings: Settings) -> int:
    con = roh_verbinden(_db_datei(settings), settings.db_schluessel(), nur_lesen=True)
    try:
        return con.execute("select count(*) from connections where status=?", ("laeuft",)).fetchone()[0]
    finally:
        con.close()


ANMELDE_HINWEISE = ("freigabe_noetig", "pin_falsch", "gesperrt", "fehler", "auswahl_noetig")


def verbindungen(settings: Settings) -> list[str]:
    """Zeilen zum Zustand der Bankverbindungen und der letzten Anmelde-Hinweise – ohne Umsätze, Salden oder Konten.
    Zum Nachsehen, wann und wie oft eine Bank eine neue Anmeldung verlangt hat."""
    con = roh_verbinden(_db_datei(settings), settings.db_schluessel(), nur_lesen=True)
    zeilen = []
    try:
        for c in con.execute("select id, art, bank, status, letzte_freigabe, letzter_erfolg, letzter_versuch, "
                             "fehler_in_folge, substr(meldung, 1, 120) from connections order by id"):
            zeilen.append(f"Verbindung {c[0]} ({c[1]}/{c[2]}): Status {c[3]}, letzte Anmeldung {c[4]}, letzter Erfolg {c[5]}, "
                          f"letzter Versuch {c[6]}, Fehler in Folge {c[7]}, Meldung „{c[8]}“")
        marken = ",".join("?" for _ in ANMELDE_HINWEISE)
        for h in con.execute(f"select erstellt_am, art, titel from hinweise where art in ({marken}) "
                             "order by erstellt_am desc limit 20", ANMELDE_HINWEISE):
            zeilen.append(f"Hinweis {h[0]}: {h[1]} – {h[2]}")
    finally:
        con.close()
    return zeilen


def klartext_reste(settings: Settings) -> list[Path]:
    """Unverschlüsselte Kopien der Datenbank in data/ (aus früheren Eingriffen oder der Umstellung)."""
    datei = _db_datei(settings)
    treffer = []
    for p in sorted(datei.parent.glob(datei.name + ".*")):  # bankpocket.db.vor-…, .klartext-…, .neu
        if p.is_file() and (".klartext" in p.name or ".vor-" in p.name or ist_klartext(p)):
            treffer.append(p)
    return treffer


def _ueberschreiben_und_loeschen(pfad: Path) -> None:
    groesse = pfad.stat().st_size
    with open(pfad, "r+b") as f:
        rest = groesse
        while rest > 0:
            teil = min(rest, 1 << 20)
            f.write(b"\0" * teil)
            rest -= teil
        f.flush()
        os.fsync(f.fileno())
    pfad.unlink()


def klartext_loeschen(settings: Settings, ja: bool = False) -> list[Path]:
    reste = klartext_reste(settings)
    if not reste:
        print("Keine unverschlüsselten Kopien gefunden.")
        return []
    for p in reste:
        print(f"  {p.name}  ({p.stat().st_size // 1024} KB)")
    if not ja and input("Diese Dateien überschreiben und endgültig löschen? [j/N] ").strip().lower() not in ("j", "ja"):
        print("Nichts gelöscht.")
        return []
    for p in reste:
        _ueberschreiben_und_loeschen(p)
    print(f"{len(reste)} Datei(en) überschrieben und gelöscht.")
    return reste


def main() -> None:
    befehl = sys.argv[1] if len(sys.argv) > 1 else ""
    settings = Settings.from_env()
    try:
        if befehl == "verschluesseln":
            erg = verschluesseln(settings, trotzdem="--trotzdem" in sys.argv)
            if erg["schon"]:
                print("Die Datenbank ist schon verschlüsselt.")
            else:
                print(f"Verschlüsselt und geprüft: {erg['tabellen']} Tabellen, {erg['zeilen']} Zeilen.")
                print(f"Die alte, unverschlüsselte Datei liegt noch als {erg['klartext'].name} – nach einem Test der App mit "
                      "„python -m bankpocket.datenbank klartext-loeschen“ entfernen.")
        elif befehl == "pruefen":
            erg = pruefen(settings)
            print(f"Verschlüsselte Datenbank ist lesbar: {erg['tabellen']} Tabellen, {erg['zeilen']} Zeilen.")
        elif befehl == "abrufe":
            print(abrufe_laufen(settings))
        elif befehl == "verbindungen":
            print("\n".join(verbindungen(settings)))
        elif befehl == "klartext-loeschen":
            klartext_loeschen(settings, ja="--ja" in sys.argv)
        else:
            sys.exit(__doc__)
    except DbSchluesselFehler as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
