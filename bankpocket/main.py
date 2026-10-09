"""Einstiegspunkt für den Server.

    uvicorn bankpocket.main:app --host 0.0.0.0 --port 8000 --workers 1

Nur im Heimnetz bzw. über VPN erreichbar machen, nie per Portfreigabe ins Internet.
Genau EIN Worker: Abrufe und Zeitplan laufen im Prozess.
Konfiguration über Umgebungsvariablen, siehe .env.example.
"""
import logging

from .api import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("fints").setLevel(logging.WARNING)  # FinTS-Protokoll nicht ins Log (enthält Kontodaten)

app = create_app()
