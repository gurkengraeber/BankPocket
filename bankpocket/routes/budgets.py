"""Budgets je Kategorie und Monat."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysen import budget_stand
from ..contracts import NICHT_AUSGABEN
from ..db import Budget
from .deps import get_ctx, get_db
from .kategorien import alle_kategorien

router = APIRouter(prefix="/api")


class BudgetIn(BaseModel):
    kategorie: str
    limit: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class BudgetPatch(BaseModel):
    limit: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


def _kategorien(s: Session) -> list[str]:
    return [k for k in alle_kategorien(s)["ausgabe"] if k not in NICHT_AUSGABEN]


@router.get("/budgets")
def budgets(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    heute = ctx.today()
    liste = budget_stand(s, heute)
    vergeben = {b["kategorie"] for b in liste}
    return {"monat": heute.strftime("%Y-%m"), "budgets": liste,
            "kategorien": [k for k in _kategorien(s) if k not in vergeben]}


@router.post("/budgets", status_code=201)
def budget_anlegen(body: BudgetIn, s: Session = Depends(get_db)):
    if body.kategorie not in _kategorien(s):
        raise HTTPException(422, "Unbekannte Kategorie.")
    if s.scalar(select(Budget).where(Budget.kategorie == body.kategorie)):
        raise HTTPException(409, "Für diese Kategorie gibt es schon ein Budget.")
    b = Budget(kategorie=body.kategorie, limit=body.limit)
    s.add(b)
    s.commit()
    return {"id": b.id}


@router.patch("/budgets/{budget_id}")
def budget_aendern(budget_id: int, body: BudgetPatch, s: Session = Depends(get_db)):
    b = s.get(Budget, budget_id)
    if not b:
        raise HTTPException(404, "Budget nicht gefunden")
    b.limit = body.limit
    s.commit()
    return {"ok": True}


@router.delete("/budgets/{budget_id}", status_code=204)
def budget_loeschen(budget_id: int, s: Session = Depends(get_db)):
    b = s.get(Budget, budget_id)
    if not b:
        raise HTTPException(404, "Budget nicht gefunden")
    s.delete(b)
    s.commit()
