"""Bildschirmfotos für die README aus den Demo-Daten (ohne Logos fremder Anbieter).

Vorher den Demo-Server starten (siehe README, „Erst ausprobieren“), dann:
    .venv/bin/python scripts/bildschirmfotos.py docs/bilder [http://127.0.0.1:8000]
Braucht Chromium (`chromium-browser`) und das Paket `websockets` (kommt mit uvicorn[standard]).
"""
import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets
ZIEL = sys.argv[1]
BASIS = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000"
PORT = 9333
SEITEN = [  # (Datei, Adresse, Breite, Höhe, nach unten scrollen)
    ("uebersicht.png", "/#/", 390, 844, 0),
    ("vertraege.png", "/#/vertraege", 390, 844, 0),
    ("vertrag.png", "/#/vertrag/8", 390, 844, 0),
    ("analysen.png", "/#/analysen", 390, 844, 0),
    ("pc-uebersicht.png", "/#/", 1280, 800, 0),
]
p = subprocess.Popen(["chromium-browser", "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                      f"--remote-debugging-port={PORT}", f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
async def main():
    for _ in range(40):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json")); break
        except Exception: time.sleep(0.25)
    ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
    async with websockets.connect(ws_url, max_size=50_000_000) as ws:
        nr = 0
        async def cdp(methode, **params):
            nonlocal nr; nr += 1
            await ws.send(json.dumps({"id": nr, "method": methode, "params": params}))
            while True:
                a = json.loads(await ws.recv())
                if a.get("id") == nr: return a.get("result", {})
        await cdp("Page.enable")
        await cdp("Network.enable")
        await cdp("Network.setBlockedURLs", urls=["*/api/logo/*"])  # keine Firmenlogos in den Bildern
        await cdp("Page.navigate", url=BASIS + "/"); await asyncio.sleep(2)
        await cdp("Runtime.evaluate", expression="localStorage.setItem('bp_startbildschirm_weg','1')")
        for datei, adresse, b, h, runter in SEITEN:
            await cdp("Emulation.setDeviceMetricsOverride", width=b, height=h, deviceScaleFactor=2, mobile=b < 700)
            await cdp("Page.navigate", url="about:blank"); await asyncio.sleep(0.3)
            await cdp("Page.navigate", url=BASIS + adresse); await asyncio.sleep(4)
            if runter:
                await cdp("Runtime.evaluate", expression=f"window.scrollTo(0,{runter})"); await asyncio.sleep(1)
            bild = await cdp("Page.captureScreenshot", format="png")
            open(f"{ZIEL}/{datei}", "wb").write(base64.b64decode(bild["data"]))
            print(datei, len(bild["data"]) * 3 // 4 // 1024, "kB")
try:
    asyncio.run(main())
finally:
    p.terminate()
