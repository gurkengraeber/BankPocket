"""Geschäftslogik zwischen Import, Erkennung und Datenbank."""
from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .contracts import (FALLBACK, PRICE_CHANGE_THRESHOLD, SCHWANKENDE_ERTRAEGE, SCHWANKUNG_MAX, TURNI, compute_status,
                        add_months, detect_contracts, muster, naechster_termin)
from .db import Account, Balance, ContractRow, Holding, Price, TransactionRow, kv_get
from .models import Transaction

GRUPPE_FUER_TYP = {
    "giro": "Tägliche Konten", "kreditkarte": "Tägliche Konten",
    "spar": "Sparkonten", "depot": "Sparkonten",
    "krypto": "Crypto", "virtuell": "Virtuell",
}
TURNUS_TEXT = {"woechentlich": "pro Woche", "zweiwoechentlich": "alle zwei Wochen", "vierwoechentlich": "alle vier Wochen",
               "halbmonatlich": "zweimal im Monat", "monatlich": "monatlich", "quartalsweise": "pro Quartal",
               "halbjaehrlich": "halbjährlich", "jaehrlich": "jährlich"}


def euro(betrag: Decimal) -> str:
    return f"{betrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def transaction_hash(account_id: int, t: Transaction, occurrence: int | str) -> str:
    """Gleiche Buchungen (z. B. zwei Kaffees am selben Tag) werden über den Zähler unterschieden.
    Überlappende Abrufe/Exporte liefern dieselben Hashes und werden so nicht doppelt gespeichert."""
    key = f"{account_id}|{t.buchungsdatum}|{t.betrag}|{t.gegenpartei}|{t.verwendungszweck}|{occurrence}"
    return hashlib.sha256(key.encode()).hexdigest()


def _extern_hash(account_id: int, extern_id: str) -> str:
    return hashlib.sha256(f"{account_id}|extern|{extern_id}".encode()).hexdigest()


def _extern_speichern(session: Session, account: Account, t: Transaction, existing: set[str]) -> int:
    """Buchung mit stabiler ID der Quelle: neu anlegen, aktualisieren oder entfernen."""
    h = _extern_hash(account.id, t.extern_id)
    row = session.scalar(select(TransactionRow).where(TransactionRow.hash == h)) if h in existing else None
    if t.geloescht:
        if row is not None:
            session.delete(row)
        return 0
    if row is not None:  # z. B. nachträglich geänderte Splitwise-Ausgabe
        row.buchungsdatum, row.betrag = t.buchungsdatum, t.betrag
        row.gegenpartei, row.verwendungszweck, row.buchungstext = t.gegenpartei, t.verwendungszweck, t.buchungstext
        row.rohdaten = t.rohdaten
        if not row.intern_fix:
            row.intern = t.intern
        row.kategorie = row.kategorie or t.kategorie or None
        return 0
    existing.add(h)
    session.add(TransactionRow(
        account_id=account.id, buchungsdatum=t.buchungsdatum, betrag=t.betrag, gegenpartei=t.gegenpartei,
        iban_gegenpartei=t.iban_gegenpartei, verwendungszweck=t.verwendungszweck, glaeubiger_id=t.glaeubiger_id,
        mandatsreferenz=t.mandatsreferenz, hash=h, rohdaten=t.rohdaten, buchungstext=t.buchungstext,
        kategorie=t.kategorie or None, intern=t.intern,
    ))
    return 1


