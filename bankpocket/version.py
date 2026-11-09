"""Stand der Version: die Datei VERSION neben dem Ordner bankpocket/ schreibt `scripts/veroeffentlichen.sh` mit
(Kurzform des Git-Commits). Sie fehlt bei einer Entwicklungsumgebung."""
from __future__ import annotations

from pathlib import Path

DATEI = Path(__file__).resolve().parent.parent / "VERSION"


def gelesen() -> str:
    try:
        return DATEI.read_text(encoding="utf-8").strip() or "entwicklung"
    except OSError:
        return "entwicklung"


# Stand des Codes, der gerade läuft (beim Start gelesen). Weicht `gelesen()` davon ab, ist neuer Code auf der Platte,
# der erst nach einem Neustart läuft (z. B. weil gerade ein Abruf arbeitet).
GESTARTET = gelesen()
