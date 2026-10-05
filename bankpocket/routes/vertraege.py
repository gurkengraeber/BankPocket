"""Verträge und Abos."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..contracts import (NICHT_AUSGABEN, TURNI, add_months, average_monthly_expenses, average_monthly_savings, muster_aus_name,
                         naechster_termin, summary_by_turnus)
from .. import logos
from ..db import Account, ContractRow, TransactionRow
from ..service import contract_status, kuendigung, pruefe_kuendigungen, sync_contracts
from .deps import get_ctx, get_db

router = APIRouter(prefix="/api")

Turnus = Literal["woechentlich", "zweiwoechentlich", "halbmonatlich", "vierwoechentlich", "monatlich", "quartalsweise", "halbjaehrlich", "jaehrlich"]


class ContractIn(BaseModel):
    name: str
    kategorie: str
    turnus: Turnus
    betrag: Decimal = Field(description="negativ = Ausgabe, positiv = Einnahme")
    naechste_faelligkeit: date


class ContractPatch(BaseModel):
    name: str | None = None
    kategorie: str | None = None
    art: str | None = Field(None, max_length=300)
    frist_wert: int | None = Field(None, ge=0, le=999)
    frist_einheit: Literal["tage", "wochen", "monate", ""] | None = None
    laufzeit_bis: date | None = None
    verlaengerung_monate: int | None = Field(None, ge=0, le=120)
    kuendigen: bool | None = None
    vertragsnummer: str | None = Field(None, max_length=80)
    notiz: str | None = Field(None, max_length=2000)
    anteil_prozent: int | None = Field(None, ge=1, le=100)
    gekuendigt_zum: date | None = None
    verwaltet_ueber: Literal["", "direkt", "makler", "app", "portal", "arbeitgeber", "bank", "verband"] | None = None
    verwaltet_name: str | None = Field(None, max_length=80)
    versichert: Literal["", "ich", "partner", "familie", "haushalt"] | None = None
    selbstbeteiligung: Decimal | None = Field(None, ge=0, le=100000)
    kontakt: str | None = Field(None, max_length=200)


# Felder, die sich auch wieder leeren lassen (None = „keine Angabe“)
LEERBAR = {"frist_wert", "laufzeit_bis", "verlaengerung_monate", "gekuendigt_zum", "selbstbeteiligung"}
# Die 30 verbreitetsten Versicherungen in Deutschland: (Name, Stichworte im Vertragsnamen als Vorschlag,
# gehört zur Merkliste „nicht erfasst“). Reihenfolge = Reihenfolge in der Auswahl; speziellere Stichworte zuerst.
VERSICHERUNGSARTEN: list[tuple[str, list[str], bool]] = [
    ("Krankenversicherung (gesetzlich)", ["krankenkasse", "hkk", "aok", "barmer", "techniker", "dak", "ikk", "bkk",
                                          "knappschaft"], True),
    ("Private Krankenversicherung", ["private kranken", "pkv"], False),
    ("Krankenzusatz", ["krankenzusatz", "zusatzversicherung"], False),
    ("Zahnzusatz", ["zahn"], False),
    ("Auslandskranken", ["auslandskranken", "reisekranken"], True),
    ("Pflegezusatz", ["pflege"], False),
    ("Krankentagegeld", ["krankentagegeld", "tagegeld"], False),
    ("Tierhalterhaftpflicht", ["tierhalter", "hundehaft", "pferdehaft"], False),
    ("Kfz-Haftpflicht", ["kfz", "kraftfahrt", "autoversicherung"], False),
    ("Kfz-Kasko", ["kasko"], False),
    ("Berufshaftpflicht", ["berufshaftpflicht", "betriebshaftpflicht"], False),
    ("Privathaftpflicht", ["haftpflicht"], True),
    ("Hausrat", ["hausrat"], True),
    ("Wohngebäude", ["wohngebäude", "wohngebaeude", "gebäudeversicherung"], False),
    ("Elementarschaden", ["elementar"], False),
    ("Rechtsschutz", ["rechtsschutz"], True),
    ("Berufsunfähigkeit", ["berufsunf", "bu-versicherung"], True),
    ("Erwerbsunfähigkeit", ["erwerbsunf"], False),
    ("Unfall", ["unfall"], False),
    ("Risikoleben", ["risikoleben"], False),
    ("Kapitallebensversicherung", ["lebensversicherung"], False),
    ("Private Rentenversicherung", ["rentenversicherung", "privatrente"], False),
    ("Riester-Rente", ["riester"], False),
    ("Rürup-Rente (Basisrente)", ["rürup", "ruerup", "basisrente"], False),
    ("Betriebliche Altersvorsorge", ["direktversicherung", "betriebliche alters"], False),
    ("Sterbegeld", ["sterbegeld"], False),
    ("Tierkranken / Tier-OP", ["tierkranken", "tier-op", "tierversicherung"], False),
    ("Fahrrad / E-Bike", ["fahrrad", "e-bike", "bike"], False),
    ("Reiserücktritt", ["reiserücktritt", "reiseruecktritt", "reiseversicherung"], False),
    ("Handy / Elektronik", ["handyversicherung", "geräteversicherung", "elektronikversicherung"], False),
]


def versicherungsart(c: ContractRow) -> str:
    """Die vom Nutzer eingetragene Art – sonst ein Vorschlag aus dem Namen."""
    if c.art:
        return c.art
    n = c.name.lower()
    return next((art for art, worte, _ in VERSICHERUNGSARTEN if any(w in n for w in worte)), "")


def versicherungsarten(c: ContractRow) -> list[str]:
    """Ein Vertrag kann mehrere Versicherungen bündeln (Hausrat mit Fahrrad): durch Komma getrennt eingetragen."""
    return [a.strip() for a in versicherungsart(c).split(",") if a.strip()]


def contract_out(c: ContractRow, heute: date) -> dict:
    status, tage = contract_status(c, heute)
    return {
        "id": c.id, "name": c.name, "kategorie": c.kategorie, "turnus": c.turnus, "typ": c.typ,
        "betrag": c.erwarteter_betrag, "monatlich": c.monatlich, "naechste_faelligkeit": c.naechste_faelligkeit,
        "letzte_zahlung": c.letzte_zahlung, "status": status, "tage_ueberfaellig": tage,
        "quelle": c.quelle, "methode": c.methode, "vorkommen": c.vorkommen, "sicherheit": c.sicherheit or 0,
        "betrag_gestiegen": c.betrag_gestiegen, "vorheriger_betrag": c.vorheriger_betrag, "bestaetigt": c.gilt,
        "betrag_gesunken": c.vorheriger_betrag is not None and not c.betrag_gestiegen,
        "sparen": c.typ == "ausgabe" and c.kategorie in NICHT_AUSGABEN,
        "logo": logos.domain_fuer(c.name),
        "art": c.art or "", "art_vorschlag": versicherungsart(c) if c.kategorie == "Versicherung" else "",
        "frist_wert": c.frist_wert, "frist_einheit": c.frist_einheit or "",
        "laufzeit_bis": c.laufzeit_bis, "verlaengerung_monate": c.verlaengerung_monate, "kuendigen": bool(c.kuendigen),
        "vertragsnummer": c.vertragsnummer or "", "notiz": c.notiz or "", "kuendigung": kuendigung(c, heute),
        "verwaltet_ueber": c.verwaltet_ueber or "", "verwaltet_name": c.verwaltet_name or "",
        "versichert": c.versichert or "", "selbstbeteiligung": c.selbstbeteiligung, "kontakt": c.kontakt or "",
        "gekuendigt_zum": c.gekuendigt_zum, "jaehrlich": c.monatlich * 12, "anteil_prozent": c.anteil_prozent or 100, "mein_betrag": c.mein_betrag,
    }


@router.get("/contracts")
def contracts(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    heute = ctx.today()
    alle = list(s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False))))
    # Erkannte, noch nicht bestätigte Verträge sind Vorschläge: Sie werden erfragt und zählen bis dahin nicht mit
    vorschlaege = [o for o in (contract_out(c, heute) for c in alle if not c.gilt) if o["status"] != "inaktiv"]
    rows = [c for c in alle if c.gilt]
    out = [contract_out(c, heute) for c in rows]
    status = {o["id"]: o["status"] for o in out}
    for c in rows:  # summary_/average_-Funktionen erwarten .status – Laufzeitstatus einsetzen
        c.status = status[c.id]
    # Sparpläne sind ein eigener Abschnitt: Vermögensaufbau, keine laufenden Kosten
    sparen_ids = {c.id for c in rows if c.typ == "ausgabe" and c.kategorie in NICHT_AUSGABEN}

    def sektion(typ: str, sparen: bool = False) -> list[dict]:
        auswahl = [c for c in rows if c.typ == typ and (c.id in sparen_ids) == sparen]
        summary = summary_by_turnus(auswahl)[typ]
        ids = {c.id for c in auswahl}
        return [{"turnus": t, **summary[t],
                 "vertraege": sorted((o for o in out if o["id"] in ids and o["turnus"] == t
                                      and o["status"] != "inaktiv"), key=lambda o: -abs(o["betrag"]))}
                for t in TURNI if t in summary]

    return {
        "ausgaben_monatlich": average_monthly_expenses(rows),
        "sparen_monatlich": average_monthly_savings(rows),
        "basierend_seit": s.scalar(select(func.min(TransactionRow.buchungsdatum))),
        "ausgaben": sektion("ausgabe"),
        "einnahmen": sektion("einnahme"),
        "sparen": sektion("ausgabe", sparen=True),
        "inaktiv": [o for o in out if o["status"] == "inaktiv"],
        "vorschlaege": sorted(vorschlaege, key=lambda o: (-o["sicherheit"], -abs(o["monatlich"]))),
    }


@router.get("/logo/{domain}")
def logo(domain: str, ctx=Depends(get_ctx)):
    """Logo eines bekannten Anbieters – einmal geholt, dann aus `data/logos/`."""
    datei = logos.logo_datei(ctx.settings.data_dir, domain.lower())
    if not datei:
        raise HTTPException(404, "Kein Logo")
    typ = logos.bildtyp(datei.read_bytes()[:16]) or "image/png"
    return FileResponse(datei, media_type=typ, headers={"Cache-Control": "private, max-age=2592000"})


@router.get("/contracts/{contract_id}")
def contract_detail(contract_id: int, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    c = s.get(ContractRow, contract_id)
    if not c or c.entfernt:
        raise HTTPException(404, "Vertrag nicht gefunden")
    namen = dict(s.execute(select(Account.id, Account.name)).all())
    zahlungen = list(s.scalars(select(TransactionRow).where(TransactionRow.contract_id == c.id)
                               .order_by(TransactionRow.buchungsdatum.desc())))
    heute = ctx.today()
    vor_einem_jahr = add_months(heute, -12)
    anteil = Decimal(c.anteil_prozent or 100) / 100
    return {**contract_out(c, heute),
            # tatsächlich gebucht – im Unterschied zu „jaehrlich“ (aktueller Betrag aufs Jahr hochgerechnet)
            "gezahlt_12_monate": sum((t.betrag for t in zahlungen if vor_einem_jahr < t.buchungsdatum <= heute),
                                     Decimal(0)) * anteil,
            "gezahlt_gesamt": sum((t.betrag for t in zahlungen), Decimal(0)),
            "zahlungen": [{"id": t.id, "datum": t.buchungsdatum, "betrag": t.betrag,
                           "verwendungszweck": t.verwendungszweck, "konto_name": namen.get(t.account_id)}
                          for t in zahlungen]}


@router.get("/versicherungen")
def versicherungen(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Alle bestätigten Versicherungen mit Jahreskosten – und welche üblichen Arten (noch) nicht erfasst sind."""
    heute = ctx.today()
    rows = [c for c in s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False),
                                                          ContractRow.kategorie == "Versicherung"))
            if c.gilt and c.typ == "ausgabe" and contract_status(c, heute)[0] != "inaktiv"]
    vertraege = sorted(({**contract_out(c, heute), "arten": versicherungsarten(c), "art_eingetragen": bool(c.art)}
                        for c in rows), key=lambda o: -o["jaehrlich"])
    vorhanden = {a for o in vertraege for a in o["arten"]}
    monatlich = sum((o["monatlich"] for o in vertraege), Decimal(0))
    for o in vertraege:  # Anteil an den gesamten Versicherungskosten – für den Balken in der Übersicht
        o["kostenanteil"] = float(o["monatlich"] / monatlich) if monatlich else 0.0
    termine = sorted((o for o in vertraege if o["kuendigung"] and o["kuendigung"]["kuendigen_bis"]
                      and not o["kuendigung"]["verpasst"] and not o["gekuendigt_zum"]),
                     key=lambda o: o["kuendigung"]["kuendigen_bis"])
    return {"vertraege": vertraege, "jaehrlich": sum((o["jaehrlich"] for o in vertraege), Decimal(0)),
            "monatlich": monatlich,
            # der nächste Termin, bis zu dem eine Versicherung gekündigt sein müsste
            "naechste_kuendigung": {"id": termine[0]["id"], "name": termine[0]["name"],
                                    **termine[0]["kuendigung"]} if termine else None,
            "arten": sorted(a for a, _, _ in VERSICHERUNGSARTEN),
            "nicht_erfasst": [a for a, _, kern in VERSICHERUNGSARTEN if kern and a not in vorhanden]}