def speichere_transaktionen(session: Session, account: Account, txs: list[Transaction],
                            eindeutig: bool = False) -> int:
    """Neue Buchungen speichern, Duplikate überspringen. eindeutig=True (manuelle Buchungen): nie Duplikat."""
    seen: Counter = Counter()
    neu = 0
    existing = set(session.scalars(select(TransactionRow.hash).where(TransactionRow.account_id == account.id)))
    for t in txs:
        if t.extern_id:
            neu += _extern_speichern(session, account, t, existing)
            continue
        ident = (t.buchungsdatum, t.betrag, t.gegenpartei, t.verwendungszweck)
        h = transaction_hash(account.id, t, uuid.uuid4().hex if eindeutig else seen[ident])
        seen[ident] += 1
        if h in existing:
            continue
        existing.add(h)
        session.add(TransactionRow(
            account_id=account.id, buchungsdatum=t.buchungsdatum, betrag=t.betrag, gegenpartei=t.gegenpartei,
            iban_gegenpartei=t.iban_gegenpartei, verwendungszweck=t.verwendungszweck,
            glaeubiger_id=t.glaeubiger_id, mandatsreferenz=t.mandatsreferenz, hash=h, rohdaten=t.rohdaten,
            buchungstext=t.buchungstext, kategorie=t.kategorie or None, intern=t.intern,
        ))
        neu += 1
    return neu


def saldo_setzen(session: Session, account: Account, datum: date, saldo: Decimal) -> None:
    snap = session.scalar(select(Balance).where(Balance.account_id == account.id, Balance.datum == datum))
    if snap:
        snap.saldo = saldo
    else:
        session.add(Balance(account_id=account.id, datum=datum, saldo=saldo))


def holdings_setzen(session: Session, account: Account, datum: date, holdings) -> None:
    session.execute(delete(Holding).where(Holding.account_id == account.id, Holding.datum == datum))
    for h in holdings:
        session.add(Holding(account_id=account.id, datum=datum, symbol=h.symbol or h.name[:20], name=(h.name or "")[:120],
                            einstand=getattr(h, "einstand", None),
                            menge=h.menge, kurs=h.kurs or Decimal(0), wert=h.wert))
        # Kursverlauf fortschreiben: geliefert von der Quelle, sonst wenigstens der heutige Kurs
        symbol = h.symbol or h.name[:20]
        kurse = dict(getattr(h, "kurse", None) or [])
        if h.kurs:
            kurse[datum] = h.kurs
        if kurse:
            session.execute(delete(Price).where(Price.symbol == symbol, Price.datum.in_(list(kurse))))
            session.add_all(Price(symbol=symbol, datum=tag, kurs=kurs) for tag, kurs in kurse.items())


VERLAUF_AB_KURSEN = 30  # ab so vielen Tageskursen gilt ein Verlauf als vorhanden
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}\d")


def wertpapiere_ohne_verlauf(session: Session, ausser_verbindung: int | None = None) -> list[str]:
    """ISINs aus Depots anderer Verbindungen, zu denen es (fast) keine Tageskurse gibt – ING und Consorsbank liefern
    nur den heutigen Kurs; den Verlauf holt der Abruf bei Trade Republic nach."""
    isins = set()
    for acc in session.scalars(select(Account).where(Account.typ == "depot", Account.aktiv)):
        if ausser_verbindung is not None and acc.connection_id == ausser_verbindung:
            continue
        stand = session.scalar(select(func.max(Holding.datum)).where(Holding.account_id == acc.id))
        if stand:
            isins.update(h.symbol for h in session.scalars(
                select(Holding).where(Holding.account_id == acc.id, Holding.datum == stand)) if h.menge > 0)
    return sorted(i for i in isins if _ISIN.fullmatch(i or "") and session.scalar(
        select(func.count()).select_from(Price).where(Price.symbol == i)) < VERLAUF_AB_KURSEN)


def kurse_ergaenzen(session: Session, symbol: str, punkte) -> None:
    """Fehlende Tageskurse nachtragen; vorhandene (vom Depot selbst gemeldete) bleiben stehen."""
    vorhanden = set(session.scalars(select(Price.datum).where(Price.symbol == symbol)))
    session.add_all(Price(symbol=symbol, datum=tag, kurs=kurs) for tag, kurs in dict(punkte).items()
                    if tag not in vorhanden)


AUSGLEICH_TAGE_VOR, AUSGLEICH_TAGE_NACH = 5, 1  # Überweisung geht bis zu 5 Tage vor der Gutschrift auf der Karte ab


