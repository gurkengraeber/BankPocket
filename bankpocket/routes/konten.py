"""Konten, Kontogruppen und Buchungen."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..contracts import (KI_KATEGORIEN, categorize, haendler_schluessel, muster, naechster_termin, paypal_merchant,
                         regelkategorie)
from ..csv_import import parse_depot, parse_transactions
from .. import logos, umbuchungen
from ..analysen import _kategorie, ist_steuer
from ..db import GRUPPEN, KONTOTYPEN, Account, Balance, Connection, ContractRow, Holding, Price, TransactionRow
from ..models import Transaction
from ..service import (_to_dataclass, account_saldo, holdings_setzen, import_transactions, konten_zusammenfuehren,
                       loesch_folgen, saldo_setzen,
                       sync_contracts, zahlung_anrechnen)
from .deps import get_ctx, get_db

router = APIRouter(prefix="/api")


class AccountIn(BaseModel):
    name: str
    quelle: str = "manuell"
    typ: Literal[tuple(KONTOTYPEN)]  # type: ignore[valid-type]
    gruppe: Literal[tuple(GRUPPEN)]  # type: ignore[valid-type]
    waehrung: str = "EUR"


class AccountPatch(BaseModel):
    name: str | None = None
    aktiv: bool | None = None
    gruppe: Literal[tuple(GRUPPEN)] | None = None  # type: ignore[valid-type]


class ReihenfolgeIn(BaseModel):
    ids: list[int]


class BuchungIn(BaseModel):
    datum: date
    betrag: Decimal
    gegenpartei: str = ""
    verwendungszweck: str = ""


class StandIn(BaseModel):
    saldo: Decimal
    datum: date | None = None  # „Stand vom“ – ohne Angabe heute


class BuchungPatch(BaseModel):
    """Nur die mitgeschickten Felder werden geändert; contract_id = null löst die Zuordnung."""
    kategorie: str | None = None
    intern: bool | None = None
    notiz: str | None = None
    contract_id: int | None = None
    tags: list[str] | None = None
    ausgeschlossen: bool | None = None  # bei „frei verfügbar“ nicht mitzählen
    # Steuerliste (Sparen → Steuern): "ja" = als Steuerzahlung führen, "nein" = herausnehmen, "" = automatisch
    steuer: Literal["", "ja", "nein"] | None = None
    rueckzahlung: bool | None = None  # Geld kam zurück: mindert die Ausgaben statt als Einnahme zu zählen
    # nur bei selbst eingetragenen Buchungen (manuelle Konten) änderbar:
    datum: date | None = None
    betrag: Decimal | None = None
    gegenpartei: str | None = None


class BuchungVertragIn(BaseModel):
    turnus: Literal["woechentlich", "zweiwoechentlich", "halbmonatlich", "vierwoechentlich", "monatlich", "quartalsweise", "halbjaehrlich", "jaehrlich"]


class GesehenIn(BaseModel):
    """Einzelne Buchungen (ids) oder alle eines Kontos bzw. einer Gruppe als gelesen markieren."""
    konto: int | None = None
    gruppe: str | None = None
    ids: list[int] | None = None


def get_account(s: Session, account_id: int) -> Account:
    acc = s.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "Konto nicht gefunden")
    return acc


def konto_out(s: Session, a: Account, ungesehen: int = 0, verbindungen: dict | None = None) -> dict:
    conn = (verbindungen or {}).get(a.connection_id)
    return {"id": a.id, "name": a.name, "quelle": a.quelle, "typ": a.typ, "gruppe": a.gruppe,
            "waehrung": a.waehrung, "aktiv": a.aktiv, "saldo": account_saldo(s, a),
            "stand": a.zuletzt_aktualisiert, "ungesehen": ungesehen, "manuell": a.quelle == "manuell",
            # ohne Bankanbindung (manuell oder CSV-Import) trägt man den Kontostand selbst ein
            "stand_setzbar": a.quelle == "manuell" or a.connection_id is None,
            "iban_ende": a.iban[-4:] if a.iban else None, "connection_id": a.connection_id,
            "verbindung_status": conn.status if conn else None}


def kontogruppen(s: Session) -> dict:
    ungesehen = dict(s.execute(select(TransactionRow.account_id, func.count())
                               .where(TransactionRow.gesehen.is_(False))
                               .group_by(TransactionRow.account_id)).all())
    verbindungen = {c.id: c for c in s.scalars(select(Connection))}
    gruppen, gesamt = [], Decimal(0)
    for g in GRUPPEN:
        konten, summe = [], Decimal(0)
        for a in s.scalars(select(Account).where(Account.gruppe == g).order_by(Account.aktiv.desc(), Account.position, Account.id)):
            k = konto_out(s, a, ungesehen.get(a.id, 0), verbindungen)
            if a.aktiv and k["saldo"] is not None:
                summe += k["saldo"]
            konten.append(k)
        gruppen.append({"name": g, "summe": summe, "ungesehen": sum(k["ungesehen"] for k in konten if k["aktiv"]),
                        "konten": konten})
        gesamt += summe
    return {"gruppen": gruppen, "gesamtsumme": gesamt}


def _kategorie_quelle(t: TransactionRow) -> str:
    if t.kategorie:
        return "manuell"
    typ = "einnahme" if t.betrag > 0 else "ausgabe"
    if regelkategorie(t.gegenpartei, t.verwendungszweck, typ, t.buchungstext):
        return "regel"
    return "ki" if (typ, haendler_schluessel(t.gegenpartei, t.verwendungszweck)) in KI_KATEGORIEN else "standard"


def tags_liste(text: str | None) -> list[str]:
    return [x for x in (text or "").split(",") if x]


def tags_text(tags: list[str]) -> str:
    """Schlagworte ohne „#“, Kommas und Doppelte – in der Reihenfolge der Eingabe."""
    sauber: list[str] = []
    for tag in tags:
        tag = " ".join(tag.replace(",", " ").lstrip("#").split())[:30]
        if tag and tag.lower() not in (x.lower() for x in sauber):
            sauber.append(tag)
    return ",".join(sauber[:12])


