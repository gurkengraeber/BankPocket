"""KI-Einordnung: Einstellungen und manueller Lauf."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import fragen, ki
from ..db import KiKategorieRow
from ..service import sync_contracts
from .deps import get_ctx, get_db

router = APIRouter(prefix="/api")


class KiIn(BaseModel):
    aktiv: bool | None = None
    schluessel: str | None = Field(default=None, max_length=300)


def _stand(s: Session) -> dict:
    return {**ki.einstellungen(s), "modell": ki.MODELL, "offen": len(ki.offene_haendler(s)),
            "eingeordnet": s.scalar(select(func.count()).select_from(KiKategorieRow))}


@router.get("/ki")
def ki_stand(s: Session = Depends(get_db)):
    return _stand(s)


@router.put("/ki")
def ki_aendern(body: KiIn, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    if body.schluessel and not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", body.schluessel.strip()):
        raise HTTPException(422, "Das sieht nicht nach einem Mistral-API-Schlüssel aus.")
    ki.einstellungen_setzen(s, ctx.vault, aktiv=body.aktiv, schluessel=body.schluessel)
    s.commit()
    return _stand(s)


@router.post("/ki/einordnen")
def ki_einordnen(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    try:
        erg = ki.einordnen(ctx, s)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:  # noqa: BLE001 – verständliche Meldung statt 500
        s.rollback()
        raise HTTPException(502, ki.fehlertext(e)) from e
    if erg["eingeordnet"]:
        sync_contracts(s, ctx.today())
    s.commit()
    return {**_stand(s), "neu_eingeordnet": erg["eingeordnet"]}


class FrageIn(BaseModel):
    frage: str = Field(min_length=3, max_length=300)


@router.post("/ki/frage")
def ki_frage(body: FrageIn, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Frage in normaler Sprache: Die KI sieht nur die Frage und die Kategorienamen, gerechnet wird hier."""
    try:
        return fragen.fragen(ctx, s, body.frage)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:  # noqa: BLE001 – verständliche Meldung statt 500
        raise HTTPException(502, ki.fehlertext(e)) from e


@router.delete("/ki/ergebnisse", status_code=204)
def ki_vergessen(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    ki.vergessen(s)
    sync_contracts(s, ctx.today())
    s.commit()