_NAMENSTEILE = re.compile(r"[^\W\d_]+")


def eigene_namen(session: Session) -> list[list[str]]:
    """Die in den Einstellungen hinterlegten eigenen Namen, je Name als Liste kleingeschriebener Wörter.
    Ein Name passt, wenn alle seine Wörter in der Gegenpartei vorkommen („Mustermann, Max“ wie „Max Mustermann“)."""
    roh = kv_get(session, "eigene_namen") or ""
    return [w for w in (_NAMENSTEILE.findall(teil.lower()) for teil in re.split(r"[,;\n]", roh)) if w]


def markiere_interne_umbuchungen(session: Session) -> None:
    """Überweisungen zwischen eigenen Konten sind keine Ausgaben/Einnahmen."""
    eigene = {i for i in session.scalars(select(Account.iban)) if i}
    if eigene:
        session.execute(update(TransactionRow)
                        .where(TransactionRow.iban_gegenpartei.in_(eigene), TransactionRow.intern.is_(False),
                               TransactionRow.intern_fix.is_(False))
                        .values(intern=True))
    # Kreditkarten haben keine IBAN: Die Gegenseite eines Kartenausgleichs ist die Abbuchung in gleicher Höhe
    # auf einem anderen eigenen Konto kurz davor.
    karten = set(session.scalars(select(Account.id).where(Account.typ == "kreditkarte")))
    for gutschrift in session.scalars(select(TransactionRow).where(
            TransactionRow.account_id.in_(karten), TransactionRow.intern.is_(True), TransactionRow.betrag > 0)):
        gegenseiten = list(session.scalars(select(TransactionRow).where(
            TransactionRow.account_id.not_in(karten), TransactionRow.betrag == -gutschrift.betrag,
            TransactionRow.buchungsdatum >= gutschrift.buchungsdatum - timedelta(days=AUSGLEICH_TAGE_VOR),
            TransactionRow.buchungsdatum <= gutschrift.buchungsdatum + timedelta(days=AUSGLEICH_TAGE_NACH),
        ).order_by(TransactionRow.buchungsdatum.desc(), TransactionRow.id)))
        frei = [t for t in gegenseiten if not t.intern_fix]
        if frei and not any(t.intern for t in gegenseiten):
            frei[0].intern = True
    # Eigener Name als Gegenseite: Geld von oder zu einem eigenen Konto, auch wenn es nicht angebunden ist
    for woerter in eigene_namen(session):
        for t in session.scalars(select(TransactionRow).where(
                TransactionRow.intern.is_(False), TransactionRow.intern_fix.is_(False),
                func.lower(TransactionRow.gegenpartei).like(f"%{woerter[0]}%"))):
            if set(woerter) <= set(_NAMENSTEILE.findall((t.gegenpartei or "").lower())):
                t.intern = True
    from .umbuchungen import automatisch_paaren
    automatisch_paaren(session)  # sichere Paare Abgang/Zugang verbinden


def import_transactions(session: Session, account: Account, txs: list[Transaction],
                        today: date | None = None, eindeutig: bool = False) -> dict:
    """CSV-Import oder manuelle Buchung: speichern, Saldo übernehmen, Verträge neu erkennen, committen."""
    neu = speichere_transaktionen(session, account, txs, eindeutig)

    # Saldo-Snapshot aus der jüngsten Buchung (ING-CSV liefert den Saldo pro Zeile mit).
    with_saldo = [t for t in txs if t.saldo is not None]
    if with_saldo:
        latest_date = max(t.buchungsdatum for t in with_saldo)
        # Bei mehreren Buchungen am selben Tag steht die jüngste im Export oben.
        latest = next(t for t in with_saldo if t.buchungsdatum == latest_date)
        saldo_setzen(session, account, latest_date, latest.saldo)
    account.zuletzt_aktualisiert = datetime.now()
    markiere_interne_umbuchungen(session)
    session.flush()
    vertraege = sync_contracts(session, today)
    session.commit()
    return {"importiert": neu, "duplikate": len(txs) - neu, "vertraege": vertraege.als_dict()}


