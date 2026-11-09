from datetime import datetime, time
from zoneinfo import ZoneInfo

from bankpocket.config import parse_zeiten
from bankpocket.scheduler import Scheduler, naechster_lauf, vorheriger_lauf

TZ = ZoneInfo("Europe/Berlin")
ZEITEN = parse_zeiten("06:45,11:45,16:45,21:45")


def test_naechster_lauf_am_selben_tag():
    assert naechster_lauf(datetime(2026, 10, 1, 12, 0, tzinfo=TZ), ZEITEN) == datetime(2026, 10, 1, 16, 45, tzinfo=TZ)


def test_naechster_lauf_am_folgetag():
    assert naechster_lauf(datetime(2026, 10, 1, 22, 0, tzinfo=TZ), ZEITEN) == datetime(2026, 10, 2, 6, 45, tzinfo=TZ)


def test_genau_zur_abrufzeit_naechste_nehmen():
    assert naechster_lauf(datetime(2026, 10, 1, 6, 45, tzinfo=TZ), ZEITEN).hour == 11


def test_zeiten_parsen():
    assert parse_zeiten(" 21:45, 06:45 ") == [time(6, 45), time(21, 45)]


def test_vorheriger_lauf_und_nachholen():
    assert vorheriger_lauf(datetime(2026, 10, 1, 12, 0, tzinfo=TZ), ZEITEN) == datetime(2026, 10, 1, 11, 45, tzinfo=TZ)
    assert vorheriger_lauf(datetime(2026, 10, 1, 3, 0, tzinfo=TZ), ZEITEN) == datetime(2026, 9, 30, 21, 45, tzinfo=TZ)
    for ausgefallen, erwartet in ((True, 1), (False, 0)):
        laeufe, gefragt = [], []
        s = Scheduler(ZEITEN, "Europe/Berlin", lambda: laeufe.append(1),
                      verpasst=lambda geplant: gefragt.append(geplant) or ausgefallen, nachhol_pause=0)
        s._nachholen()
        assert len(laeufe) == erwartet and len(gefragt) == 1
