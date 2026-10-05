from datetime import datetime, time
from zoneinfo import ZoneInfo

from bankpocket.config import parse_zeiten
from bankpocket.scheduler import naechster_lauf

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