def _to_dataclass(r: TransactionRow) -> Transaction:
    return Transaction(r.buchungsdatum, r.betrag, r.gegenpartei, r.verwendungszweck,
                       r.iban_gegenpartei, r.glaeubiger_id, r.mandatsreferenz, kategorie=r.kategorie or "",
                       buchungstext=r.buchungstext)


# Nur auf diesen Konten gibt es Verträge – nicht bei Splitwise, Krypto, Depots oder Bargeld
VERTRAGS_KONTOTYPEN = ("giro", "kreditkarte", "spar")


@dataclass
class SyncErgebnis:
    neu: list[ContractRow] = field(default_factory=list)
    erhoeht: list[ContractRow] = field(default_factory=list)
    aktualisiert: int = 0

    def als_dict(self) -> dict:
        return {"neu": [c.name for c in self.neu], "aktualisiert": self.aktualisiert}


def sync_contracts(session: Session, today: date | None = None) -> SyncErgebnis:
    """Erkennung über alle Buchungen laufen lassen und mit der DB abgleichen.
    Nutzeränderungen (Name/Kategorie, Entfernen) bleiben erhalten."""
    today = today or date.today()
    rows = list(session.scalars(
        select(TransactionRow).join(Account).where(
            TransactionRow.intern.is_(False), Account.typ.in_(VERTRAGS_KONTOTYPEN), Account.quelle != "manuell")))
    by_obj = {}
    txs = []
    for r in rows:
        t = _to_dataclass(r)
        by_obj[id(t)] = r
        txs.append(t)

    existing = {c.schluessel: c for c in session.scalars(select(ContractRow).where(ContractRow.quelle == "auto"))}
    eigene = list(session.scalars(select(ContractRow).where(ContractRow.quelle == "manuell")))
    manuelle = {c.id for c in eigene}
    eigene_muster = _eigene_vertraege_fuellen(session, eigene, by_obj, txs)
    ergebnis, found = SyncErgebnis(), set()
    erkannt = [d for d in detect_contracts(txs, today)
               # sonst gehören diese Zahlungen schon zu einem selbst angelegten Vertrag
               if not any(_passt(d.schluessel, m) for m in eigene_muster)]
    schluessel_erkannt = {d.schluessel for d in erkannt}
    nach_id = {c.id: c for c in existing.values()}
    letzte_bisher = {c.id: c.letzte_zahlung for c in existing.values()}
    for d in erkannt:
        row = existing.get(d.schluessel)
        if row is None:
            # Die Kennung einer Gruppe kann wandern (neuer Betrag, andere Schreibweise). Gehören die Buchungen
            # schon überwiegend zu einem Vertrag, ist es derselbe – kein zweiter Vorschlag daneben.
            bisher = _bisheriger_vertrag(d, by_obj, nach_id)
            if bisher is not None and bisher.schluessel not in schluessel_erkannt:
                existing.pop(bisher.schluessel, None)
                bisher.schluessel = d.schluessel
                existing[d.schluessel] = row = bisher
            elif bisher is not None and bisher.gilt:
                continue  # die Zahlungen laufen als Nachzügler beim bestätigten Vertrag weiter
        found.add(d.schluessel)
        letzte = d.transaktionen[-1].buchungsdatum
        if row is None:
            row = ContractRow(schluessel=d.schluessel, quelle="auto", name=d.name, kategorie=d.kategorie)
            session.add(row)
            ergebnis.neu.append(row)
        else:
            ergebnis.aktualisiert += 1
            if row.entfernt:
                continue
        if not row.bearbeitet:
            row.name, row.kategorie = d.name, d.kategorie
        row.turnus, row.typ, row.methode = d.turnus, d.typ, d.methode
        row.erwarteter_betrag, row.vorkommen, row.sicherheit = d.erwarteter_betrag, d.vorkommen, d.sicherheit
        row.letzte_zahlung = letzte
        row.naechste_faelligkeit = d.naechste_faelligkeit
        row.betrag_gestiegen, row.vorheriger_betrag = d.betrag_gestiegen, d.vorheriger_betrag
        row.nicht_mehr_erkannt = False
        session.flush()
        for t in d.transaktionen:
            tr = by_obj[id(t)]
            if tr.vertrag_fix or (tr.contract_id and tr.contract_id != row.id and tr.contract_id in manuelle):
                continue  # vom Nutzer zugeordnet oder gelöst
            tr.contract_id = row.id
            if row.kategorie not in FALLBACK.values():  # „Sonstiges“ nicht festschreiben – bessere Regeln sollen greifen
                tr.kategorie = tr.kategorie or row.kategorie

    for key, row in existing.items():
        if key not in found:
            row.nicht_mehr_erkannt = True
    session.flush()
    aktive = [c for c in existing.values() if not c.entfernt]
    _zahlungen_nachfuehren(aktive, rows, by_obj, txs)
    # teurer geworden mit einer Zahlung, die seit dem letzten Abgleich dazugekommen ist
    ergebnis.erhoeht = [c for c in aktive if c.betrag_gestiegen and c.vorheriger_betrag is not None
                        and c.id in letzte_bisher and letzte_bisher[c.id] != c.letzte_zahlung]
    session.flush()
    return ergebnis


