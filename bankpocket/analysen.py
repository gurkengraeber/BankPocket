"""Auswertungen für Übersicht und Analysen."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import FALLBACK, NICHT_AUSGABEN, add_months, categorize, naechster_termin
from .db import Account, Balance, Budget, ContractRow, TransactionRow, oberkategorien
from . import zahltag
from .service import contract_status, euro


def _tage(start: date, ende: date):
    d = start
    while d <= ende:
        yield d
        d += timedelta(days=1)


TEMPO_TAGE = 90  # Zeitraum für das übliche Ausgabentempo


GEHALT_ARTEN = ("einnahmen", "vertraege", "sparen", "sonstige", "ausgeschlossen")
GEHALT_AUSGABEN = ("vertraege", "sparen", "sonstige")


def _gehaltsvertrag(s: Session, heute: date) -> ContractRow | None:
    kandidaten = [c for c in s.scalars(select(ContractRow).where(ContractRow.typ == "einnahme",
                                                                ContractRow.entfernt.is_(False)))
                  if c.kategorie == "Lohn / Gehalt" and c.letzte_zahlung
                  and contract_status(c, heute)[0] != "inaktiv"]
    return max(kandidaten, key=lambda c: c.erwarteter_betrag) if kandidaten else None


def _taegliche_konten(s: Session) -> list[int]:
    return list(s.scalars(select(Account.id).where(Account.gruppe == "Tägliche Konten", Account.aktiv.is_(True))))


def gehaltsmonat_buchungen(s: Session, start: date, ende: date | None = None) -> dict[str, list[TransactionRow]]:
    """Die Buchungen eines Gehaltsmonats (ab Gehaltseingang, bis vor dem nächsten) in vier Töpfen:
    Einnahmen, Verträge, Sparen, sonstige Ausgaben – plus die vom Nutzer ausgeschlossenen."""
    q = select(TransactionRow).where(TransactionRow.account_id.in_(_taegliche_konten(s)),
                                     TransactionRow.buchungsdatum >= start, TransactionRow.intern.is_(False))
    if ende:
        q = q.where(TransactionRow.buchungsdatum < ende)
    gueltig = {c.id for c in s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False))) if c.gilt}
    toepfe: dict[str, list[TransactionRow]] = {art: [] for art in GEHALT_ARTEN}
    anteil = anteile(s)
    for t in s.scalars(q.order_by(TransactionRow.buchungsdatum.desc(), TransactionRow.id.desc())):
        _eigener(t, anteil)
        if t.ausgeschlossen:
            toepfe["ausgeschlossen"].append(t)
        elif _kategorie(t) in NICHT_AUSGABEN:  # Kauf fürs Depot – oder ein Verkauf, der das Gesparte mindert
            toepfe["sparen"].append(t)
        elif t.betrag > 0:
            toepfe["sonstige" if t.rueckzahlung else "einnahmen"].append(t)  # Rückzahlung mindert die Ausgaben
        else:
            toepfe["vertraege" if t.contract_id in gueltig else "sonstige"].append(t)
    return toepfe


def _summen(toepfe: dict[str, list[TransactionRow]]) -> dict[str, Decimal]:
    summe = lambda art: sum((getattr(t, "mein_betrag", t.betrag) for t in toepfe[art]), Decimal(0))  # noqa: E731
    return {"einnahmen": summe("einnahmen"), "vertraege": -summe("vertraege"), "sparen": -summe("sparen"),
            "sonstige": -summe("sonstige")}


def gehalt_offen(s: Session, g: ContractRow, naechste: date, heute: date) -> dict[str, list[dict]]:
    """Was bis zum nächsten Gehalt noch erwartet wird: fällige Verträge und Sparpläne, dazu weitere regelmäßige
    Eingänge (nicht das Gehalt selbst)."""
    offen: dict[str, list[dict]] = {"einnahmen": [], "vertraege": [], "sparen": []}
    for c in s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False))):
        status, _ = contract_status(c, heute)
        if (c.id == g.id or not c.gilt or status == "inaktiv"
                or c.naechste_faelligkeit >= max(naechste, heute + timedelta(days=1))):
            continue
        if c.typ == "einnahme":
            if c.naechste_faelligkeit >= heute:  # ein ausgebliebener Eingang wird nicht einfach mitgerechnet
                offen["einnahmen"].append({"id": c.id, "name": c.name, "kategorie": c.kategorie,
                                           "betrag": abs(c.erwarteter_betrag), "datum": c.naechste_faelligkeit})
            continue
        if c.naechste_faelligkeit >= heute or status == "ueberfaellig":
            # wöchentliche Verträge werden bis zum Gehalt mehrmals fällig
            k, termin = 0, c.naechste_faelligkeit
            while k == 0 or termin < naechste:
                if c.gekuendigt_zum and termin > c.gekuendigt_zum:
                    break  # gekündigt: danach geht nichts mehr ab
                offen["sparen" if c.kategorie in NICHT_AUSGABEN else "vertraege"].append(
                    {"id": c.id, "name": c.name, "kategorie": c.kategorie, "betrag": abs(c.mein_betrag),
                     "datum": termin})
                k += 1
                termin = naechster_termin(c.naechste_faelligkeit, c.turnus, k)
    for liste in offen.values():
        liste.sort(key=lambda p: p["datum"])
    return offen


def gehalt_karte(s: Session, heute: date) -> dict | None:
    """„Frei verfügbar“: Einnahmen seit dem Gehaltseingang minus Verträge, Sparen und sonstige
    Ausgaben – bei Verträgen und Sparplänen auch das, was bis zum nächsten Gehalt noch abgeht.
    Dazu: Betrag pro Tag und eine Prognose mit dem üblichen Ausgabentempo."""
    g = _gehaltsvertrag(s, heute)
    if g is None:
        return None
    zahltage = list(s.scalars(select(TransactionRow.buchungsdatum).where(TransactionRow.contract_id == g.id)))
    muster = zahltag.muster_erkennen(zahltage)
    naechste = zahltag.naechster_zahltag(zahltage) or g.naechste_faelligkeit
    verspaetet = naechste < heute  # erwartet, aber noch nicht eingegangen
    konten = _taegliche_konten(s)
    toepfe = gehaltsmonat_buchungen(s, g.letzte_zahlung)
    gebucht, offen = _summen(toepfe), gehalt_offen(s, g, naechste, heute)
    offen_summe = {art: sum((p["betrag"] for p in posten), Decimal(0)) for art, posten in offen.items()}
    detail = {"einnahmen": gebucht["einnahmen"] + offen_summe["einnahmen"],
              "vertraege": gebucht["vertraege"] + offen_summe["vertraege"],
              "sparen": gebucht["sparen"] + offen_summe["sparen"], "sonstige": gebucht["sonstige"]}
    ausgaben = detail["vertraege"] + detail["sparen"] + detail["sonstige"]
    verfuegbar = detail["einnahmen"] - ausgaben
    ausstehend = offen_summe["vertraege"] + offen_summe["sparen"]
    posten = offen["vertraege"] + offen["sparen"]
    tage = max((naechste - heute).days, 0)

    # Übliches Tempo der Alltagsausgaben (ohne Verträge, Umbuchungen, Sparen) – für die Prognose
    seit = heute - timedelta(days=TEMPO_TAGE)
    alltag = [t for t in s.scalars(select(TransactionRow).where(
        TransactionRow.account_id.in_(konten), TransactionRow.buchungsdatum > seit,
        TransactionRow.buchungsdatum <= heute, TransactionRow.betrag < 0, TransactionRow.intern.is_(False),
        TransactionRow.contract_id.is_(None)))
        if _kategorie(t) not in NICHT_AUSGABEN and not t.ausgeschlossen]
    # Was daneben hereinkommt (Erstattungen, Freunde zahlen ihren Anteil zurück), gehört dagegengerechnet – sonst
    # zählt durchgereichtes Geld voll als Ausgabe und die Prognose rutscht weit ins Minus.
    manuell = set(s.scalars(select(Account.id).where(Account.quelle == "manuell")))
    eingaenge = [t for t in s.scalars(select(TransactionRow).where(
        TransactionRow.account_id.in_(konten), TransactionRow.buchungsdatum > seit,
        TransactionRow.buchungsdatum <= heute, TransactionRow.betrag > 0, TransactionRow.intern.is_(False),
        TransactionRow.contract_id.is_(None)))
        if t.account_id not in manuell and _kategorie(t) not in NICHT_AUSGABEN and not t.ausgeschlossen]
    erste = min((t.buchungsdatum for t in alltag), default=heute)
    netto = -sum((t.betrag for t in alltag), Decimal(0)) - sum((t.betrag for t in eingaenge), Decimal(0))
    tempo = max(netto, Decimal(0)) / max((heute - erste).days + 1, 30) if alltag else Decimal(0)
    anteil = max(Decimal(0), min(Decimal(1), verfuegbar / g.erwarteter_betrag)) if g.erwarteter_betrag else 0
    return {"name": g.name, "betrag": g.erwarteter_betrag, "datum": naechste, "tage": tage, "start": g.letzte_zahlung,
            "verspaetet": verspaetet, "rhythmus": zahltag.beschreibung(muster),
            "verfuegbar": verfuegbar, "ausstehend": ausstehend, "ausgaben": ausgaben, "detail": detail,
            "offen": offen_summe, "ausgeschlossen": len(toepfe["ausgeschlossen"]),
            "posten": sorted(posten, key=lambda p: p["datum"]),
            "pro_tag": (verfuegbar / tage).quantize(Decimal("0.01")) if tage and verfuegbar > 0 else None,
            "prognose": (verfuegbar - tempo * tage).quantize(Decimal("1")) if tage and len(alltag) >= 5 else None,
            "tempo_pro_tag": tempo.quantize(Decimal("0.01")),
            "anteil": float(anteil)}


def gehalt_verlauf(s: Session, heute: date, anzahl: int = 6) -> list[dict]:
    """Die abgeschlossenen Gehaltsmonate davor: was jeweils am Ende übrig blieb."""
    g = _gehaltsvertrag(s, heute)
    if g is None:
        return []
    tage: list[date] = []
    for d in sorted(set(s.scalars(select(TransactionRow.buchungsdatum).where(TransactionRow.contract_id == g.id)))):
        if not tage or (d - tage[-1]).days >= 20:  # Nachzahlungen kurz nach dem Gehalt sind kein neuer Monat
            tage.append(d)
    verlauf = []
    for start, ende in list(zip(tage, tage[1:]))[-anzahl:]:
        m = _summen(gehaltsmonat_buchungen(s, start, ende))
        ausgaben = m["vertraege"] + m["sparen"] + m["sonstige"]
        verlauf.append({"start": start, "ende": ende, "einnahmen": m["einnahmen"], "ausgaben": ausgaben,
                        "frei": m["einnahmen"] - ausgaben})
    return verlauf


def konto_verlauf(s: Session, acc: Account, start: date, ende: date) -> dict[date, Decimal]:
    """Tägliche Salden eines Kontos. Bankkonten werden vom letzten bekannten Saldo aus über die Umsätze
    zurückgerechnet; Depots nutzen ihre Snapshots; manuelle Konten summieren ihre Buchungen."""
    snaps = list(s.execute(select(Balance.datum, Balance.saldo).where(Balance.account_id == acc.id)
                           .order_by(Balance.datum)))
    txs = list(s.execute(select(TransactionRow.buchungsdatum, TransactionRow.betrag)
                         .where(TransactionRow.account_id == acc.id)))
    tage = list(_tage(start, ende))
    if acc.typ == "depot" or (snaps and not txs):
        # Vor dem ersten Snapshot ist nichts bekannt – den ersten Wert annehmen statt eines Sprungs von 0 auf
        # den vollen Depotwert am Tag der Einrichtung.
        out, i, letzter = {}, 0, (snaps[0][1] if snaps else None)
        for d in tage:
            while i < len(snaps) and snaps[i][0] <= d:
                letzter = snaps[i][1]
                i += 1
            if letzter is not None:
                out[d] = letzter
        if acc.typ == "depot" and snaps and acc.connection_id:
            # Vor dem ersten Snapshot: Käufe und Verkäufe vom Verrechnungskonto derselben Verbindung zurückrechnen
            # (zum Kaufpreis, ohne Kursbewegung) – sonst sähe es aus, als wäre das Depot schon immer voll gewesen.
            erster_tag, erster_wert = snaps[0]
            kaeufe = list(s.execute(select(TransactionRow.buchungsdatum, TransactionRow.betrag).join(Account).where(
                Account.connection_id == acc.connection_id, Account.id != acc.id,
                TransactionRow.kategorie == "Sparen", TransactionRow.buchungsdatum <= erster_tag)))
            if kaeufe:
                for d in tage:
                    if d < erster_tag:
                        danach = sum((-b for tag, b in kaeufe if tag > d), Decimal(0))
                        out[d] = max(erster_wert - danach, Decimal(0))
        return out
    if not txs:
        return {}
    if not snaps and acc.quelle != "manuell":
        # CSV-Konto ohne eingetragenen Stand: Die Summe der importierten Buchungen ist kein Kontostand.
        # Bis ein Stand eingetragen ist, zählt das Konto nicht zum Vermögen – wie in der Übersicht.
        return {}
    delta: dict[date, Decimal] = defaultdict(Decimal)
    laufend = Decimal(0)
    for d, b in txs:
        if d < start:
            laufend += b
        else:
            delta[d] += b
    kumuliert = {}
    for d in tage:
        laufend += delta.get(d, Decimal(0))
        kumuliert[d] = laufend
    if snaps and acc.quelle != "manuell":
        anker_datum, anker_saldo = snaps[-1]
        bis_anker = sum((b for d, b in txs if d <= anker_datum), Decimal(0))
        return {d: anker_saldo + kumuliert[d] - bis_anker for d in tage}
    if acc.quelle == "manuell":
        # Ein eingetragener Anfangsstand (Bargeld, Wallet, Splitwise) war schon vorher da – er ist kein Zugewinn
        # am Tag des Eintragens. Bis dahin gilt deshalb dieser erste Stand.
        erste = s.execute(select(TransactionRow.buchungsdatum, TransactionRow.betrag, TransactionRow.gegenpartei)
                          .where(TransactionRow.account_id == acc.id)
                          .order_by(TransactionRow.buchungsdatum, TransactionRow.id).limit(1)).first()
        if erste and erste[2] == "Stand angepasst":
            for d in tage:
                if d < erste[0]:
                    kumuliert[d] = erste[1]
    return kumuliert


def vermoegen(s: Session, heute: date, tage: int = 365) -> dict:
    start = heute - timedelta(days=tage)
    summe: dict[date, Decimal] = defaultdict(Decimal)
    for acc in s.scalars(select(Account).where(Account.aktiv.is_(True))):
        for d, w in konto_verlauf(s, acc, start, heute).items():
            summe[d] += w
    tage_mit_daten = [d for d in _tage(start, heute) if d in summe]
    schritt = 7 if tage > 400 else 1
    auswahl = tage_mit_daten[::schritt]
    if tage_mit_daten and auswahl[-1] != tage_mit_daten[-1]:
        auswahl.append(tage_mit_daten[-1])
    punkte = [{"d": d.isoformat(), "w": float(summe[d])} for d in auswahl]

    prognose = []
    if len(tage_mit_daten) >= 30:
        fenster = tage_mit_daten[-min(90, len(tage_mit_daten)):]
        pro_tag = (summe[fenster[-1]] - summe[fenster[0]]) / max((fenster[-1] - fenster[0]).days, 1)
        letzter = tage_mit_daten[-1]
        prognose = [{"d": (letzter + timedelta(days=n)).isoformat(),
                     "w": float(summe[letzter] + pro_tag * n)} for n in range(0, 91, 7)]
    erster = summe[tage_mit_daten[0]] if tage_mit_daten else Decimal(0)
    aktuell = summe[tage_mit_daten[-1]] if tage_mit_daten else Decimal(0)
    return {"punkte": punkte, "prognose": prognose, "aktuell": aktuell, "veraenderung": aktuell - erster,
            "veraenderung_prozent": float((aktuell - erster) / abs(erster)) if erster else None}


def _kategorie(t: TransactionRow) -> str:
    if t.betrag > 0 and t.rueckzahlung:  # gehört zu den Ausgaben – ohne gewählte Kategorie zu „Sonstiges“
        return t.kategorie or FALLBACK["ausgabe"]
    return t.kategorie or categorize(t.gegenpartei, t.verwendungszweck, "einnahme" if t.betrag > 0 else "ausgabe",
                                     buchungstext=t.buchungstext)


def anteile(s: Session) -> dict[int, Decimal]:
    """Verträge, die man sich teilt: Vertrag → eigener Anteil (0–1). Ihre Buchungen zählen überall nur anteilig."""
    return {c.id: Decimal(c.anteil_prozent) / 100
            for c in s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False), ContractRow.typ == "ausgabe"))
            if c.gilt and (c.anteil_prozent or 100) < 100}


def _eigener(t: TransactionRow, anteil: dict[int, Decimal]) -> Decimal:
    """Der eigene Teil einer Buchung; merkt ihn an der Buchung, damit Listen ihn anzeigen können."""
    t.mein_betrag = t.betrag * anteil[t.contract_id] if t.contract_id in anteil and t.betrag < 0 else t.betrag
    return t.mein_betrag


def _monatssummen(s: Session, start: date, ende: date) -> dict:
    rows = s.scalars(select(TransactionRow).join(Account).where(
        TransactionRow.buchungsdatum >= start, TransactionRow.buchungsdatum < ende,
        TransactionRow.intern.is_(False), TransactionRow.ausgeschlossen.is_(False), Account.typ != "depot"))
    anteil = anteile(s)
    konten = list(s.scalars(select(Account)))
    manuell = {a.id for a in konten if a.quelle == "manuell"}
    splitwise = {a.id for a in konten if a.quelle == "splitwise"}
    # Wer ein Bargeld-Konto führt, trägt Barausgaben dort ein – Abhebungen sind dann nur Umbuchungen.
    bargeld_konto = any(a.quelle == "manuell" and a.aktiv and "bargeld" in a.name.lower() for a in konten)
    einnahmen = ausgaben = gespart = Decimal(0)
    kategorien: dict[str, list] = defaultdict(lambda: [Decimal(0), 0])
    belege: list[tuple[TransactionRow, str, str]] = []  # (Buchung, einnahme|ausgabe|gespart, Kategorie) – zum Nachsehen
    for t in rows:
        if t.account_id in splitwise:
            # Splitwise korrigiert die Bankbuchungen: +40 (andere schulden dir ihren Anteil) senkt deine Ausgaben,
            # −25 (jemand hat für dich gezahlt) erhöht sie. Ein erhaltener Ausgleich hebt die Gutschrift auf.
            if t.buchungstext == "Ausgleich" and t.betrag < 0:
                einnahmen += t.betrag
                belege.append((t, "einnahme", "Ausgleich"))
            else:
                kat = t.kategorie or categorize(t.verwendungszweck, "", "ausgabe")
                ausgaben -= t.betrag
                kategorien[kat][0] -= t.betrag
                belege.append((t, "ausgabe", kat))
            continue
        if t.betrag > 0:
            if t.account_id in manuell:  # Einzahlungen/Bestände auf manuellen Konten sind kein Einkommen
                continue
            if t.kategorie in NICHT_AUSGABEN:  # Verkauf aus dem Depot: weniger gespart, kein Einkommen
                gespart -= t.betrag
                belege.append((t, "gespart", t.kategorie))
            elif t.rueckzahlung:  # Geld kam zurück: mindert die Ausgaben seiner Kategorie, ist kein Einkommen
                kat = _kategorie(t)
                ausgaben -= t.betrag
                kategorien[kat][0] -= t.betrag
                belege.append((t, "ausgabe", kat))
            else:
                einnahmen += t.betrag
                belege.append((t, "einnahme", _kategorie(t)))
            continue
        kat = _kategorie(t)
        if kat == "Bargeld" and bargeld_konto and t.account_id not in manuell:
            continue
        betrag = _eigener(t, anteil)
        if kat in NICHT_AUSGABEN:
            gespart -= betrag
            belege.append((t, "gespart", kat))
            continue
        ausgaben -= betrag
        kategorien[kat][0] -= betrag
        kategorien[kat][1] += 1
        belege.append((t, "ausgabe", kat))
    return {"einnahmen": einnahmen, "ausgaben": ausgaben, "gespart": gespart, "kategorien": kategorien,
            "belege": belege, "eltern": oberkategorien(s)}


def _gebuendelt(kategorien: dict[str, list], eltern: dict[str, str]) -> dict[str, list]:
    """Summen je Oberkategorie: {Oberkategorie: [Summe, Anzahl, {Unterkategorie: [Summe, Anzahl]}]}."""
    oben: dict[str, list] = {}
    for k, v in kategorien.items():
        ziel = oben.setdefault(eltern.get(k, k), [Decimal(0), 0, {}])
        ziel[0] += v[0]
        ziel[1] += v[1]
        if k in eltern:
            ziel[2][k] = [v[0], v[1]]
    return oben


def monats_buchungen(s: Session, monat: date, art: str, kategorie: str | None = None,
                     tag: str | None = None, monate: int = 1, steuern: bool = False,
                     steuerliste: bool = False) -> list[TransactionRow]:
    """Die Buchungen hinter einer Monatszahl – genau die, die in Einnahmen, Ausgaben oder Gespart eingerechnet sind.
    monate=12 ab dem 1. Januar ergibt die Buchungen hinter einer Jahreszahl."""
    start = monat.replace(day=1)
    m = _monatssummen(s, start, add_months(start, monate))
    belege, eltern = m["belege"], m["eltern"]
    treffer = [t for t, a, k in belege if a == art and (kategorie is None or kategorie in (k, eltern.get(k)))
               and (tag is None or tag in (t.tags or "").split(",")) and (not steuern or ist_steuer(t))
               and not (steuerliste and t.steuer == "nein")]
    return sorted(treffer, key=lambda t: (t.buchungsdatum, t.id), reverse=True)


def monats_analyse(s: Session, monat: date, verlauf_bis: date | None = None) -> dict:
    """verlauf_bis: letzter Monat der Balken – bleibt beim Blättern stehen, solange der gewählte Monat hineinpasst."""
    start = monat.replace(day=1)
    m = _monatssummen(s, start, add_months(start, 1))
    ende = max(start, min(verlauf_bis.replace(day=1), add_months(start, 5))) if verlauf_bis else start
    return {"monat": start.strftime("%Y-%m"), **_auswertung(m),
            "verlauf": _verlauf(s, [add_months(ende, -i) for i in range(5, -1, -1)])}


def _verlauf(s: Session, monate: list[date]) -> list[dict]:
    verlauf = []
    for ms in monate:
        v = _monatssummen(s, ms, add_months(ms, 1))
        verlauf.append({"monat": ms.strftime("%Y-%m"), "einnahmen": v["einnahmen"], "ausgaben": v["ausgaben"],
                        "gespart": v["gespart"]})
    return verlauf


def _auswertung(m: dict) -> dict:
    """Summen, Kategorien und Tags eines Zeitraums – gleich für Monat und Jahr."""
    kategorien = sorted(
        ({"kategorie": k, "summe": v[0], "anzahl": v[1],
          "anteil": float(v[0] / m["ausgaben"]) if m["ausgaben"] > 0 else 0.0,
          # Unterkategorien zählen oben mit und stehen hier einzeln
          "unter": sorted(({"kategorie": u, "summe": w[0], "anzahl": w[1]} for u, w in v[2].items() if w[0] > 0),
                          key=lambda x: -x["summe"])}
         for k, v in _gebuendelt(m["kategorien"], m["eltern"]).items() if v[0] > 0),
        key=lambda x: -x["summe"])
    # Ausgaben je Tag (eine Buchung kann mehrere Tags tragen und zählt dann bei jedem)
    je_tag: dict[str, list] = defaultdict(lambda: [Decimal(0), 0])
    for t, art, _ in m["belege"]:
        if art == "ausgabe":
            for tag in (x for x in (t.tags or "").split(",") if x):
                je_tag[tag][0] -= getattr(t, "mein_betrag", t.betrag)
                je_tag[tag][1] += 1
    tags = sorted(({"tag": k, "summe": v[0], "anzahl": v[1]} for k, v in je_tag.items()), key=lambda x: -x["summe"])
    return {"einnahmen": m["einnahmen"], "ausgaben": m["ausgaben"], "gespart": m["gespart"],
            "kategorien": kategorien, "tags": tags}


# Was in der Steuererklärung typischerweise eine Rolle spielt – als Liste zum Nachschlagen, keine Steuerberatung
STEUER_KATEGORIEN = ("Spenden", "Mitgliedschaft", "Versicherung")
# Zahlungen ans Finanzamt und andere Steuern: sicher erkannt an der Behörde als Empfänger oder Absender …
STEUER_BEHOERDEN = ("finanzamt", "bundeskasse", "hauptzollamt", "landeshauptkasse", "steuerkasse", "steueramt")
# … bei Ausgaben auch an einer genannten Steuer („Kfz-Steuer“, „Grundsteuer“) – als ganzes Wort, damit
# „steuerfrei“, „Steuerberater“ oder „Steuerung“ nicht zählen
_RE_STEUERART = re.compile(r"\b[\wäöüß-]*steuer\b", re.I)


def ist_steuer(t: TransactionRow) -> bool:
    if t.steuer:  # vom Nutzer festgelegt
        return t.steuer == "ja"
    text = f"{t.gegenpartei} {t.verwendungszweck}".lower()
    if any(w in text for w in STEUER_BEHOERDEN):
        return True
    # eine Gutschrift mit dem Wort „Steuer“ ist noch keine Erstattung (Bankprämie „… steuerfrei“, Zinsabrechnung)
    return t.betrag < 0 and bool(_RE_STEUERART.search(text))


def jahres_analyse(s: Session, jahr: int) -> dict:
    """Wie die Monatsanalyse, nur fürs ganze Jahr: zwölf Monatsbalken, Vergleich zum Vorjahr und eine Liste der
    Spenden, Beiträge und Versicherungen je Empfänger."""
    start = date(jahr, 1, 1)
    m = _monatssummen(s, start, date(jahr + 1, 1, 1))
    vor = _monatssummen(s, date(jahr - 1, 1, 1), start)
    je_empfaenger: dict[str, dict[str, list]] = {k: defaultdict(lambda: [Decimal(0), 0]) for k in STEUER_KATEGORIEN}
    for t, art, kat in m["belege"]:
        kat = m["eltern"].get(kat, kat)
        if art == "ausgabe" and kat in je_empfaenger and t.steuer != "nein":  # „nein“: vom Nutzer aus der Liste genommen
            name = (t.gegenpartei or t.verwendungszweck or "Unbekannt").strip()
            je_empfaenger[kat][name][0] -= getattr(t, "mein_betrag", t.betrag)
            je_empfaenger[kat][name][1] += 1
    def gruppe(titel: str, je: dict[str, list], **mehr) -> dict:
        return {"kategorie": titel, "summe": sum((v[0] for v in je.values()), Decimal(0)),
                "empfaenger": sorted(({"name": n, "summe": v[0], "anzahl": v[1]} for n, v in je.items()),
                                     key=lambda x: -x["summe"]), **mehr}

    steuer = [gruppe(k, e) for k, e in je_empfaenger.items() if e]
    # Steuern selbst: was ans Finanzamt ging – und was zurückkam
    for titel, art, vz in (("Steuerzahlungen", "ausgabe", -1), ("Steuererstattungen", "einnahme", 1)):
        je: dict[str, list] = defaultdict(lambda: [Decimal(0), 0])
        for t, a, _ in m["belege"]:
            if a == art and ist_steuer(t):
                name = (t.gegenpartei or t.verwendungszweck or "Unbekannt").strip()
                je[name][0] += vz * getattr(t, "mein_betrag", t.betrag)
                je[name][1] += 1
        if je:
            steuer.append(gruppe(titel, je, steuern=True, art=art))
    hat_vorjahr = bool(vor["belege"])
    return {"jahr": jahr, "monat": None, **_auswertung(m),
            "verlauf": _verlauf(s, [date(jahr, i, 1) for i in range(1, 13)]),
            "vorjahr": {"einnahmen": vor["einnahmen"], "ausgaben": vor["ausgaben"], "gespart": vor["gespart"]}
            if hat_vorjahr else None,
            "steuer": steuer}


def kategorien_verlauf(s: Session, heute: date, monate: int = 12) -> dict:
    """Ausgaben je Kategorie über die letzten Monate – wie entwickelt sich z. B. „Lebensmittel“?"""
    start = heute.replace(day=1)
    anfaenge = [add_months(start, -i) for i in range(monate - 1, -1, -1)]
    werte: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0)] * monate)
    for i, ms in enumerate(anfaenge):
        m = _monatssummen(s, ms, add_months(ms, 1))
        for k, v in _gebuendelt(m["kategorien"], m["eltern"]).items():
            werte[k][i] = max(v[0], Decimal(0))
    volle = max(monate - 1, 1)  # der laufende Monat ist noch nicht fertig und zählt nicht in den Schnitt
    return {"monate": [m.strftime("%Y-%m") for m in anfaenge],
            "kategorien": sorted(({"kategorie": k, "werte": w, "summe": sum(w, Decimal(0)),
                                   "schnitt": sum(w[:-1] if monate > 1 else w, Decimal(0)) / volle}
                                  for k, w in werte.items() if sum(w) > 0), key=lambda x: -x["summe"])}


def sparen(s: Session, heute: date, fenster: int = 6) -> dict:
    """Sparquote (was vom Einkommen übrig bleibt), angelegtes Geld und Sparpläne – für den Reiter „Sparen“.
    fenster: über wie viele volle Monate der Schnitt läuft."""
    start = heute.replace(day=1)
    verlauf = []
    for ms in (add_months(start, -i) for i in range(11, -1, -1)):
        v = _monatssummen(s, ms, add_months(ms, 1))
        uebrig = v["einnahmen"] - v["ausgaben"]
        verlauf.append({"monat": ms.strftime("%Y-%m"), "einnahmen": v["einnahmen"], "ausgaben": v["ausgaben"],
                        "angelegt": v["gespart"], "uebrig": uebrig,
                        "quote": float(uebrig / v["einnahmen"]) if v["einnahmen"] > 0 else None})
    volle = [v for v in verlauf[:-1] if v["einnahmen"] > 0][-fenster:]  # der laufende Monat ist noch nicht fertig
    ein = sum((v["einnahmen"] for v in volle), Decimal(0))
    plaene = [c for c in s.scalars(select(ContractRow).where(ContractRow.entfernt.is_(False), ContractRow.typ == "ausgabe"))
              if c.gilt and c.kategorie in NICHT_AUSGABEN and contract_status(c, heute)[0] != "inaktiv"]
    return {"verlauf": verlauf, "monate": len(volle), "von": volle[0]["monat"] if volle else None,
            "bis": volle[-1]["monat"] if volle else None,
            "quote": float(sum((v["uebrig"] for v in volle), Decimal(0)) / ein) if ein > 0 else None,
            "uebrig_monatlich": sum((v["uebrig"] for v in volle), Decimal(0)) / len(volle) if volle else None,
            "angelegt_monatlich": sum((v["angelegt"] for v in volle), Decimal(0)) / len(volle) if volle else None,
            "sparplaene_monatlich": sum((c.monatlich for c in plaene), Decimal(0)),
            "sparplaene": sorted(({"id": c.id, "name": c.name, "turnus": c.turnus, "betrag": c.erwarteter_betrag,
                                   "monatlich": c.monatlich, "naechste_faelligkeit": c.naechste_faelligkeit}
                                  for c in plaene), key=lambda p: -p["monatlich"])}


def budget_stand(s: Session, heute: date) -> list[dict]:
    """Budgets des laufenden Monats mit Verbrauch und Hochrechnung bis Monatsende."""
    start = heute.replace(day=1)
    ende = add_months(start, 1)
    m = _monatssummen(s, start, ende)
    summen = _gebuendelt(m["kategorien"], m["eltern"])  # ein Budget für „Lebensmittel“ umfasst seine Unterkategorien
    tage, vergangen = (ende - start).days, heute.day
    out = []
    for b in s.scalars(select(Budget).order_by(Budget.id)):
        ausgegeben = max(summen[b.kategorie][0], Decimal(0)) if b.kategorie in summen else Decimal(0)
        anteil = float(ausgegeben / b.limit) if b.limit else 0.0
        out.append({
            "id": b.id, "kategorie": b.kategorie, "limit": b.limit, "ausgegeben": ausgegeben,
            "rest": b.limit - ausgegeben, "anteil": anteil,
            "status": "ueberschritten" if ausgegeben > b.limit else "knapp" if anteil >= 0.8 else "ok",
            # Hochrechnung erst ab der zweiten Woche – aus ein, zwei Tagen wird sonst Unsinn
            "prognose": (ausgegeben / vergangen * tage).quantize(Decimal("0.01")) if vergangen >= 7 else None,
        })
    return out


def pruefe_budgets(notifier, s: Session, heute: date, push: bool = True) -> None:
    """Je Budget und Monat höchstens ein Hinweis bei 80 % und einer bei Überschreitung."""
    monat = heute.strftime("%Y-%m")
    for b in budget_stand(s, heute):
        if b["status"] == "ueberschritten":
            notifier.hinweis(s, "budget", f"Budget überschritten: {b['kategorie']}",
                             f"{euro(b['ausgegeben'])} von {euro(b['limit'])} ausgegeben.", link="#/budgets",
                             schluessel=f"budget|{b['id']}|{monat}|100", push=push)
        elif b["status"] == "knapp":
            notifier.hinweis(s, "budget", f"Budget fast aufgebraucht: {b['kategorie']}",
                             f"{euro(b['ausgegeben'])} von {euro(b['limit'])} – noch {euro(b['rest'])}.",
                             link="#/budgets", schluessel=f"budget|{b['id']}|{monat}|80", push=push)