def buchung_out(t: TransactionRow, konto_name: str | None = None) -> dict:
    haendler = (paypal_merchant(_to_dataclass(t)) or t.gegenpartei).strip()
    return {"id": t.id, "datum": t.buchungsdatum, "betrag": t.betrag, "gegenpartei": t.gegenpartei,
            "verwendungszweck": t.verwendungszweck, "buchungstext": t.buchungstext,
            "kategorie": _kategorie(t),
            "kategorie_manuell": bool(t.kategorie), "kategorie_quelle": _kategorie_quelle(t),
            "haendler": haendler, "intern": t.intern, "gesehen": t.gesehen,
            # bekannte Anbieter (Spotify, REWE, Bahn …) zeigen ihr Logo statt des Kategorie-Symbols
            "logo": None if t.intern else logos.domain_fuer(haendler),
            "contract_id": t.contract_id, "konto_id": t.account_id, "konto_name": konto_name, "notiz": t.notiz or "",
            "gegenbuchung_id": t.gegenbuchung_id, "ausgeschlossen": bool(t.ausgeschlossen),
            "steuer": ist_steuer(t), "steuer_wahl": t.steuer or "", "rueckzahlung": bool(t.rueckzahlung),
            # bei geteilten Verträgen: der eigene Teil dieser Buchung (sonst None)
            "mein_betrag": t.mein_betrag if getattr(t, "mein_betrag", t.betrag) != t.betrag else None,
            "tags": tags_liste(t.tags)}


@router.get("/accounts")
def accounts(s: Session = Depends(get_db)):
    return kontogruppen(s)


@router.post("/accounts", status_code=201)
def create_account(body: AccountIn, s: Session = Depends(get_db)):
    acc = Account(**body.model_dump())
    s.add(acc)
    s.commit()
    return {"id": acc.id}


@router.put("/accounts/reihenfolge")
def konten_reihenfolge(body: ReihenfolgeIn, s: Session = Depends(get_db)):
    """Reihenfolge der Konten (einer Gruppe) so speichern, wie sie in der Übersicht gezogen wurde."""
    for platz, account_id in enumerate(body.ids, start=1):
        acc = s.get(Account, account_id)
        if acc:
            acc.position = platz
    s.commit()
    return {"ok": True}