@router.post("/contracts", status_code=201)
def add_contract(body: ContractIn, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    c = ContractRow(name=body.name, kategorie=body.kategorie, turnus=body.turnus,
                    erwarteter_betrag=body.betrag, naechste_faelligkeit=body.naechste_faelligkeit,
                    typ="einnahme" if body.betrag > 0 else "ausgabe", quelle="manuell", bearbeitet=True,
                    bestaetigt=True, muster=muster_aus_name(body.name, body.betrag > 0))
    s.add(c)
    sync_contracts(s, ctx.today())  # passende Buchungen gleich einsammeln
    s.commit()
    return {"id": c.id}


@router.patch("/contracts/{contract_id}")
def patch_contract(contract_id: int, body: ContractPatch, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    c = s.get(ContractRow, contract_id)
    if not c or c.entfernt:
        raise HTTPException(404, "Vertrag nicht gefunden")
    gesetzt = body.model_fields_set
    for k, v in body.model_dump().items():
        if k in gesetzt and (v is not None or k in LEERBAR):
            setattr(c, k, v.strip() if isinstance(v, str) else v)
    if c.frist_wert and not c.frist_einheit:
        c.frist_einheit = "monate"
    if gesetzt & {"name", "kategorie"}:
        c.bearbeitet = True
    c.bestaetigt = True  # wer einen Vertrag anpasst, hält ihn für echt
    if c.gekuendigt_zum:
        c.kuendigen = False  # erledigt – nicht weiter erinnern
    if c.kuendigen:  # die Erinnerung soll nicht erst mit dem nächsten Abruf kommen
        pruefe_kuendigungen(ctx.notifier, s, ctx.today(), push=False)
    if body.kategorie:  # zugehörige Buchungen mitziehen (für Analysen)
        s.execute(update(TransactionRow).where(TransactionRow.contract_id == c.id).values(kategorie=body.kategorie))
    s.commit()
    return contract_out(c, ctx.today())


@router.post("/contracts/{contract_id}/bestaetigen")
def confirm_contract(contract_id: int, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    c = s.get(ContractRow, contract_id)
    if not c or c.entfernt:
        raise HTTPException(404, "Vertrag nicht gefunden")
    c.bestaetigt = True
    s.commit()
    return contract_out(c, ctx.today())


@router.delete("/contracts/{contract_id}", status_code=204)
def delete_contract(contract_id: int, s: Session = Depends(get_db)):
    c = s.get(ContractRow, contract_id)
    if not c:
        raise HTTPException(404, "Vertrag nicht gefunden")
    if c.quelle == "manuell":
        s.delete(c)
    else:
        # merken, damit die Erkennung ihn beim nächsten Import nicht wieder anlegt
        c.entfernt = True
        s.execute(update(TransactionRow).where(TransactionRow.contract_id == c.id).values(contract_id=None))
    s.commit()


@router.post("/contracts/redetect")
def redetect(s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    result = sync_contracts(s, ctx.today())
    s.commit()
    return result.als_dict()


@router.get("/kalender")
def kalender(tage: int = 45, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Anstehende Zahlungen und Eingänge aus den Verträgen, nach Tag gruppiert."""
    heute = ctx.today()
    ende = heute + timedelta(days=min(max(tage, 7), 400))
    monatsende = add_months(heute.replace(day=1), 1) - timedelta(days=1)
    eintraege = []
    for c in s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False))):
        status, tage_ueber = contract_status(c, heute)
        if status == "inaktiv" or not c.gilt:
            continue
        basis = {"id": c.id, "name": c.name, "kategorie": c.kategorie, "typ": c.typ, "betrag": c.mein_betrag}
        k = 0
        if status == "ueberfaellig":
            eintraege.append({**basis, "datum": c.naechste_faelligkeit, "ueberfaellig": True,
                              "tage_ueberfaellig": tage_ueber})
            k = 1
        while (d := naechster_termin(c.naechste_faelligkeit, c.turnus, k)) <= ende:
            if c.gekuendigt_zum and d > c.gekuendigt_zum:
                break
            if d >= heute:
                eintraege.append({**basis, "datum": d, "ueberfaellig": False})
            k += 1
    eintraege.sort(key=lambda e: (not e["ueberfaellig"], e["datum"], e["typ"] != "einnahme", -abs(e["betrag"])))
    tage_liste: list[dict] = []
    for e in eintraege:
        schluessel = "ueberfaellig" if e["ueberfaellig"] else e["datum"].isoformat()
        if not tage_liste or tage_liste[-1]["datum"] != schluessel:
            tage_liste.append({"datum": schluessel, "eintraege": [], "summe": 0})
        tage_liste[-1]["eintraege"].append(e)
        tage_liste[-1]["summe"] += e["betrag"]
    bis_monatsende = [e for e in eintraege if not e["ueberfaellig"] and e["datum"] <= monatsende]
    return {
        "tage": tage_liste,
        "monat_ausgaben": sum((abs(e["betrag"]) for e in bis_monatsende if e["typ"] == "ausgabe"), 0),
        "monat_einnahmen": sum((e["betrag"] for e in bis_monatsende if e["typ"] == "einnahme"), 0),
    }