def _passt(schluessel: str | None, m: str) -> bool:
    """Gehört die Kennung eines Vertrags zum Muster (gleiche Gruppe, mit oder ohne Betrags-Anhang)?"""
    return bool(schluessel) and (schluessel == m or schluessel.startswith(m + "|"))


def _bisheriger_vertrag(d, by_obj: dict, nach_id: dict[int, ContractRow]) -> ContractRow | None:
    """Der erkannte Vertrag, dem diese Buchungen schon gehören: ein bestätigter, sobald er einen spürbaren Teil
    davon hält (er soll nie verwaisen, nur weil die Erkennung die Gruppe jetzt anders schneidet) – sonst der,
    dem die Mehrheit zugeordnet ist."""
    ids = Counter(by_obj[id(t)].contract_id for t in d.transaktionen)
    ids.pop(None, None)
    bestaetigte = [(n, cid) for cid, n in ids.items() if cid in nach_id and nach_id[cid].gilt and not nach_id[cid].entfernt
                   and n * 4 >= len(d.transaktionen)]
    if bestaetigte:
        return nach_id[max(bestaetigte)[1]]
    if not ids:
        return None
    cid, anzahl = ids.most_common(1)[0]
    return nach_id.get(cid) if anzahl * 2 > len(d.transaktionen) else None


def zahlung_anrechnen(c: ContractRow, r: TransactionRow) -> None:
    """Eine spätere Zahlung zählt für den Vertrag: letzte Zahlung, nächster Termin und – wenn der Betrag in etwa
    passt – der neue erwartete Betrag. Eine einmalig ganz andere Summe (Gutschrift, Nachzahlung) ändert ihn nicht."""
    if c.letzte_zahlung and r.buchungsdatum <= c.letzte_zahlung:
        return
    c.letzte_zahlung = r.buchungsdatum
    c.naechste_faelligkeit = naechster_termin(r.buchungsdatum, c.turnus)
    c.vorkommen = (c.vorkommen or 0) + 1
    alt, neu = abs(c.erwarteter_betrag), abs(r.betrag)
    vorher, c.betrag_gestiegen, c.vorheriger_betrag = c.erwarteter_betrag, False, None
    if (c.kategorie in SCHWANKENDE_ERTRAEGE or c.kategorie == "Lohn / Gehalt"
            or r.betrag * c.erwarteter_betrag <= 0 or abs(neu - alt) > alt * SCHWANKUNG_MAX):
        return
    c.erwarteter_betrag = r.betrag
    if abs(neu - alt) > alt * PRICE_CHANGE_THRESHOLD:
        c.betrag_gestiegen, c.vorheriger_betrag = neu > alt, vorher


