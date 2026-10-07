"""Web-App: REST-API und Auslieferung der Oberfläche. Start siehe bankpocket/main.py."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select, update

from .auth import COOKIE, LoginBremse, pruefe_token, session_secret
from .config import Settings
from .context import AppContext
from .db import Connection, make_sessionmaker
from .fetchers.binance import BinanceSource
from .fetchers.enablebanking import EnableBankingSource
from .fetchers.fints_source import FinTSSource
from .fetchers.splitwise import SplitwiseSource
from .fetchers.trade_republic import TradeRepublicSource
from .notify import Notifier
from . import backup, ki
from .routes import analysen, budgets, kategorien, konten, system, verbindungen, vertraege
from .routes import bereiche as bereiche_routen
from .routes import ki as ki_routen
from .scheduler import Scheduler
from .sync import SyncManager
from .vault import Vault

log = logging.getLogger(__name__)
BEENDEN_WARTEN = 90  # Sekunden, die ein laufender Abruf beim Beenden noch bekommt

# Die Rückkehr von der Bank kommt als Weiterleitung von einer fremden Seite – das Session-Cookie (SameSite=Strict)
# wird dabei nicht mitgeschickt. Geschützt ist sie durch den zufälligen „state“ der laufenden Freigabe.
OEFFENTLICH = {"/api/health", "/api/auth", "/api/login", "/api/logout", "/api/enablebanking/callback"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")

# Zeitpunkte werden als lokale Serverzeit gespeichert; mit Zeitzonen-Offset ausliefern,
# damit der Browser sie richtig umrechnet – egal, in welcher Zeitzone der Server läuft.
ENCODERS_BY_TYPE[datetime] = lambda d: (d if d.tzinfo else d.astimezone()).isoformat()


STANDARD_QUELLEN = {"trade_republic": TradeRepublicSource, "binance": BinanceSource, "splitwise": SplitwiseSource,
                    "enablebanking": EnableBankingSource}


def create_app(settings: Settings | None = None, today: Callable[[], date] = date.today,
               now: Callable[[], datetime] = datetime.now, source_factory=FinTSSource,
               notifier: Notifier | None = None, quellen: dict | None = None, ki_client=None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    session_factory = make_sessionmaker(settings.db_url)
    ctx = AppContext(settings=settings, session_factory=session_factory, vault=Vault.from_file(settings.key_file),
                     notifier=notifier or Notifier(session_factory, settings.data_dir, settings.push_kontakt),
                     today=today, now=now, source_factory=source_factory,
                     quellen={**STANDARD_QUELLEN, **(quellen or {})}, ki_client=ki_client)
    ctx.manager = SyncManager(ctx)

    with session_factory() as s:
        kategorien.regeln_laden(s)
        ki.laden(s)
    with session_factory() as s:  # nach einem Neustart hängengebliebene Abrufe freigeben
        s.execute(update(Connection).where(Connection.status == "laeuft")
                  .values(status="fehler", meldung="Abruf wurde durch einen Neustart unterbrochen."))
        s.commit()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.scheduler:
            def lauf() -> None:
                try:
                    ctx.manager.automatisch_abrufen()
                finally:
                    backup.taeglich(ctx)  # einmal am Tag, nach dem ersten Abruf

            def verpasst(geplant) -> bool:
                """Seit der letzten geplanten Zeit hat keine Verbindung einen Abruf versucht."""
                with session_factory() as s:
                    letzter = s.scalar(select(func.max(Connection.letzter_versuch)))
                    hat_verbindungen = s.scalar(select(func.count()).select_from(Connection))
                return bool(hat_verbindungen) and (letzter is None or letzter < geplant.replace(tzinfo=None))

            app.state.scheduler = Scheduler(settings.abrufzeiten, settings.zeitzone, lauf, verpasst=verpasst)
            app.state.scheduler.start()
        yield
        if app.state.scheduler:
            app.state.scheduler.stop()
        # Laufende Abrufe (eine Anmeldung, auf deren Freigabe gewartet wird) nicht mitten im Schritt abreißen
        if ctx.manager.laufende():
            log.info("Beenden: warte auf laufende Abrufe %s (höchstens %s s)", ctx.manager.laufende(), BEENDEN_WARTEN)
            await asyncio.to_thread(ctx.manager.warte_auf_ende, BEENDEN_WARTEN)

    app = FastAPI(title="BankPocket", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json",
                  redoc_url=None)
    app.state.ctx = ctx
    app.state.login_bremse = LoginBremse()
    app.state.scheduler = None

    @app.middleware("http")
    async def sicherheit(request: Request, call_next):
        pfad = request.url.path
        if settings.auth and pfad.startswith("/api/") and pfad not in OEFFENTLICH:
            with session_factory() as s:
                ok = pruefe_token(session_secret(s), request.cookies.get(COOKIE))
            if not ok:
                return JSONResponse({"detail": "Nicht angemeldet"}, status_code=401)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if not pfad.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        if pfad.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for modul in (system, konten, vertraege, verbindungen, analysen, budgets, kategorien, ki_routen, bereiche_routen):
        app.include_router(modul.router)

    dist = Path(settings.frontend_dir) if settings.frontend_dir else None
    if dist and (dist / "index.html").is_file():
        basis = dist.resolve()

        @app.get("/{pfad:path}", include_in_schema=False)
        def frontend(pfad: str):
            if pfad.startswith("api/"):
                raise HTTPException(404, "Nicht gefunden")
            datei = (basis / pfad).resolve()
            if pfad and datei.is_file() and basis in datei.parents:
                # gehashte Assets dürfen lange gecacht werden, alles andere immer frisch laden
                cache = "public, max-age=31536000, immutable" if pfad.startswith("assets/") else "no-cache"
                return FileResponse(datei, headers={"Cache-Control": cache})
            return FileResponse(basis / "index.html", headers={"Cache-Control": "no-cache"})

    return app
