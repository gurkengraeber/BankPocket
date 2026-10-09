import pytest

from bankpocket.contracts import KI_KATEGORIEN, regeln_setzen


@pytest.fixture(autouse=True)
def keine_benutzerregeln():
    regeln_setzen([])
    KI_KATEGORIEN.clear()
    yield
    regeln_setzen([])
    KI_KATEGORIEN.clear()


def vertraege_bestaetigen(client) -> list[str]:
    """Erkannte Verträge sind zunächst Vorschläge – hier sagt der Nutzer zu allen „ja“."""
    vorschlaege = client.get("/api/contracts").json()["vorschlaege"]
    for v in vorschlaege:
        assert client.post(f"/api/contracts/{v['id']}/bestaetigen").json()["bestaetigt"]
    return [v["name"] for v in vorschlaege]
