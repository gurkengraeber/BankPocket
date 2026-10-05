"""Übersicht und Analysen."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analysen import (GEHALT_ARTEN, GEHALT_AUSGABEN, _gehaltsvertrag, budget_stand, gehalt_karte, gehalt_offen, gehalt_verlauf,
                        gehaltsmonat_buchungen, jahres_analyse, kategorien_verlauf, monats_analyse, monats_buchungen, sparen, vermoegen)
from ..db import Account, Connection, Notice
from .deps import get_ctx, get_db
from .konten import buchung_out, kontogruppen

router = APIRouter(prefix="/api")

AKTION_NOETIG = {
    "freigabe_noetig": "Freigabe nötig – tippe, um den Abruf zu starten.",
    "pin_falsch": "Anmeldung fehlgeschlagen – bitte PIN prüfen.",
    "gesperrt": "Zugang gesperrt – bitte im Online-Banking prüfen.",
    "auswahl_noetig": "Bitte TAN-Verfahren auswählen.",
}
AKTION_NOETIG_ART = {
    ("trade_republic", "freigabe_noetig"): "Anmeldung nötig – tippe, um dich neu anzumelden.",
    ("binance", "pin_falsch"): "API-Schlüssel abgelehnt – bitte prüfen.",
    ("splitwise", "pin_falsch"): "API-Schlüssel abgelehnt – bitte prüfen.",
}


@router.get("/uebersicht")
def uebersicht(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    verbindungen = list(s.scalars(select(Connection).order_by(Connection.id)))
    banner = [{"art": c.status, "titel": c.name, "link": f"#/verbindung/{c.id}",
               "text": AKTION_NOETIG_ART.get((c.art, c.status), AKTION_NOETIG[c.status])}
              for c in verbindungen if c.status in AKTION_NOETIG]
    banner += [{"art": "fehler", "titel": c.name, "text": c.meldung or "Abruf fehlgeschlagen.",
                "link": f"#/verbindung/{c.id}"} for c in verbindungen if c.status == "fehler" and c.fehler_in_folge >= 3]
    erfolge = [c.letzter_erfolg for c in verbindungen if c.letzter_erfolg]
    return {
        **kontogruppen(s),
        "gehalt": gehalt_karte(s, ctx.today()),
        "budgets": budget_stand(s, ctx.today()),
        "letzte_aktualisierung": max(erfolge) if erfolge else None,
        "verbindungen": [{"id": c.id, "name": c.name, "status": c.status,
                          "laeuft": bool((ctx.manager.live(c.id) or {}).get("laeuft"))} for c in verbindungen],
        "banner": banner,
        "hinweise_ungelesen": s.scalar(select(func.count()).select_from(Notice).where(Notice.gelesen.is_(False))),
    }


@router.get("/gehalt")
def gehalt(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Der laufende Gehaltsmonat im Detail und die Monate davor."""
    karte = gehalt_karte(s, ctx.today())
    if karte is None:
        raise HTTPException(404, "Noch kein Gehalt erkannt")
    return {**karte, "verlauf": gehalt_verlauf(s, ctx.today())}


@router.get("/gehalt/buchungen")
def gehalt_buchungen(art: str = Query(pattern=f"^({'|'.join(GEHALT_ARTEN)}|ausgaben)$"), s: Session = Depends(get_db),
                     ctx=Depends(get_ctx)):
    """Die Buchungen hinter einer Zeile – und was bis zum nächsten Gehalt noch erwartet wird."""
    karte, g = gehalt_karte(s, ctx.today()), _gehaltsvertrag(s, ctx.today())
    if karte is None:
        raise HTTPException(404, "Noch kein Gehalt erkannt")
    namen = dict(s.execute(select(Account.id, Account.name)).all())
    toepfe, offen = gehaltsmonat_buchungen(s, g.letzte_zahlung), gehalt_offen(s, g, karte["datum"], ctx.today())
    arten = GEHALT_AUSGABEN if art == "ausgaben" else (art,)  # „Ausgaben“ = Verträge, Sparen und Sonstiges zusammen
    buchungen = sorted((t for a in arten for t in toepfe[a]), key=lambda t: (t.buchungsdatum, t.id), reverse=True)
    return {"buchungen": [buchung_out(t, namen.get(t.account_id)) for t in buchungen],
            "offen": sorted((p for a in arten for p in offen.get(a, [])), key=lambda p: p["datum"])}


@router.get("/analysen/vermoegen")
def analysen_vermoegen(tage: int = Query(365, ge=30, le=3650), s: Session = Depends(get_db),
                       ctx=Depends(get_ctx)):
    return vermoegen(s, ctx.today(), tage)


@router.get("/analysen/monat")
def analysen_monat(monat: str | None = None, verlauf_bis: str | None = None, s: Session = Depends(get_db),
                   ctx=Depends(get_ctx)):
    try:
        m = date.fromisoformat(f"{monat}-01") if monat else ctx.today()
        bis = date.fromisoformat(f"{verlauf_bis}-01") if verlauf_bis else None
    except ValueError:
        raise HTTPException(422, "Monat bitte als JJJJ-MM angeben")
    return monats_analyse(s, m, bis)


@router.get("/analysen/jahr")
def analysen_jahr(jahr: int | None = Query(None, ge=1990, le=2200), s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    return jahres_analyse(s, jahr or ctx.today().year)


@router.get("/analysen/kategorien-verlauf")
def analysen_kategorien_verlauf(monate: int = Query(12, ge=3, le=36), s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    return kategorien_verlauf(s, ctx.today(), monate)


@router.get("/sparen")
def sparen_uebersicht(fenster: int = Query(6, ge=1, le=11), s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Sparquote, Sparpläne und die Konten, auf denen das Ersparte liegt."""
    gruppen = [g for g in kontogruppen(s)["gruppen"] if g["name"] in ("Sparkonten", "Crypto") and g["konten"]]
    return {**sparen(s, ctx.today(), fenster), "gruppen": gruppen, "erspartes": sum(g["summe"] for g in gruppen)}


@router.get("/analysen/buchungen")
def analysen_buchungen(monat: str | None = None, jahr: int | None = Query(None, ge=1990, le=2200),
                       art: str = Query("ausgabe", pattern="^(einnahme|ausgabe|gespart)$"),
                       kategorie: str | None = None, tag: str | None = None, empfaenger: str | None = None,
                       monate: int = Query(1, ge=1, le=24), steuern: bool = False, steuerliste: bool = False,
                       s: Session = Depends(get_db)):
    """Welche Buchungen stecken hinter einer Zahl der Monats- oder Jahresanalyse?"""
    try:
        m = date(jahr, 1, 1) if jahr else date.fromisoformat(f"{monat}-01")
    except ValueError:
        raise HTTPException(422, "Monat bitte als JJJJ-MM angeben")
    namen = dict(s.execute(select(Account.id, Account.name)).all())
    treffer = monats_buchungen(s, m, art, kategorie, tag, monate=12 if jahr else monate, steuern=steuern,
                               steuerliste=steuerliste)
    if empfaenger:
        treffer = [t for t in treffer if (t.gegenpartei or t.verwendungszweck or "Unbekannt").strip() == empfaenger]
    return {"buchungen": [buchung_out(t, namen.get(t.account_id)) for t in treffer]}