def _zahlungen_nachfuehren(vertraege: list[ContractRow], rows: list[TransactionRow], by_obj: dict,
                           txs: list) -> None:
    """Die Erkennung sieht nur die gleichmäßige Reihe. Zahlungen danach mit anderem Betrag oder von einer anderen
    Karte gehören trotzdem zum Vertrag – sonst gilt er als überfällig, obwohl gezahlt wurde.
    Es zählen: von Hand zugeordnete Buchungen und, bei bestätigten Verträgen, Buchungen derselben Gruppe
    (gleicher Empfänger, gleiches Mandat …) rund um den erwarteten Termin."""
    muster_von = {id(by_obj[id(t)]): muster(t) for t in txs}
    zugeordnet: dict[int, list[TransactionRow]] = {}
    frei: dict[str, list[TransactionRow]] = {}
    for r in rows:
        if r.contract_id is not None:
            zugeordnet.setdefault(r.contract_id, []).append(r)
        elif not r.vertrag_fix and muster_von[id(r)]:
            frei.setdefault(muster_von[id(r)], []).append(r)

    kandidaten: dict[int, list[TransactionRow]] = {}
    gueltig = [c for c in vertraege if c.gilt and c.letzte_zahlung and not c.nicht_mehr_erkannt]
    for c in vertraege:
        if not c.letzte_zahlung:
            continue
        meine = sorted(zugeordnet.get(c.id, []), key=lambda r: r.buchungsdatum)
        for r in meine:
            zahlung_anrechnen(c, r)
        if c in gueltig:
            # woran Zahlungen dieses Vertrags zu erkennen sind: seine Gruppe und die der von Hand zugeordneten
            erkennbar = {m for m in frei if _passt(c.schluessel, m)} | {
                muster_von[id(r)] for r in meine if r.vertrag_fix and muster_von[id(r)] in frei}
            kandidaten[c.id] = [r for m in erkennbar for r in frei[m]]
    for c in gueltig:
        mitbewerber = [o for o in gueltig if o is not c]
        while True:
            faellig = naechster_termin(c.letzte_zahlung, c.turnus)
            toleranz = timedelta(days=TURNI[c.turnus][2])
            ab, bis = faellig - toleranz, naechster_termin(faellig, c.turnus) - toleranz
            passend = [r for r in kandidaten[c.id]
                       if r.contract_id is None and c.letzte_zahlung < r.buchungsdatum and ab <= r.buchungsdatum < bis
                       and r.betrag * c.erwarteter_betrag > 0
                       # laufen zwei bestätigte Verträge über denselben Empfänger, zählt der mit dem näheren Betrag
                       and not any(r in kandidaten[o.id] and abs(o.erwarteter_betrag - r.betrag)
                                   < abs(c.erwarteter_betrag - r.betrag) for o in mitbewerber)]
            if not passend:
                break
            r = min(passend, key=lambda r: (abs((r.buchungsdatum - faellig).days), r.buchungsdatum))
            r.contract_id = c.id
            if c.kategorie not in FALLBACK.values():
                r.kategorie = r.kategorie or c.kategorie
            zahlung_anrechnen(c, r)


