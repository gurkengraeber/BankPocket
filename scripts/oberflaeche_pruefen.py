"""Öffnet jede Seite der Oberfläche mit Demo-Daten in einem Browser ohne Fenster und meldet Fehler:
Ausnahmen im Skript, Fehlermeldungen in der Konsole, fehlgeschlagene API-Aufrufe und leere Seiten.

    cd frontend && npm run build && cd ..
    .venv/bin/python scripts/oberflaeche_pruefen.py

Startet dafür selbst einen Server mit frischen Demo-Daten auf einem freien Port. Braucht Chromium
(`chromium-browser`) und das Paket `websockets` (kommt mit uvicorn[standard]). Endet mit 1, wenn etwas auffällt.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

WURZEL = Path(__file__).resolve().parent.parent
SEITEN = ["/", "/vertraege", "/vertrag/8", "/kalender", "/versicherungen", "/sparen", "/analysen", "/gehalt",
          "/budgets", "/konto/1", "/gruppe/T%C3%A4gliche%20Konten", "/konto-neu", "/verbinden", "/verbindung/1",
          "/einstellungen", "/kategorien", "/konten-sortieren", "/unklar", "/hinweise"]
GROESSEN = [(390, 844), (1280, 800)]


def freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def warte_auf(url: str, sekunden: float = 30) -> None:
    ende = time.time() + sekunden
    while time.time() < ende:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise SystemExit(f"{url} antwortet nicht")


async def pruefen(basis: str, cdp_port: int) -> list[str]:
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json"))
    ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
    probleme: list[str] = []
    async with websockets.connect(ws_url, max_size=50_000_000) as ws:
        nr, ereignisse = 0, []

        async def cdp(methode, **params):
            nonlocal nr
            nr += 1
            await ws.send(json.dumps({"id": nr, "method": methode, "params": params}))
            while True:
                a = json.loads(await ws.recv())
                if a.get("id") == nr:
                    return a.get("result", {})
                ereignisse.append(a)

        async def warten(sekunden: float):
            ende = time.time() + sekunden
            while time.time() < ende:
                try:
                    ereignisse.append(json.loads(await asyncio.wait_for(ws.recv(), ende - time.time())))
                except asyncio.TimeoutError:
                    return

        for bereich in ("Page", "Runtime", "Log", "Network"):
            await cdp(f"{bereich}.enable")
        await cdp("Network.setBlockedURLs", urls=["*/api/logo/*"])  # keine Abfragen nach Firmenlogos auslösen
        await cdp("Page.navigate", url=basis + "/")
        await warten(2)
        await cdp("Runtime.evaluate", expression="localStorage.setItem('bp_startbildschirm_weg','1')")
        for breite, hoehe in GROESSEN:
            await cdp("Emulation.setDeviceMetricsOverride", width=breite, height=hoehe, deviceScaleFactor=1,
                      mobile=breite < 700)
            for seite in SEITEN:
                await cdp("Page.navigate", url="about:blank")
                ereignisse.clear()
                await cdp("Page.navigate", url=f"{basis}/#{seite}")
                await warten(2.5)
                wo = f"{seite} ({breite} px)"
                for e in ereignisse:
                    m, p = e.get("method"), e.get("params", {})
                    if m == "Runtime.exceptionThrown":
                        d = p["exceptionDetails"]
                        probleme.append(f"{wo}: Ausnahme – {d.get('exception', {}).get('description') or d.get('text')}"[:300])
                    elif m == "Log.entryAdded" and p["entry"]["level"] == "error":
                        probleme.append(f"{wo}: Konsole – {p['entry']['text']}"[:300])
                    elif m == "Runtime.consoleAPICalled" and p["type"] == "error":
                        text = " ".join(str(a.get("value", a.get("description", ""))) for a in p["args"])
                        probleme.append(f"{wo}: Konsole – {text}"[:300])
                    elif m == "Network.responseReceived" and "/api/" in p["response"]["url"] \
                            and p["response"]["status"] >= 400:
                        probleme.append(f"{wo}: {p['response']['status']} bei {p['response']['url'].split('/api/')[1]}")
                text = (await cdp("Runtime.evaluate", expression="document.body.innerText.trim().length"))
                if text.get("result", {}).get("value", 0) < 40:
                    probleme.append(f"{wo}: Seite bleibt leer")
                breit = await cdp("Runtime.evaluate",
                                  expression="document.documentElement.scrollWidth > window.innerWidth + 2")
                if breit.get("result", {}).get("value"):
                    probleme.append(f"{wo}: Inhalt ragt seitlich über den Bildschirm")
    return probleme


def main() -> int:
    if not (WURZEL / "frontend" / "dist" / "index.html").exists():
        raise SystemExit("frontend/dist fehlt – erst „cd frontend && npm run build“")
    daten, port, cdp_port = tempfile.mkdtemp(prefix="bankpocket-demo-"), freier_port(), freier_port()
    umgebung = {**os.environ, "BANKPOCKET_DATA_DIR": daten, "BANKPOCKET_AUTH": "aus", "BANKPOCKET_SCHEDULER": "aus",
                "BANKPOCKET_FRONTEND_DIR": str(WURZEL / "frontend" / "dist")}
    subprocess.run([sys.executable, "-m", "bankpocket.demo"], cwd=WURZEL, env=umgebung, check=True,
                   stdout=subprocess.DEVNULL)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "bankpocket.main:app", "--port", str(port),
                               "--log-level", "warning"], cwd=WURZEL, env=umgebung,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = subprocess.Popen(["chromium-browser", "--headless", "--no-sandbox", "--disable-gpu",
                                f"--remote-debugging-port={cdp_port}", f"--user-data-dir={tempfile.mkdtemp()}",
                                "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        warte_auf(f"http://127.0.0.1:{port}/api/health")
        warte_auf(f"http://127.0.0.1:{cdp_port}/json")
        probleme = asyncio.run(pruefen(f"http://127.0.0.1:{port}", cdp_port))
    finally:
        browser.terminate()
        server.terminate()
    for p in dict.fromkeys(probleme):
        print("•", p)
    print(f"{len(SEITEN)} Seiten in {len(GROESSEN)} Größen geprüft – "
          + (f"{len(set(probleme))} Auffälligkeiten" if probleme else "keine Auffälligkeiten"))
    return 1 if probleme else 0


if __name__ == "__main__":
    sys.exit(main())