@router.patch("/accounts/{account_id}")
def patch_account(account_id: int, body: AccountPatch, s: Session = Depends(get_db)):
    acc = get_account(s, account_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(acc, k, v)
    s.commit()
    return {"ok": True}


class ZusammenfuehrenIn(BaseModel):
    ziel_id: int


@router.get("/accounts/{account_id}/folgen")
def konto_folgen(account_id: int, s: Session = Depends(get_db)):
    """Was beim Löschen dieses Kontos verloren ginge – für die Rückfrage."""
    return loesch_folgen(s, get_account(s, account_id))


@router.post("/accounts/{account_id}/zusammenfuehren")
def konto_zusammenfuehren(account_id: int, body: ZusammenfuehrenIn, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Dieses Konto in ein anderes übernehmen (z. B. altes CSV-Konto → angebundenes Bankkonto)."""
    quelle, ziel = get_account(s, account_id), get_account(s, body.ziel_id)
    if quelle.id == ziel.id:
        raise HTTPException(422, "Bitte ein anderes Konto wählen.")
    if quelle.connection_id is not None:
        raise HTTPException(409, "Dieses Konto gehört zu einer Bankverbindung und käme beim nächsten Abruf zurück. "
                                 "Übernimm stattdessen das andere Konto in dieses.")
    if "depot" in (quelle.typ, ziel.typ):
        raise HTTPException(422, "Depots lassen sich nicht zusammenführen.")
    ergebnis = konten_zusammenfuehren(s, quelle, ziel, ctx.today())
    s.commit()
    return {**ergebnis, "ziel_id": ziel.id}


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: int, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Konto samt Buchungen, Ständen und Positionen löschen. Verbundene Konten legt der nächste Abruf wieder an –
    die löscht man über ihre Verbindung."""
    acc = get_account(s, account_id)
    if acc.connection_id is not None:
        raise HTTPException(409, "Dieses Konto gehört zu einer Bankverbindung und käme beim nächsten Abruf zurück. "
                                 "Lösche die Verbindung in den Einstellungen – danach lässt sich das Konto löschen.")
    for tabelle in (TransactionRow, Balance, Holding):
        s.execute(delete(tabelle).where(tabelle.account_id == acc.id))
    s.delete(acc)
    s.flush()
    sync_contracts(s, ctx.today())  # Verträge, die nur aus diesen Buchungen bestanden, werden inaktiv
    s.commit()


@router.get("/accounts/{account_id}/positionen")
def positionen(account_id: int, s: Session = Depends(get_db)):
    """Aktueller Bestand eines Depots oder Krypto-Kontos (Stand des letzten Abrufs), größte Position zuerst."""
    acc = get_account(s, account_id)
    stand = s.scalar(select(func.max(Holding.datum)).where(Holding.account_id == acc.id))
    zeilen = s.scalars(select(Holding).where(Holding.account_id == acc.id, Holding.datum == stand)
                       .order_by(Holding.wert.desc())) if stand else []
    # Kurse des vorherigen Stands, um die Veränderung seit dem letzten Abruftag zu zeigen
    davor = s.scalar(select(func.max(Holding.datum)).where(Holding.account_id == acc.id, Holding.datum < stand)) \
        if stand else None
    alte_kurse = {h.symbol: h.kurs for h in s.scalars(
        select(Holding).where(Holding.account_id == acc.id, Holding.datum == davor))} if davor else {}
    out, gewinn_summe, einsatz_summe = [], Decimal(0), Decimal(0)
    for h in zeilen:
        # Plus/Minus seit dem Kauf, sofern die Quelle den Kaufkurs kennt
        einsatz = (h.menge * h.einstand).quantize(Decimal("0.01")) if h.einstand else None
        gewinn = h.wert - einsatz if einsatz else None
        if gewinn is not None:
            gewinn_summe, einsatz_summe = gewinn_summe + gewinn, einsatz_summe + einsatz
        out.append({"symbol": h.symbol, "name": h.name or h.symbol, "menge": h.menge, "kurs": h.kurs, "wert": h.wert,
                    "einstand": h.einstand, "gewinn": gewinn,
                    "kurs_prozent": round(float((h.kurs - alte_kurse[h.symbol]) / alte_kurse[h.symbol] * 100), 2)
                    if h.kurs and alte_kurse.get(h.symbol) else None,
                    "gewinn_prozent": round(float(gewinn / einsatz * 100), 1) if einsatz else None})
    return {"stand": stand, "davor": davor, "positionen": out,
            "gewinn": gewinn_summe if einsatz_summe else None,
            "gewinn_prozent": round(float(gewinn_summe / einsatz_summe * 100), 1) if einsatz_summe else None}


@router.get("/accounts/{account_id}/positionen/{symbol}")
def position_verlauf(account_id: int, symbol: str, s: Session = Depends(get_db)):
    """Wertverlauf einer Position: Stückzahl am jeweiligen Tag (aus den Käufen zurückgerechnet) × Kurs des Tages."""
    acc = get_account(s, account_id)
    h = s.scalar(select(Holding).where(Holding.account_id == acc.id, Holding.symbol == symbol)
                 .order_by(Holding.datum.desc()).limit(1))
    if not h:
        raise HTTPException(404, "Position nicht gefunden")
    kurse = dict(s.execute(select(Price.datum, Price.kurs).where(Price.symbol == symbol).order_by(Price.datum)).all())
    # Käufe und Verkäufe stehen auf dem Verrechnungskonto derselben Verbindung, benannt nach dem Wertpapier
    trades = list(s.scalars(select(TransactionRow).join(Account).where(
        Account.connection_id == acc.connection_id, Account.id != acc.id, TransactionRow.kategorie == "Sparen",
        TransactionRow.gegenpartei == h.name).order_by(TransactionRow.buchungsdatum))) if acc.connection_id and h.name else []
    tage = sorted(kurse)

    def kurs_am(tag: date) -> Decimal | None:
        frueher = [t for t in tage if t <= tag]
        return kurse[frueher[-1]] if frueher else (kurse[tage[0]] if tage else None)

    einsatz_heute = (h.menge * h.einstand) if h.einstand else None
    punkte = []
    for tag in tage:
        stueck, einsatz = h.menge, einsatz_heute
        for t in trades:
            if t.buchungsdatum > tag:
                k = kurs_am(t.buchungsdatum)
                if k:
                    stueck += t.betrag / k  # Kauf (negativ) rückgängig machen, Verkauf (positiv) wieder dazunehmen
                if einsatz is not None:
                    einsatz += t.betrag
        punkte.append({"d": tag, "w": (max(stueck, Decimal(0)) * kurse[tag]).quantize(Decimal("0.01")),
                       "kurs": kurse[tag],
                       "eingezahlt": max(einsatz, Decimal(0)).quantize(Decimal("0.01")) if einsatz is not None else None})
    gewinn = (h.wert - einsatz_heute.quantize(Decimal("0.01"))) if einsatz_heute else None
    return {"symbol": h.symbol, "name": h.name or h.symbol, "menge": h.menge, "kurs": h.kurs, "wert": h.wert,
            "einstand": h.einstand, "gewinn": gewinn,
            "gewinn_prozent": round(float(gewinn / einsatz_heute * 100), 1) if einsatz_heute else None,
            "punkte": punkte,
            "kaeufe": [{"id": t.id, "datum": t.buchungsdatum, "betrag": t.betrag, "text": t.verwendungszweck}
                       for t in reversed(trades)]}


@router.post("/accounts/{account_id}/import")
async def import_csv(account_id: int, file: UploadFile = File(...), delimiter: str = Query(";"),
                     s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    acc = get_account(s, account_id)
    raw = await file.read()
    depot = parse_depot(raw, delimiter)
    if depot:
        return _depot_importieren(s, acc, depot, ctx)
    try:
        txs = parse_transactions(raw, delimiter)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return import_transactions(s, acc, txs, ctx.today())


def _depot_importieren(s: Session, acc: Account, depot: dict, ctx) -> dict:
    """Depotübersicht: Das Konto wird zum Depot, die Positionen ersetzen den Bestand des Export-Tags."""
    if acc.connection_id is not None or acc.quelle == "manuell":
        raise HTTPException(422, "Eine Depotübersicht lässt sich nur in ein eigenes CSV-Konto importieren.")
    if acc.typ != "depot" and s.scalar(select(func.count()).select_from(TransactionRow)
                                       .where(TransactionRow.account_id == acc.id)):
        raise HTTPException(422, "Das ist eine Depotübersicht – bitte als neues Konto importieren, nicht in ein "
                                 "Konto mit Buchungen.")
    from ..fetchers.base import FetchedHolding
    tag = min(depot["datum"] or ctx.today(), ctx.today())
    positionen = [FetchedHolding(symbol=p["symbol"][:20], name=p["name"], menge=p["menge"], kurs=p["kurs"],
                                 wert=p["wert"], datum=tag, einstand=p["einstand"]) for p in depot["positionen"]]
    if acc.typ != "depot":  # beim ersten Import einsortieren – eine später gewählte Gruppe bleibt
        acc.typ, acc.gruppe = "depot", "Sparkonten"
    holdings_setzen(s, acc, tag, positionen)
    gesamt = sum((p.wert for p in positionen), Decimal(0))
    saldo_setzen(s, acc, tag, gesamt)
    acc.zuletzt_aktualisiert = ctx.now()
    s.commit()
    return {"importiert": len(positionen), "duplikate": 0, "depot": True, "wert": gesamt, "stand": tag}


@router.get("/accounts/{account_id}/transactions")
def transactions(account_id: int, limit: int = Query(100, le=1000), s: Session = Depends(get_db)):
    get_account(s, account_id)
    rows = s.scalars(select(TransactionRow).where(TransactionRow.account_id == account_id)
                     .order_by(TransactionRow.buchungsdatum.desc(), TransactionRow.id.desc()).limit(limit))
    return [buchung_out(r) for r in rows]


@router.post("/accounts/{account_id}/transactions", status_code=201)
def add_buchung(account_id: int, body: BuchungIn, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """„Buchung hinzufügen“ für manuelle Konten (Bargeld, Kautionen & Schulden …)."""
    acc = get_account(s, account_id)
    if acc.quelle != "manuell":
        raise HTTPException(400, "Manuelle Buchungen nur auf manuellen Konten")
    t = Transaction(body.datum, body.betrag, body.gegenpartei, body.verwendungszweck)
    return import_transactions(s, acc, [t], ctx.today(), eindeutig=True)


@router.post("/accounts/{account_id}/stand")
def stand_setzen(account_id: int, body: StandIn, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """„Stand eintragen“ für manuelle Konten (z. B. Splitwise): bucht nur die Differenz zum bisherigen Saldo."""
    acc = get_account(s, account_id)
    if acc.quelle != "manuell":
        if acc.connection_id is not None:
            raise HTTPException(400, "Bei verbundenen Konten kommt der Stand von der Bank.")
        # CSV-Konto: Der eingetragene Stand ist der Ankerpunkt, von dem aus die Umsätze zurückgerechnet werden –
        # die importierten Buchungen bleiben unverändert.
        tag = min(body.datum or ctx.today(), ctx.today())
        saldo_setzen(s, acc, tag, body.saldo)
        acc.zuletzt_aktualisiert = ctx.now()
        s.commit()
        return {"saldo": account_saldo(s, acc), "differenz": Decimal(0)}
    differenz = body.saldo - account_saldo(s, acc)
    if differenz:
        tag = min(body.datum or ctx.today(), ctx.today())
        import_transactions(s, acc, [Transaction(tag, differenz, "Stand angepasst")], ctx.today(), eindeutig=True)
        # Eine Korrektur des Stands ist weder Einnahme noch Ausgabe
        s.execute(update(TransactionRow).where(TransactionRow.account_id == acc.id, TransactionRow.intern.is_(False),
                                               TransactionRow.gegenpartei == "Stand angepasst").values(intern=True))
        s.commit()
    return {"saldo": account_saldo(s, acc), "differenz": differenz}


@router.post("/accounts/{account_id}/seen")
def mark_seen(account_id: int, s: Session = Depends(get_db)):
    s.execute(update(TransactionRow).where(TransactionRow.account_id == account_id).values(gesehen=True))
    s.commit()
    return {"ok": True}


def _konto_ids(s: Session, konto: int | None, gruppe: str | None) -> list[int]:
    q = select(Account.id)
    if konto is not None:
        q = q.where(Account.id == konto)
    elif gruppe:
        q = q.where(Account.gruppe == gruppe, Account.aktiv.is_(True))
    return list(s.scalars(q))


@router.get("/buchungen")
def buchungen(konto: int | None = None, gruppe: str | None = None, suche: str | None = None,
              kategorie: str | None = None, tag: str | None = None,
              limit: int = Query(60, le=500), offset: int = 0, s: Session = Depends(get_db)):
    ids = _konto_ids(s, konto, gruppe)
    namen = dict(s.execute(select(Account.id, Account.name)).all())
    q = select(TransactionRow).where(TransactionRow.account_id.in_(ids))
    q = q.order_by(TransactionRow.buchungsdatum.desc(), TransactionRow.id.desc())
    wort = (suche or "").strip().lstrip("#").lower()
    if wort or kategorie or tag:
        # Empfänger, Verwendungszweck, Tag, Notiz – und die Kategorie. Die wird meist erst beim Anzeigen
        # bestimmt, deshalb läuft die Suche über die fertigen Buchungen statt in der Datenbank.
        def passt(t: TransactionRow) -> bool:
            kat = _anzeige_kategorie(t)
            if kategorie and kat != kategorie:
                return False
            if tag and tag not in tags_liste(t.tags):
                return False
            return not wort or any(wort in (text or "").lower()
                                   for text in (t.gegenpartei, t.verwendungszweck, t.tags, t.notiz, kat))
        rows = [t for t in s.scalars(q) if passt(t)][offset:offset + limit + 1]
    else:
        rows = list(s.scalars(q.limit(limit + 1).offset(offset)))
    return {"buchungen": [buchung_out(r, namen.get(r.account_id)) for r in rows[:limit]],
            "weitere": len(rows) > limit}


def _anzeige_kategorie(t: TransactionRow) -> str:
    return "Umbuchung" if t.intern else buchung_out(t)["kategorie"]


@router.get("/buchungen/filter")
def buchungen_filter(konto: int | None = None, gruppe: str | None = None, s: Session = Depends(get_db)):
    """Kategorien und Tags, die in dieser Ansicht vorkommen – häufigste zuerst, als Auswahl unter dem Suchfeld."""
    kategorien: dict[str, int] = {}
    tags: dict[str, int] = {}
    for t in s.scalars(select(TransactionRow).where(TransactionRow.account_id.in_(_konto_ids(s, konto, gruppe)))):
        kat = _anzeige_kategorie(t)
        kategorien[kat] = kategorien.get(kat, 0) + 1
        for x in tags_liste(t.tags):
            tags[x] = tags.get(x, 0) + 1

    def sortiert(d: dict[str, int]) -> list[dict]:
        return [{"name": k, "anzahl": n} for k, n in sorted(d.items(), key=lambda p: (-p[1], p[0].lower()))]
    return {"kategorien": sortiert(kategorien), "tags": sortiert(tags)}


@router.get("/tags")
def tags(s: Session = Depends(get_db)):
    """Alle vergebenen Schlagworte, häufigste zuerst – als Vorschläge beim Eintippen."""
    zaehler: dict[str, int] = {}
    for text in s.scalars(select(TransactionRow.tags).where(TransactionRow.tags != "")):
        for tag in tags_liste(text):
            zaehler[tag] = zaehler.get(tag, 0) + 1
    return [{"tag": k, "anzahl": n} for k, n in sorted(zaehler.items(), key=lambda p: (-p[1], p[0].lower()))]


@router.post("/buchungen/gesehen")
def buchungen_gesehen(body: GesehenIn, s: Session = Depends(get_db)):
    if body.ids is not None:
        q = update(TransactionRow).where(TransactionRow.id.in_(body.ids))
    else:
        q = update(TransactionRow).where(TransactionRow.account_id.in_(_konto_ids(s, body.konto, body.gruppe)))
    s.execute(q.values(gesehen=True))
    s.commit()
    return {"ok": True}


@router.get("/buchungen/{buchung_id}")
def buchung(buchung_id: int, s: Session = Depends(get_db)):
    t = s.get(TransactionRow, buchung_id)
    if not t:
        raise HTTPException(404, "Buchung nicht gefunden")
    acc = s.get(Account, t.account_id)
    return _buchung_detail(s, t)


def _buchung_detail(s: Session, t: TransactionRow) -> dict:
    acc = s.get(Account, t.account_id)
    c = s.get(ContractRow, t.contract_id) if t.contract_id else None
    if c and not c.entfernt and c.gilt and c.typ == "ausgabe" and (c.anteil_prozent or 100) < 100 and t.betrag < 0:
        t.mein_betrag = t.betrag * c.anteil_prozent / 100
    return {**buchung_out(t, acc.name if acc else None), "iban_gegenpartei": t.iban_gegenpartei,
            "bearbeitbar": bool(acc and acc.quelle == "manuell"),
            "gegenbuchung": _kurz(s, s.get(TransactionRow, t.gegenbuchung_id)) if t.gegenbuchung_id else None,
            "glaeubiger_id": t.glaeubiger_id, "mandatsreferenz": t.mandatsreferenz,
            "vertrag": {"id": c.id, "name": c.name, "turnus": c.turnus, "betrag": c.erwarteter_betrag,
                        "kategorie": c.kategorie, "anteil_prozent": c.anteil_prozent or 100}
            if c and not c.entfernt else None}


def _kurz(s: Session, t: TransactionRow | None) -> dict | None:
    """Eine Buchung in Kurzform – für Gegenbuchungen und ihre Auswahl."""
    if t is None:
        return None
    acc = s.get(Account, t.account_id)
    return {"id": t.id, "datum": t.buchungsdatum, "betrag": t.betrag, "gegenpartei": t.gegenpartei,
            "verwendungszweck": t.verwendungszweck[:80], "konto_id": t.account_id, "konto_name": acc.name if acc else "",
            "konto_quelle": acc.quelle if acc else ""}


def _vertrag_nachfuehren(c: ContractRow, t: TransactionRow) -> None:
    """Eine zugeordnete Zahlung zählt für den Vertrag: letzte Zahlung und nächster Termin."""
    if c.letzte_zahlung and c.letzte_zahlung >= t.buchungsdatum:
        return
    if c.quelle != "manuell":
        zahlung_anrechnen(c, t)
        return
    c.letzte_zahlung = t.buchungsdatum
    c.naechste_faelligkeit = max(c.naechste_faelligkeit, naechster_termin(t.buchungsdatum, c.turnus))


@router.patch("/buchungen/{buchung_id}")
def buchung_patch(buchung_id: int, body: BuchungPatch, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    t = s.get(TransactionRow, buchung_id)
    if not t:
        raise HTTPException(404, "Buchung nicht gefunden")
    felder = body.model_fields_set
    if felder & {"datum", "betrag", "gegenpartei"}:
        if s.get(Account, t.account_id).quelle != "manuell":
            raise HTTPException(400, "Datum, Betrag und Text lassen sich nur bei selbst eingetragenen Buchungen ändern.")
        if body.datum:
            t.buchungsdatum = body.datum
        if body.betrag:
            t.betrag = body.betrag
        if body.gegenpartei is not None:
            t.gegenpartei = body.gegenpartei.strip()[:200]
    if "kategorie" in felder:
        t.kategorie = body.kategorie or None
    if "intern" in felder and body.intern is not None:
        t.intern, t.intern_fix = body.intern, True  # Abrufe und die Umbuchungs-Erkennung lassen das so stehen
    if "notiz" in felder:
        t.notiz = (body.notiz or "").strip()
    if "tags" in felder:
        t.tags = tags_text(body.tags or [])
    if "ausgeschlossen" in felder and body.ausgeschlossen is not None:
        t.ausgeschlossen = body.ausgeschlossen
    if "steuer" in felder and body.steuer is not None:
        t.steuer = body.steuer
    if "rueckzahlung" in felder and body.rueckzahlung is not None:
        if t.betrag <= 0:
            raise HTTPException(400, "Nur ein Geldeingang kann eine Rückzahlung sein.")
        if t.rueckzahlung != body.rueckzahlung and "kategorie" not in felder:
            t.kategorie = None  # die Kategorien für Einnahmen und Ausgaben sind verschieden – neu wählen
        t.rueckzahlung = body.rueckzahlung
    if "contract_id" in felder:
        t.vertrag_fix = True  # die Erkennung ordnet diese Buchung nicht mehr um
        if body.contract_id is None:
            t.contract_id = None
        else:
            c = s.get(ContractRow, body.contract_id)
            if not c or c.entfernt:
                raise HTTPException(404, "Vertrag nicht gefunden")
            t.contract_id = c.id
            _vertrag_nachfuehren(c, t)
            if c.quelle == "manuell":
                # die übrigen Zahlungen dieser Art gehören auch dazu – jetzt und bei künftigen Abrufen
                c.muster = c.muster or muster(_to_dataclass(t))
                sync_contracts(s, ctx.today())
    s.commit()
    return _buchung_detail(s, t)


# ---------- Umbuchungen: Gegenbuchung auf dem anderen eigenen Konto ----------
class PaarIn(BaseModel):
    a: int
    b: int


def _paar_laden(s: Session, body: PaarIn) -> tuple[TransactionRow, TransactionRow]:
    a, b = s.get(TransactionRow, body.a), s.get(TransactionRow, body.b)
    if not a or not b:
        raise HTTPException(404, "Buchung nicht gefunden")
    return a, b


@router.get("/umbuchungen/fragen")
def umbuchungen_fragen(s: Session = Depends(get_db)):
    """Paare, bei denen BankPocket unsicher ist – zur Bestätigung."""
    return [{"sicherheit": p, "abgang": _kurz(s, a), "zugang": _kurz(s, b)} for p, a, b in umbuchungen.offene_fragen(s)]


@router.post("/umbuchungen")
def umbuchung_paaren(body: PaarIn, s: Session = Depends(get_db)):
    a, b = _paar_laden(s, body)
    if a.account_id == b.account_id or a.betrag != -b.betrag:
        raise HTTPException(422, "Eine Gegenbuchung liegt auf einem anderen Konto und hat denselben Betrag "
                                 "mit umgekehrtem Vorzeichen.")
    for t in (a, b):
        umbuchungen.loesen(s, t)  # eine frühere Zuordnung ersetzt die neue
    umbuchungen.paaren(a, b)
    s.commit()
    return _buchung_detail(s, a)


@router.post("/umbuchungen/ablehnen")
def umbuchung_ablehnen(body: PaarIn, s: Session = Depends(get_db)):
    """„Gehört nicht zusammen“ – dieses Paar wird nicht mehr vorgeschlagen."""
    a, b = _paar_laden(s, body)
    for t, gegen in ((a, b), (b, a)):
        t.paar_nein = ",".join(sorted({*(x for x in (t.paar_nein or "").split(",") if x), str(gegen.id)}))
    s.commit()
    return {"ok": True}


@router.delete("/umbuchungen/{buchung_id}", status_code=204)
def umbuchung_loesen(buchung_id: int, s: Session = Depends(get_db)):
    t = s.get(TransactionRow, buchung_id)
    if not t:
        raise HTTPException(404, "Buchung nicht gefunden")
    gegen = s.get(TransactionRow, t.gegenbuchung_id) if t.gegenbuchung_id else None
    umbuchungen.loesen(s, t)
    if gegen is not None:  # von Hand gelöst: der nächste Abruf verbindet die beiden nicht wieder
        for x, y in ((t, gegen), (gegen, t)):
            x.paar_nein = ",".join(sorted({*(i for i in (x.paar_nein or "").split(",") if i), str(y.id)}))
    s.commit()


@router.get("/buchungen/{buchung_id}/gegenbuchungen")
def gegenbuchungen(buchung_id: int, s: Session = Depends(get_db)):
    """Mögliche Gegenbuchungen zu dieser Buchung, die wahrscheinlichste zuerst."""
    t = s.get(TransactionRow, buchung_id)
    if not t:
        raise HTTPException(404, "Buchung nicht gefunden")
    return [{"sicherheit": p, **_kurz(s, r)} for p, r in umbuchungen.kandidaten(s, t)[:12]]


@router.post("/buchungen/{buchung_id}/erkennen")
def buchung_erkennen(buchung_id: int, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Die KI nach der Kategorie dieser einen Buchung fragen (gesendet: Name und gekürzter Verwendungszweck)."""
    from .. import ki
    t = s.get(TransactionRow, buchung_id)
    if not t:
        raise HTTPException(404, "Buchung nicht gefunden")
    try:
        kategorie = ki.einzeln_erkennen(ctx, s, t)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:  # noqa: BLE001 – verständliche Meldung statt 500
        s.rollback()
        raise HTTPException(502, ki.fehlertext(e)) from e
    if kategorie:
        if t.kategorie in ("Sonstiges", "Sonstige Einnahmen"):
            t.kategorie = None  # ein früheres bewusstes „Sonstiges“ weicht dem Ergebnis
        sync_contracts(s, ctx.today())
    s.commit()
    return {**_buchung_detail(s, t), "erkannt": kategorie}


@router.delete("/buchungen/{buchung_id}", status_code=204)
def buchung_loeschen(buchung_id: int, s: Session = Depends(get_db)):
    t = s.get(TransactionRow, buchung_id)
    if not t:
        raise HTTPException(404, "Buchung nicht gefunden")
    if s.get(Account, t.account_id).quelle != "manuell":
        raise HTTPException(400, "Nur selbst eingetragene Buchungen lassen sich löschen.")
    s.delete(t)
    s.commit()


@router.post("/buchungen/{buchung_id}/vertrag", status_code=201)
def buchung_als_vertrag(buchung_id: int, body: BuchungVertragIn, s: Session = Depends(get_db), ctx=Depends(get_ctx)):
    """Aus einer Buchung einen eigenen Vertrag machen – für alles, was die Erkennung nicht von selbst findet."""
    t = s.get(TransactionRow, buchung_id)
    if not t:
        raise HTTPException(404, "Buchung nicht gefunden")
    typ = "einnahme" if t.betrag > 0 else "ausgabe"
    name = (paypal_merchant(_to_dataclass(t)) or t.gegenpartei or t.verwendungszweck or "Vertrag").strip()[:200]
    c = ContractRow(name=name, turnus=body.turnus, erwarteter_betrag=t.betrag, typ=typ, quelle="manuell",
                    kategorie=t.kategorie or categorize(t.gegenpartei, t.verwendungszweck, typ, buchungstext=t.buchungstext),
                    letzte_zahlung=t.buchungsdatum, naechste_faelligkeit=naechster_termin(t.buchungsdatum, body.turnus),
                    bearbeitet=True, bestaetigt=True, muster=muster(_to_dataclass(t)))
    s.add(c)
    s.flush()
    t.contract_id = c.id
    sync_contracts(s, ctx.today())  # ältere und künftige Zahlungen derselben Art gehören dazu
    s.commit()
    return _buchung_detail(s, t)