def _eigene_vertraege_fuellen(session: Session, eigene: list[ContractRow], by_obj: dict, txs: list) -> set[str]:
    """Selbst angelegte Verträge sammeln alle Buchungen ein, die zu ihrem Muster passen – auch ältere und künftige.
    Fehlt das Muster noch, ergibt es sich aus der zuletzt von Hand zugeordneten Buchung."""
    session.flush()
    gruppen: dict[str, list] = {}
    for t in txs:
        m = muster(t)
        if m:
            gruppen.setdefault(m, []).append(by_obj[id(t)])
    for c in eigene:
        if c.muster or c.entfernt:
            continue
        zugeordnet = [(t, r) for t, r in ((t, by_obj[id(t)]) for t in txs) if r.contract_id == c.id]
        if zugeordnet:
            c.muster = muster(max(zugeordnet, key=lambda p: p[1].buchungsdatum)[0])
    for c in eigene:
        if not c.muster or c.entfernt:
            continue
        passend = gruppen.get(c.muster, [])
        for r in passend:
            if not r.vertrag_fix and (r.contract_id is None or r.contract_id not in {e.id for e in eigene}):
                r.contract_id = c.id
                if c.kategorie not in FALLBACK.values():
                    r.kategorie = r.kategorie or c.kategorie
        meine = sorted((r for r in passend if r.contract_id == c.id), key=lambda r: r.buchungsdatum)
        if meine:
            c.vorkommen = len({r.buchungsdatum for r in meine})
            if not c.letzte_zahlung or meine[-1].buchungsdatum >= c.letzte_zahlung:
                c.letzte_zahlung = meine[-1].buchungsdatum
                c.naechste_faelligkeit = max(c.naechste_faelligkeit, naechster_termin(c.letzte_zahlung, c.turnus))
    return {c.muster for c in eigene if c.muster and not c.entfernt}


def contract_status(c: ContractRow, today: date | None = None) -> tuple[str, int]:
    """Status zur Laufzeit, damit „X Tage überfällig“ auch ohne neuen Import stimmt."""
    today = today or date.today()
    if c.nicht_mehr_erkannt:
        return "inaktiv", 0
    if c.quelle == "manuell" or c.letzte_zahlung is None:
        return "aktiv", 0
    _, status, tage = compute_status(c.turnus, c.letzte_zahlung, today)
    return status, tage


def melde_vertragsereignisse(notifier, session: Session, erg: SyncErgebnis, heute: date, push: bool = True) -> None:
    for c in erg.neu:
        # Nur wirklich neue Verträge melden – nicht alles, was beim ersten Import der Historie auftaucht.
        if c.letzte_zahlung and (heute - c.letzte_zahlung).days <= 40:
            notifier.hinweis(session, "neuer_vertrag", f"Ist {c.name} ein Vertrag?",
                             f"{euro(abs(c.erwarteter_betrag))} {TURNUS_TEXT[c.turnus]} – bitte bestätigen oder ablehnen.",
                             link="#/vertraege", schluessel=f"neu|{c.id}", push=push)
    for c in erg.erhoeht:
        notifier.hinweis(session, "betrag_gestiegen", f"{c.name} ist teurer geworden",
                         f"{euro(abs(c.vorheriger_betrag))} → {euro(abs(c.erwarteter_betrag))}",
                         link=f"#/vertrag/{c.id}", schluessel=f"erhoehung|{c.id}|{c.letzte_zahlung}", push=push)


def pruefe_ueberfaellig(notifier, session: Session, heute: date, push: bool = True) -> None:
    for c in session.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False),
                                                       ContractRow.quelle == "auto")):
        status, tage = contract_status(c, heute)
        if status != "ueberfaellig" or not c.gilt:
            continue
        titel = f"{c.name}: Zahlung überfällig" if c.typ == "ausgabe" else f"{c.name}: Eingang überfällig"
        notifier.hinweis(session, "ueberfaellig", titel,
                         f"Erwartet am {c.naechste_faelligkeit:%d.%m.%Y} – seit {tage} Tagen offen.",
                         link=f"#/vertrag/{c.id}", schluessel=f"ueberfaellig|{c.id}|{c.naechste_faelligkeit}",
                         push=push)


FRIST_TEXT = {"tage": ("Tag", "Tage"), "wochen": ("Woche", "Wochen"), "monate": ("Monat", "Monate")}


