"""Lebensbereiche: „Was kostet meine Wohnung?“"""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import bereiche
from ..contracts import add_months
from ..db import Account, Bereich
from .deps import get_ctx, get_db
from .kategorien import alle_kategorien
from .konten import buchung_out

router = APIRouter(prefix="/api")


class BereichIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    emoji: str = Field(default="🏡", min_length=1, max_length=16)
    kategorien: list[str] = Field(default_factory=list, max_length=60)
    vertraege: list[int] = Field(default_factory=list, max_length=200)


def _finden(s: Session, bereich_id: int) -> Bereich:
    b = s.get(Bereich, bereich_id)
    if not b:
        raise HTTPException(404, "Bereich nicht gefunden")
    return b


def _setzen(b: Bereich, body: BereichIn) -> None:
    b.name, b.emoji = body.name.strip(), body.emoji.strip()
    b.kategorien = json.dumps(list(dict.fromkeys(body.kategorien)), ensure_ascii=False)
    b.vertraege = json.dumps(list(dict.fromkeys(body.vertraege)))


@router.get("/bereiche")
def liste(fenster: int = Query(bereiche.FENSTER, ge=1, le=12), s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    alle = list(s.scalars(select(Bereich).order_by(Bereich.id)))
    kategorien = alle_kategorien(s)
    summen: dict = {}  # alle Bereiche rechnen über dieselben Monate – nur einmal aus der Datenbank holen
    return {"bereiche": [{k: v for k, v in bereiche.auswertung(s, b, ctx.today(), fenster, summen).items() if k != "posten"}
                         for b in alle],
            "vorlagen": bereiche.vorlagen(s, alle, {*kategorien["ausgabe"], *kategorien["einnahme"]})}


@router.post("/bereiche", status_code=201)
def anlegen(body: BereichIn, s: Session = Depends(get_db)):
    b = Bereich()
    _setzen(b, body)
    s.add(b)
    s.commit()
    return {"id": b.id}


@router.get("/bereiche/{bereich_id}")
def detail(bereich_id: int, fenster: int = Query(bereiche.FENSTER, ge=1, le=12), s: Session = Depends(get_db),
           ctx=Depends(get_ctx)):
    return bereiche.auswertung(s, _finden(s, bereich_id), ctx.today(), fenster)


@router.put("/bereiche/{bereich_id}")
def aendern(bereich_id: int, body: BereichIn, fenster: int = Query(bereiche.FENSTER, ge=1, le=12),
            s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    b = _finden(s, bereich_id)
    _setzen(b, body)
    s.commit()
    return bereiche.auswertung(s, b, ctx.today(), fenster)


@router.delete("/bereiche/{bereich_id}", status_code=204)
def loeschen(bereich_id: int, s: Session = Depends(get_db)):
    s.delete(_finden(s, bereich_id))
    s.commit()


@router.get("/bereiche/{bereich_id}/buchungen")
def bereich_buchungen(bereich_id: int, monat: str | None = None, kategorie: str | None = None,
                      fenster: int = Query(bereiche.FENSTER, ge=1, le=12), s: Session = Depends(get_db),
                      ctx=Depends(get_ctx)):
    """Buchungen eines Monats – oder ohne Monat die des Schnitt-Zeitraums (für einen Posten)."""
    try:
        m = date.fromisoformat(f"{monat}-01") if monat else add_months(ctx.today().replace(day=1), -fenster)
    except ValueError:
        raise HTTPException(422, "Monat bitte als JJJJ-MM angeben")
    namen = dict(s.execute(select(Account.id, Account.name)).all())
    treffer = bereiche.buchungen(s, _finden(s, bereich_id), m, 1 if monat else fenster, kategorie)
    return {"buchungen": [buchung_out(t, namen.get(t.account_id)) for t in treffer]}
