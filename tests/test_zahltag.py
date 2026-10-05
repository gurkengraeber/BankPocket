from datetime import date

from bankpocket.zahltag import bankarbeitstag, beschreibung, muster_erkennen, naechster_zahltag


def test_feiertage_und_wochenende():
    assert not bankarbeitstag(date(2026, 4, 3))  # Karfreitag
    assert not bankarbeitstag(date(2026, 12, 31))  # Silvester
    assert not bankarbeitstag(date(2026, 10, 3))  # Tag der Deutschen Einheit (Samstag)
    assert bankarbeitstag(date(2026, 10, 2))


def test_letzter_bankarbeitstag():
    daten = [date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)]
    assert muster_erkennen(daten) == ("letzter", 0)
    assert beschreibung(("letzter", 0)) == "am letzten Bankarbeitstag"
    assert naechster_zahltag(daten) == date(2026, 10, 30)  # 31.10. ist ein Samstag
    assert naechster_zahltag(daten + [date(2026, 10, 30), date(2026, 11, 30)]) == date(2026, 12, 30)  # Silvester


def test_fester_tag_mit_verschiebung():
    daten = [date(2026, 6, 15), date(2026, 7, 15), date(2026, 8, 14), date(2026, 9, 15)]  # 15.08. = Samstag
    assert muster_erkennen(daten) == ("tag", 15, True)
    assert naechster_zahltag(daten) == date(2026, 10, 15)
    # Erster des Monats, am Wochenende erst danach – und über den Monatswechsel hinweg
    daten = [date(2026, 7, 1), date(2026, 8, 3), date(2026, 9, 1), date(2026, 10, 1)]
    assert muster_erkennen(daten) == ("tag", 1, False)
    assert naechster_zahltag(daten) == date(2026, 11, 2)


def test_kein_muster():
    assert naechster_zahltag([date(2026, 9, 3)]) is None
    assert muster_erkennen([date(2026, 7, 3), date(2026, 8, 19), date(2026, 9, 9)]) is None