def kuendigung(c: ContractRow, heute: date) -> dict | None:
    """Bis wann muss gekündigt sein – und zu wann endet der Vertrag dann?
    Mit Laufzeitende: Ende minus Frist; ist der Termin verpasst und der Vertrag verlängert sich, gilt die nächste
    Runde. Ohne Laufzeitende: jederzeit kündbar, der Vertrag endet nach Ablauf der Frist."""
    if not c.frist_wert and not c.laufzeit_bis:
        return None

    def vor(ende: date) -> date:
        if not c.frist_wert:
            return ende
        if c.frist_einheit == "monate":
            return add_months(ende, -c.frist_wert)
        return ende - timedelta(days=c.frist_wert * (7 if c.frist_einheit == "wochen" else 1))

    frist = (f"{c.frist_wert} {FRIST_TEXT.get(c.frist_einheit, FRIST_TEXT['tage'])[c.frist_wert != 1]}"
             if c.frist_wert else None)
    if not c.laufzeit_bis:
        nach = (add_months(heute, c.frist_wert) if c.frist_einheit == "monate"
                else heute + timedelta(days=c.frist_wert * (7 if c.frist_einheit == "wochen" else 1)))
        return {"frist": frist, "kuendigen_bis": None, "ende": nach, "tage": None, "jederzeit": True, "verpasst": False}
    ende, n = c.laufzeit_bis, 0
    while vor(ende) < heute and c.verlaengerung_monate and n < 600:
        ende, n = add_months(c.laufzeit_bis, (n + 1) * c.verlaengerung_monate), n + 1
    bis = vor(ende)
    return {"frist": frist, "kuendigen_bis": bis, "ende": ende, "tage": (bis - heute).days, "jederzeit": False,
            "verpasst": bis < heute}


def pruefe_kuendigungen(notifier, session: Session, heute: date, push: bool = True) -> None:
    """Wer einen Vertrag kündigen will, wird 30, 7 und 1 Tag vor dem letzten Termin erinnert (je einmal)."""
    for c in session.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False), ContractRow.kuendigen.is_(True))):
        if c.gekuendigt_zum:
            continue  # erledigt
        k = kuendigung(c, heute)
        if k is None or k["jederzeit"]:
            # jederzeit kündbar (oder nichts eingetragen): eine Woche vor der nächsten Abbuchung erinnern –
            # bei eingetragener Frist entsprechend früher, damit die Kündigung noch vor dieser Abbuchung greift
            bis = c.naechste_faelligkeit - ((k["ende"] - heute) if k else timedelta(0))
            if c.naechste_faelligkeit < heute or (bis - heute).days > 7:
                continue
            notifier.hinweis(session, "kuendigen", f"{c.name} kündigen",
                             f"Die nächste Abbuchung kommt am {c.naechste_faelligkeit:%d.%m.%Y}"
                             + (f" – Kündigungsfrist {k['frist']}." if k else "."),
                             link=f"#/vertrag/{c.id}", schluessel=f"kuendigen|{c.id}|{c.naechste_faelligkeit}", push=push)
            continue
        tage = k["tage"]
        if k["verpasst"] or tage > 30:
            continue
        stufe = 1 if tage <= 1 else 7 if tage <= 7 else 30
        wann = "heute" if tage == 0 else "morgen" if tage == 1 else f"in {tage} Tagen"
        notifier.hinweis(session, "kuendigen", f"{c.name}: Kündigung bis {k['kuendigen_bis']:%d.%m.%Y}",
                         f"Letzter Termin {wann} – sonst läuft der Vertrag bis {k['ende']:%d.%m.%Y}"
                         + (" weiter." if c.verlaengerung_monate else "."),
                         link=f"#/vertrag/{c.id}", schluessel=f"kuendigen|{c.id}|{k['kuendigen_bis']}|{stufe}", push=push)


def account_saldo(session: Session, account: Account) -> Decimal | None:
    if account.quelle == "manuell":  # manuelle Konten: Saldo = Summe der Buchungen
        betraege = session.scalars(select(TransactionRow.betrag).where(TransactionRow.account_id == account.id))
        return sum(betraege, Decimal(0))
    snap = session.scalar(select(Balance).where(Balance.account_id == account.id)
                          .order_by(Balance.datum.desc()).limit(1))
    return snap.saldo if snap else None
