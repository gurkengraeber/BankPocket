"""Vertrags-/Abo-Erkennung auf einer Transaktionsliste.

Stufen (siehe Brief):
 1. SEPA-Lastschriften: Gruppierung über Gläubiger-ID + Mandatsreferenz
 2. Sonstige Zahlungen: Gegenpartei/IBAN, Betrag ±10 %, regelmäßiger Abstand
 3. PayPal: Händler aus dem Verwendungszweck
 4. Kategorisierung per Regelliste (LLM-Fallback später)
 5. Einnahmen gleich behandelt
"""
from __future__ import annotations

import calendar
import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from .models import MONATE, WOCHEN_TAGE, Contract, Transaction

AMOUNT_TOLERANCE = Decimal("0.10")
PRICE_CHANGE_THRESHOLD = Decimal("0.02")
DICHTE_MAX = 3.0  # Buchungen pro Monat – darüber ist es ein Laden (Supermarkt, Lieferdienst), kein Vertrag
SCHWANKUNG_MAX = Decimal("0.35")  # bis hierhin gilt eine Gruppe als ein Vertrag mit variablem Betrag
TAG_TOLERANZ = 6  # monatliche Verträge werden an ähnlichen Tagen gebucht (± Tage)
GLEICH_TOLERANZ = Decimal("0.02")  # „gleicher Betrag“: Abos kosten jedes Mal dasselbe
# Hier kauft man ein – zwei ähnliche Käufe im Halbjahres- oder Jahresabstand sind Zufall, kein Vertrag
ALLTAG = {"Lebensmittel", "Drogerie", "Restaurants", "Shopping", "Tanken", "Reisen", "Bargeld", "Freizeit",
          "Gesundheit", "Haustier"}
# Buchungstexte, an denen man eine regelmäßige Abbuchung erkennt
# So weist der Broker eine Sparplan-Ausführung aus – das ist per Definition ein Vertrag, auch 14-tägig oder wöchentlich
SPARPLAN_TEXTE = {"TRADING_SAVINGSPLAN_EXECUTED", "SAVINGS_PLAN_EXECUTED", "SAVINGS_PLAN_INVOICE_CREATED"}
# Erträge, deren Höhe sich jeden Monat ändert (Zinsen aufs Guthaben) – der Betrag sagt hier nichts über den Vertrag
SCHWANKENDE_ERTRAEGE = {"Zinsen", "Dividenden"}
KEINE_IBAN = {"", "n/a", "na", "-"}  # so füllen manche Banken das IBAN-Feld bei Kartenzahlungen
_RE_DAUER = re.compile(r"lastschrift|dauerauftrag|gehalt|rente|folgelastschrift", re.I)

# turnus -> (Monate, Soll-Abstand in Tagen, Toleranz in Tagen, Mindestvorkommen)
TURNI = {
    "woechentlich": (0, 7, 2, 4),
    "zweiwoechentlich": (0, 14, 3, 4),
    "halbmonatlich": (0, 15, 4, 4),  # zweimal im Monat an festen Tagen (z. B. am 2. und 16.) – nur bei Sparplänen
    "vierwoechentlich": (0, 28, 3, 5),  # Prepaid-Aufladung, Vier-Wochen-Tarif: der Tag wandert durch den Monat
    "monatlich": (1, 30, 5, 3),
    # von Hand überwiesen oder zum Quartalsende mit Feiertagen: der Abstand streut, zwei Zahlungen können reichen
    "quartalsweise": (3, 91, 18, 2),
    "halbjaehrlich": (6, 182, 12, 2),
    "jaehrlich": (12, 365, 14, 2),
}

# Reihenfolge zählt: der erste Treffer gewinnt. Stichworte werden im Namen, Verwendungszweck und Buchungstext gesucht.
AUSGABEN_REGELN: dict[str, list[str]] = {
    "Sparen": ["sparplan", "sparrate", "wertpapier", "trade republic", "scalable capital", "dow jones", "bauspar",
               "vermögenswirksam", "vermoegenswirksam", "flatex", "smartbroker", "justtrade", "finanzen.net zero",
               "bitpanda", "coinbase", "kraken", "binance"],
    "Miete": ["miete", "hausverwaltung", "wohnungsbau", "wohnungsgesellschaft", "wohnungsgenossenschaft", "vermietung",
              "nebenkosten", "hausgeld", "vonovia", "deutsche wohnen", "leg wohnen", "grand city", "lwb"],
    "Strom": ["immergrün", "immergruen", "stadtwerke", "vattenfall", "e.on", "enbw", "naturstrom", "envia", "eprimo",
              "yello", "lichtblick", "ostrom", "tibber", "polarstern", "grünwelt", "rheinenergie", "mainova", "gasag",
              "energieversorgung", "fernwärme", "fernwaerme"],
    "Internet & Telefon": ["telekom", "vodafone", "o2", "1&1", "congstar", "telefonica", "pyur", "netcologne", "m-net",
                           "deutsche glasfaser", "lebara", "aldi talk", "fraenk", "blau.de", "simyo", "winsim",
                           "drillisch", "freenet", "mobilcom"],
    "Streaming": ["netflix", "spotify", "disney", "dazn", "amazon prime", "youtube", "apple.com/bill", "audible",
                  "deezer", "apple music", "paramount", "sky deutschland", "joyn", "rtl+", "crunchyroll", "twitch",
                  "patreon"],
    "Software/KI": ["anthropic", "openai", "chatgpt", "claude.ai", "github", "google one", "google cloud",
                    "google workspace", "proton", "mailbox.org", "microsoft", "adobe", "dropbox", "icloud",
                    "1password", "bitwarden", "nordvpn", "mullvad", "jetbrains", "notion", "canva", "hetzner",
                    "netcup", "strato", "ionos", "all-inkl", "namecheap", "cloudflare", "digitalocean",
                    "amazon web services"],
    "Versicherung": ["versicherung", "allianz", "huk", "axa", "ergo", "haftpflicht", "debeka", "signal iduna", "r+v",
                     "hansemerkur", "hanse merkur", "devk", "lvm", "gothaer", "barmenia", "wgv", "cosmosdirekt",
                     "cosmos direkt", "getsafe", "krankenkasse", "aok", "barmer", "dak-gesundheit", "ikk",
                     "knappschaft"],
    "Spenden": ["spende", "unicef", "greenpeace", "ärzte ohne grenzen", "aerzte ohne grenzen", "wikimedia",
                "sea-watch", "nabu", "amnesty", "caritas", "diakonie", "betterplace", "wwf"],
    "Mitgliedschaft": ["ver.di", "verdi", "mitgliedsbeitrag", "verein", "e.v.", "adac", "gewerkschaft"],
    "Coworking": ["coworking", "co-working"],
    "Fitness": ["fitness", "mcfit", "urban sports", "gym", "clever fit", "john reed", "kletterhalle", "boulder"],
    "Mobilität": ["blablacar", "flix se", "flixtrain", "db vertrieb", "deutschlandticket", "bvg", "mvg", "hvv", "rmv", "flixbus", "deutsche bahn",
                  "db fernverkehr", "bahncard", "leipziger verkehrsbetriebe", "lvb", "mdv", "vbb", "kvb", "üstra",
                  "nextbike", "tier mobility", "bolt", "uber *trip", "uber trip", "free now", "freenow", "miles mobility",
                  "share now", "teilauto", "cambio", "parkhaus", "easypark", "parkster", "apcoa", "contipark"],
    "Bildung": ["udemy", "coursera", "volkshochschule", "hochschule", "universität", "universitaet",
                "studentenwerk", "semesterbeitrag", "thalia", "hugendubel", "duolingo", "babbel"],
    "Gebühren & Steuern": ["rundfunk", "beitragsservice", "finanzamt", "bundeskasse", "stadtkasse",
                           "hauptzollamt", "kfz-steuer", "kontoführung", "kontofuehrung", "entgelt", "gebühr",
                           "gebuehr"],
    # Alltagsausgaben – vor allem für Analysen, selten Verträge
    "Lebensmittel": ["rewe", "edeka", "aldi", "lidl", "netto", "penny", "kaufland", "alnatura", "denns",
                     "tegut", "globus", "norma", "nahkauf", "konsum", "marktkauf", "famila", "bio company", "biomarkt",
                     "flink", "knuspr", "picnic", "bofrost", "hellofresh", "bäckerei", "baeckerei", "backwerk",
                     "fleischerei", "metzgerei"],
    "Drogerie": ["dm-drogerie", "dm drogerie", "rossmann", "budni", "douglas"],
    "Restaurants": ["lieferando", "wolt", "uber eats", "foodora", "restaurant", "mcdonald", "burger king", "starbucks",
                    "cafe", "café", "pizzeria", "imbiss", "domino", "subway", "kfc", "vapiano", "osteria", "nordsee",
                    "dean&david", "dean & david", "bistro", "döner", "doener", "sushi", "too good to go"],
    "Haustier": ["fressnapf", "zooplus", "tierarzt", "tierklinik", "futterhaus"],
    "Freizeit": ["kino", "cinemaxx", "cineplex", "eventim", "ticketmaster", "museum", "konzert", "theater", "steam",
                 "playstation", "nintendo", "xbox", "schwimmbad", "bowling", "ticketswap"],
    "Shopping": ["amazon", "zalando", "otto ", "ebay", "ikea", "mediamarkt", "saturn", "decathlon", "h&m",
                 "about you", "galeria", "tk maxx", "primark", "c&a", "deichmann", "snipes", "zara", "uniqlo",
                 "obi ", "hornbach", "bauhaus", "toom", "hagebau", "jysk", "xxxlutz", "tchibo", "tedi", "woolworth",
                 "temu", "shein", "aliexpress", "etsy", "vinted", "kleinanzeigen", "conrad", "cyberport",
                 "notebooksbilliger", "alternate", "galaxus", "home24", "westwing"],
    "Tanken": ["aral", "shell", "esso", "tankstelle", "totalenergies", "jet tankstelle", "orlen", "avia", "star tank",
               "tamoil", "agip"],
    "Gesundheit": ["apotheke", "arzt", "zahnarzt", "physio", "praxis", "klinik", "krankenhaus", "fielmann",
                   "apollo optik", "optik", "sanitätshaus", "docmorris", "shop apotheke", "medpex"],
    "Reisen": ["booking.com", "airbnb", "lufthansa", "ryanair", "eurowings", "hotel", "bahn.de", "easyjet",
               "condor", "wizz air", "hostel", "expedia", "ferienwohnung", "check24 reise"],
    "Bargeld": ["geldautomat", "bargeldauszahlung", "auszahlung atm", "bargeld"],
}
EINNAHMEN_REGELN: dict[str, list[str]] = {
    "Lohn / Gehalt": ["gehalt", "lohn", "bezüge", "bezuege", "rente"],
    "Zinsen": ["zinsen", "zinsgutschrift"],
    "Dividenden": ["dividende", "ausschüttung", "ausschuettung", "ertragsgutschrift", "kupon"],
    "Staatliche Leistungen": ["familienkasse", "kindergeld", "elterngeld", "bafög", "bafoeg", "arbeitsagentur",
                              "bundesagentur für arbeit", "jobcenter", "wohngeld", "krankengeld"],
    "Erstattung": ["erstattung", "rückerstattung", "rueckerstattung", "refund", "retoure", "storno", "rückzahlung",
                   "rueckzahlung", "finanzamt"],
    "Verkäufe": ["vinted", "kleinanzeigen", "ebay", "momox", "rebuy"],
}
FALLBACK = {"ausgabe": "Sonstiges", "einnahme": "Sonstige Einnahmen"}
# Kreditkarten nennen die Art des Händlers (englisch, vom Kartennetz). Gilt nur für den Buchungstext und erst,
# wenn der Händlername nichts hergibt.
HAENDLERART_REGELN: dict[str, list[str]] = {
    "Mobilität": ["transportation", "passenger railway", "bus line", "taxicab", "limousine", "commuter", "toll",
                  "automobile rental", "car rental", "parking", "ferries", "auto service", "automotive", "car wash",
                  "auto parts", "tire store", "motor vehicle", "towing", "auto dealer", "bicycle"],
    "Bargeld": ["auto cash", "automated cash", "cash disburse", "manual cash"],
    "Reisen": ["airline", "air carrier", "lodging", "hotel", "motel", "travel agenc", "tour operator", "cruise",
               "campground"],
    "Lebensmittel": ["grocery", "supermarket", "bakeries", "food store", "convenience store", "dairy", "candy",
                     "pkg stores", "package store", "beer", "wine", "liquor"],
    "Restaurants": ["eating place", "restaurant", "fast food", "drinking place", "caterer"],
    "Tanken": ["service station", "fuel dealer", "automated fuel"],
    "Gesundheit": ["drug store", "pharmac", "doctor", "dentist", "medical", "hospital", "optician", "optometrist",
                   "chiropract"],
    "Drogerie": ["cosmetic store", "barber", "beauty shop"],
    "Software/KI": ["digital goods", "computer software", "computer network", "information retrieval",
                    "data processing"],
    "Internet & Telefon": ["telecommunication", "telephone service"],
    "Freizeit": ["motion picture", "amusement", "theatrical", "recreation", "tourist attraction", "video game",
                 "bowling", "sporting and recreational", "ticket agenc"],
    "Bildung": ["school", "college", "universit", "book store", "educational"],
    "Versicherung": ["insurance"],
    "Shopping": ["clothing", "apparel", "department store", "electronics", "furniture", "shoe store",
                 "sporting goods", "variety store", "discount store", "hardware store", "home supply", "jewelry",
                 "hobby", "toy", "gift", "florist", "record store", "music store", "mail order", "direct marketing"],
    "Gebühren & Steuern": ["government service", "tax payment", "postal service", "courier service"],
}
# Sparen ist Vermögensaufbau, keine Ausgabe -> zählt nicht in Ø Ausgaben/Monat.
NICHT_AUSGABEN = {"Sparen"}

_RE_PAYPAL_EINKAUF = re.compile(r"Ihr Einkauf bei\s+(.+?)(?:\s*[,.;]|\s{2,}|$)", re.I)
_RE_PAYPAL_PREFIX = re.compile(r"PP\.\d+\.PP\s*\.\s*(.+?)\s*[,.;]", re.I)
_RE_NOISE = re.compile(r"\d+|[^\w\s]|\b(gmbh|ag|kg|se|ug|e\s?k|co|sagt danke)\b", re.I)


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def naechster_termin(d: date, turnus: str, k: int = 1) -> date:
    """Der k-te Termin nach d im Rhythmus des Vertrags."""
    if turnus in WOCHEN_TAGE:
        return d + timedelta(days=k * WOCHEN_TAGE[turnus])
    return add_months(d, k * MONATE[turnus])


def normalize(name: str) -> str:
    return " ".join(_RE_NOISE.sub(" ", name.lower()).split())


def _paypal_haendler(name: str, zweck: str) -> str | None:
    if "paypal" not in name.lower():
        return None
    for rx in (_RE_PAYPAL_EINKAUF, _RE_PAYPAL_PREFIX):
        m = rx.search(zweck)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def paypal_merchant(t: Transaction) -> str | None:
    return _paypal_haendler(t.gegenpartei, t.verwendungszweck)


def haendler_schluessel(name: str, zweck: str = "") -> str:
    """Normalisierter Händlername – bei PayPal der eigentliche Händler. Schlüssel für die KI-Einordnung."""
    return normalize(_paypal_haendler(name, zweck) or name)


# Vom Nutzer angelegte Regeln: (stichwort, kategorie, typ). Werden aus der DB geladen (regeln_laden).
BENUTZER_REGELN: list[tuple[str, str, str]] = []


# Von der KI eingeordnete Händler: (typ, händlerschlüssel) → Kategorie. Aus der DB geladen (ki.laden).
KI_KATEGORIEN: dict[tuple[str, str], str] = {}


def regeln_setzen(regeln: list[tuple[str, str, str]]) -> None:
    BENUTZER_REGELN[:] = sorted(((w.lower(), k, t) for w, k, t in regeln), key=lambda r: -len(r[0]))


def regelkategorie(name: str, purpose: str = "", typ: str = "ausgabe", buchungstext: str = "",
                   rules: dict[str, list[str]] | None = None) -> str | None:
    """Kategorie nach Nutzer- und eingebauten Regeln – None, wenn keine Regel passt."""
    haystack = f"{name} {purpose} {buchungstext}".lower()
    if rules is None:
        for stichwort, kategorie, regeltyp in BENUTZER_REGELN:  # längstes Stichwort zuerst
            if regeltyp == typ and stichwort in haystack:
                return kategorie
    eingebaut = rules is None
    rules = rules or (EINNAHMEN_REGELN if typ == "einnahme" else AUSGABEN_REGELN)
    for kategorie, keywords in rules.items():
        if any(k in haystack for k in keywords):
            return kategorie
    if eingebaut and typ == "ausgabe" and buchungstext:
        art = buchungstext.lower()
        for kategorie, keywords in HAENDLERART_REGELN.items():
            if any(k in art for k in keywords):
                return kategorie
    return None


def categorize(name: str, purpose: str = "", typ: str = "ausgabe",
               rules: dict[str, list[str]] | None = None, buchungstext: str = "") -> str:
    return (regelkategorie(name, purpose, typ, buchungstext, rules)
            or (KI_KATEGORIEN.get((typ, haendler_schluessel(name, purpose))) if rules is None else None)
            or FALLBACK[typ])


def _group_key(t: Transaction) -> tuple[str, str] | None:
    """(Methode, Schlüssel) oder None, wenn keine Gruppierung möglich ist."""
    sign = "+" if t.betrag > 0 else "-"
    if (t.buchungstext or "").upper() in SPARPLAN_TEXTE and t.gegenpartei:
        return "sparplan", f"{sign}|{normalize(t.gegenpartei)}"
    # PayPal zuerst: alle PayPal-Lastschriften laufen über dasselbe Mandat, der Händler steht im Verwendungszweck
    merchant = paypal_merchant(t)
    if merchant:
        return "paypal", f"{sign}|{normalize(merchant)}"
    if t.glaeubiger_id:
        return "sepa", f"{sign}|{t.glaeubiger_id}|{t.mandatsreferenz}"
    iban = t.iban_gegenpartei if t.iban_gegenpartei.strip().lower() not in KEINE_IBAN else ""
    key = iban or normalize(t.gegenpartei)
    return ("gegenpartei", f"{sign}|{key}") if key else None


def _cluster_by_amount(txs: list[Transaction], toleranz: Decimal = AMOUNT_TOLERANCE) -> list[list[Transaction]]:
    """Betrag ±10 % relativ zum jeweils letzten Betrag des Clusters (verträgt schleichende Erhöhungen)."""
    clusters: list[list[Transaction]] = []
    for t in sorted(txs, key=lambda x: x.buchungsdatum):
        for c in clusters:
            ref = abs(c[-1].betrag)
            if abs(abs(t.betrag) - ref) <= ref * toleranz:
                c.append(t)
                break
        else:
            clusters.append([t])
    return clusters


def _dichte(txs: list[Transaction]) -> float:
    """Buchungen pro Monat über die aktive Zeitspanne der Gruppe."""
    daten = [t.buchungsdatum for t in txs]
    monate = max((max(daten) - min(daten)).days / 30.44, 1.0)
    return len(txs) / monate


def _schwankung(txs: list[Transaction]) -> Decimal:
    betraege = sorted(abs(t.betrag) for t in txs)
    mitte = betraege[len(betraege) // 2]
    return (betraege[-1] - betraege[0]) / mitte if mitte else Decimal(1)


def _tage_passen(dates: list[date], turnus: str) -> bool:
    """Monatliche Zahlungen kommen an ähnlichen Tagen – zufällige Einkäufe nicht.
    Kreisförmig gerechnet, damit 30., 31., 1. und 2. als nah beieinander gelten."""
    if turnus != "monatlich":
        return True
    winkel = [2 * math.pi * (d.day - 1) / 31 for d in dates]
    mittel = math.atan2(sum(map(math.sin, winkel)), sum(map(math.cos, winkel))) * 31 / (2 * math.pi)
    nah = sum(1 for d in dates if abs((d.day - 1 - mittel + 15.5) % 31 - 15.5) <= TAG_TOLERANZ)
    return nah / len(dates) >= 0.75


def detect_turnus(dates: list[date]) -> str | None:
    if len(dates) < 2:
        return None
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    med = median(gaps)
    for name, (_, soll, tol, min_n) in TURNI.items():
        if abs(med - soll) > tol:
            continue
        # ein doppelter Abstand heißt: eine Zahlung ausgefallen (pausiert, Guthaben reichte) – kein Bruch
        ok = sum(1 for g in gaps if abs(g - soll) <= tol or abs(g - 2 * soll) <= 2 * tol)
        passt = len(dates) >= min_n and ok / len(gaps) >= 0.75
        if name == "vierwoechentlich":
            # Vier Wochen und ein Monat liegen dicht beieinander. Vier Wochen sind es nur, wenn der übliche
            # Abstand wirklich 28 Tage ist und der Tag durch den Monat wandert – sonst weiter mit „monatlich“.
            if passt and abs(med - soll) <= 1 and not _tage_passen(dates, "monatlich"):
                return name
            continue
        return name if passt else None
    return None


def _neues_gehalt(txs: list[Transaction], dates: list[date]) -> str | None:
    """Ausgewiesenes Gehalt (Buchungstext oder Verwendungszweck) gilt schon nach zwei Monaten als monatlich –
    sonst fehlt nach einem Jobwechsel lange die Gehaltsanzeige."""
    if len(dates) != 2 or not 25 <= (dates[1] - dates[0]).days <= 35 or any(t.betrag <= 0 for t in txs):
        return None
    ist_gehalt = all(regelkategorie("", t.verwendungszweck, "einnahme", t.buchungstext,
                                    rules={"g": EINNAHMEN_REGELN["Lohn / Gehalt"]}) for t in txs)
    return "monatlich" if ist_gehalt else None


def _regelmaessig_ausgewiesen(txs: list[Transaction]) -> bool:
    """Die Bank weist die jüngste und mindestens die Hälfte der Zahlungen als Lastschrift oder Dauerauftrag aus –
    auch wenn die ersten noch von Hand überwiesen wurden."""
    ausgewiesen = [bool(_RE_DAUER.search(t.buchungstext or "")) for t in sorted(txs, key=lambda t: t.buchungsdatum)]
    return ausgewiesen[-1] and sum(ausgewiesen) * 2 >= len(ausgewiesen)


def _ein_vertrag(c: Contract | None) -> Contract | None:
    """Wechselnde Beträge sind nur dann EIN Vertrag, wenn je Zeitraum eine Zahlung kommt (Beitrag wurde erhöht).
    Zwei Zahlungen im selben Zeitraum sind zwei Verträge beim selben Anbieter (zwei Abos, Beitrag plus Spende)."""
    if c is None:
        return None
    tage = sorted({t.buchungsdatum for t in c.transaktionen})
    eng = sum(1 for a, b in zip(tage, tage[1:]) if (b - a).days < TURNI[c.turnus][1] / 2)
    return c if len(tage) == len(c.transaktionen) and eng == 0 else None


def _dauerbuchung(txs: list[Transaction], methode: str) -> bool:
    """Lastschrift mit Mandat, Dauerauftrag oder Gehalt – die Bank weist die Zahlung selbst als regelmäßig aus."""
    return methode == "sepa" or all(_RE_DAUER.search(t.buchungstext or "") for t in txs)


def _seltener_vertrag_glaubwuerdig(txs: list[Transaction], methode: str, kategorie: str) -> bool:
    """Halbjährlich/jährlich reichen zwei Zahlungen – aber nur, wenn sie wirklich nach Vertrag aussehen.
    Zwei ähnliche Kartenkäufe im Abstand von sechs Monaten (Fernbus, Flug, Laden) sind sonst Zufall."""
    if len({t.buchungsdatum for t in txs}) >= 3 or _dauerbuchung(txs, methode):
        return True
    return kategorie not in ALLTAG and _schwankung(txs) <= GLEICH_TOLERANZ


def _sicherheit(txs: list[Transaction], methode: str, turnus: str, kategorie: str, vorkommen: int) -> int:
    """Wie sicher ist das ein Vertrag? 0–100, damit die sichersten Vorschläge oben stehen."""
    punkte = 40
    if _dauerbuchung(txs, methode):
        punkte += 20
    lang, mittel = (6, 4) if turnus == "monatlich" else (4, 3)
    punkte += 15 if vorkommen >= lang else 8 if vorkommen >= mittel else -15 if vorkommen <= 2 else 0
    schwankung = _schwankung(txs)
    punkte += 15 if schwankung <= GLEICH_TOLERANZ else 5 if schwankung <= AMOUNT_TOLERANCE else 0
    if kategorie in ALLTAG:
        punkte -= 25
    elif kategorie not in FALLBACK.values():
        punkte += 10  # bekannter Vertragsanbieter (Streaming, Versicherung, Miete …)
    return max(5, min(99, punkte))


def _betragsaenderung(betraege: list[Decimal]) -> tuple[bool, bool]:
    """(gestiegen, gesunken): Die letzte Zahlung weicht um mehr als 2 % von der vorherigen ab – und davor war der
    Betrag stabil. Bei Verträgen, die ohnehin jeden Monat schwanken (Handyrechnung, Zinsen), wäre das nur Rauschen."""
    if len(betraege) < 2 or betraege[-1] * betraege[-2] <= 0:
        return False, False
    letzter, vorher = abs(betraege[-1]), abs(betraege[-2])
    if len(betraege) >= 3 and abs(vorher - abs(betraege[-3])) > abs(betraege[-3]) * PRICE_CHANGE_THRESHOLD:
        return False, False
    return letzter > vorher * (1 + PRICE_CHANGE_THRESHOLD), letzter < vorher * (1 - PRICE_CHANGE_THRESHOLD)


def _ist_gehalt(txs: list[Transaction]) -> bool:
    """Eingänge eines Absenders, von denen die Bank oder der Verwendungszweck mindestens drei als
    Lohn/Gehalt/Rente ausweist. Daneben dürfen vom selben Absender viele andere Zahlungen kommen (Spesen)."""
    if len(txs) < 3 or any(t.betrag <= 0 for t in txs):
        return False
    gehalt = sum(1 for t in txs if t.kategorie == "Lohn / Gehalt" or regelkategorie(
        "", t.verwendungszweck, "einnahme", t.buchungstext, rules={"g": EINNAHMEN_REGELN["Lohn / Gehalt"]}))
    return gehalt >= 3 and gehalt / len(txs) >= 0.3


def _hauptzahlungen(txs: list[Transaction]) -> list[Transaction]:
    """Je Kalendermonat die größte Zahlung – ohne Monate, in denen nur Kleinbeträge (Spesen) kamen."""
    je_monat: dict[tuple[int, int], Transaction] = {}
    for t in txs:
        monat = (t.buchungsdatum.year, t.buchungsdatum.month)
        if monat not in je_monat or t.betrag > je_monat[monat].betrag:
            je_monat[monat] = t
    mitte = median(t.betrag for t in je_monat.values())
    return sorted((t for t in je_monat.values() if t.betrag >= mitte * Decimal("0.4")), key=lambda t: t.buchungsdatum)


def compute_status(turnus: str, last: date, today: date) -> tuple[date, str, int]:
    """(nächste Fälligkeit, Status, Tage überfällig)."""
    months, _, tol, _ = TURNI[turnus]
    due = naechster_termin(last, turnus)
    if today <= due + timedelta(days=tol):
        return due, "aktiv", 0
    if turnus in WOCHEN_TAGE:  # nach gut einem Monat ohne Zahlung gilt der Vertrag als beendet
        return due, "inaktiv" if today > due + timedelta(days=35) else "ueberfaellig", (today - due).days
    # lange genug ausgeblieben (mind. 2 Monate bzw. ein ganzer Zyklus) -> inaktiv, vorher „überfällig“
    status = "inaktiv" if today > add_months(due, max(months, 2)) else "ueberfaellig"
    return due, status, (today - due).days


def _build(txs: list[Transaction], methode: str, schluessel: str, today: date) -> Contract | None:
    txs = sorted(txs, key=lambda t: t.buchungsdatum)
    # Mehrere Buchungen am selben Tag zählen als eine Zahlung.
    dates = sorted({t.buchungsdatum for t in txs})
    turnus = detect_turnus(dates) or _neues_gehalt(txs, dates)
    if not turnus or not _tage_passen(dates, turnus):
        return None
    last = txs[-1]
    names = Counter(
        (paypal_merchant(t) or t.gegenpartei).strip() for t in txs if (paypal_merchant(t) or t.gegenpartei)
    )
    name = names.most_common(1)[0][0] if names else (last.glaeubiger_id or "Unbekannt")
    due, status, ueberfaellig = compute_status(turnus, last.buchungsdatum, today)
    typ = "einnahme" if last.betrag > 0 else "ausgabe"
    kategorie = last.kategorie or categorize(name, last.verwendungszweck, typ, buchungstext=last.buchungstext)
    if turnus in ("halbjaehrlich", "jaehrlich") and not _seltener_vertrag_glaubwuerdig(txs, methode, kategorie):
        return None
    if turnus == "quartalsweise" and len(dates) < 3 and not (
            kategorie not in ALLTAG and _schwankung(txs) <= GLEICH_TOLERANZ
            and (_regelmaessig_ausgewiesen(txs) or kategorie not in FALLBACK.values())):
        return None  # zwei Zahlungen im Quartalsabstand: nur bei gleichem Betrag und Dauerauftrag/Lastschrift
        # oder bekanntem Anbieter – zwei ähnliche Einkäufe im Abstand von drei Monaten sind Zufall
    # Wöchentlich oder alle zwei Wochen geht man auch einkaufen – ein Vertrag kostet dabei jedes Mal dasselbe
    if turnus in WOCHEN_TAGE and not (_dauerbuchung(txs, methode) or _schwankung(txs) <= GLEICH_TOLERANZ):
        return None
    prev = txs[-2].betrag if len(txs) > 1 else None
    gestiegen, gesunken = _betragsaenderung([x.betrag for x in txs])
    return Contract(
        name=name,
        kategorie=kategorie,
        turnus=turnus,
        erwarteter_betrag=last.betrag,
        naechste_faelligkeit=due,
        typ=typ,
        status=status,
        methode=methode,
        schluessel=schluessel,
        tage_ueberfaellig=ueberfaellig,
        vorkommen=len(dates),
        sicherheit=_sicherheit(txs, methode, turnus, kategorie, len(dates)),
        betrag_gestiegen=gestiegen,
        vorheriger_betrag=prev if gestiegen or gesunken else None,  # gesetzt, aber nicht gestiegen = gesunken
        transaktionen=txs,
    )


def _feste_monatstage(tage: list[int]) -> int:
    """In wie viele Gruppen fallen die Tage im Monat? Zweimal monatlich ergibt zwei, echter 14-Tage-Takt wandert."""
    sortiert = sorted(set(tage))
    gruppen = [[sortiert[0]]]
    for tag in sortiert[1:]:
        if tag - gruppen[-1][-1] > 4:
            gruppen.append([tag])
        else:
            gruppen[-1].append(tag)
    # Ein fester Tag verschiebt sich höchstens ums Wochenende – eine breite Gruppe heißt: die Tage wandern
    if any(g[-1] - g[0] > 5 for g in gruppen):
        return 99
    return len(gruppen)


def _build_sparplan(txs: list[Transaction], schluessel: str, today: date) -> Contract | None:
    """Sparplan je Wertpapier, im Rhythmus der letzten Ausführungen (wöchentlich, alle zwei Wochen, monatlich …)."""
    txs = sorted(txs, key=lambda t: t.buchungsdatum)
    dates = sorted({t.buchungsdatum for t in txs})
    if len(dates) < 2:
        return None
    abstand = median([(b - a).days for a, b in zip(dates, dates[1:])][-6:])  # der Rhythmus kann gewechselt haben
    if abstand > 35:  # vierteljährlich oder seltener: normale Erkennung
        c = _build(txs, "sparplan", schluessel, today)
        if c:
            c.sicherheit = max(c.sicherheit, 90)
        return c
    turnus = "woechentlich" if abstand <= 9 else "zweiwoechentlich" if abstand <= 20 else "monatlich"
    if turnus == "zweiwoechentlich" and _feste_monatstage([d.day for d in dates[-8:]]) <= 2:
        turnus = "halbmonatlich"  # 24 statt 26 Ausführungen im Jahr
    last, prev = txs[-1], txs[-2].betrag
    gestiegen, gesunken = _betragsaenderung([x.betrag for x in txs])  # Rate erhöht oder gesenkt
    due, status, ueberfaellig = compute_status(turnus, last.buchungsdatum, today)
    return Contract(
        name=last.gegenpartei.strip(), kategorie="Sparen", turnus=turnus, erwarteter_betrag=last.betrag,
        naechste_faelligkeit=due, typ="ausgabe", status=status, methode="sparplan", schluessel=schluessel,
        tage_ueberfaellig=ueberfaellig, vorkommen=len(dates), sicherheit=95 if len(dates) >= 3 else 85,
        betrag_gestiegen=gestiegen, vorheriger_betrag=prev if gestiegen or gesunken else None, transaktionen=txs)


def muster(t: Transaction) -> str | None:
    """Woran weitere Zahlungen desselben Vertrags zu erkennen sind (Mandat, PayPal-Händler, Empfänger …)."""
    key = _group_key(t)
    return f"{key[0]}|{key[1]}" if key else None


def muster_aus_name(name: str, einnahme: bool) -> str | None:
    """Für von Hand angelegte Verträge: Zahlungen an bzw. von jemandem mit diesem Namen."""
    n = normalize(name)
    return f"gegenpartei|{'+' if einnahme else '-'}|{n}" if n else None


def detect_contracts(transactions: list[Transaction], today: date | None = None) -> list[Contract]:
    today = today or date.today()
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for t in transactions:
        if t.betrag == 0:
            continue
        key = _group_key(t)
        if key:
            groups[key].append(t)

    contracts: list[Contract] = []
    for (methode, key), txs in groups.items():
        if methode == "sparplan":
            c = _build_sparplan(txs, f"{methode}|{key}", today)
            if c:
                contracts.append(c)
            continue
        # Zinsen und Dividenden: Unter demselben Namen laufen beim Broker auch Verkäufe – die gehören nicht dazu
        ertraege = [t for t in txs if t.betrag > 0 and t.kategorie in SCHWANKENDE_ERTRAEGE]
        if len(ertraege) >= 2 and len(ertraege) * 2 >= len(txs):
            c = _build(ertraege, methode, f"{methode}|{key}", today)
            if c:
                # erwartet wird die Mitte der letzten Zahlungen, nicht zufällig die letzte (Ausreißer zählen nicht)
                c.erwarteter_betrag = Decimal(median(t.betrag for t in c.transaktionen[-6:])).quantize(Decimal("0.01"))
                c.betrag_gestiegen, c.vorheriger_betrag = False, None
                contracts.append(c)
            continue
        if _ist_gehalt(txs):
            # Gehalt schwankt (Zuschläge, Sonderzahlungen) und kommt mit Spesen vom selben Absender: Es zählt die
            # Hauptzahlung jedes Monats, unabhängig von ihrer genauen Höhe.
            haupt = _hauptzahlungen(txs)
            c = _build(haupt, methode, f"{methode}|{key}", today)
            if c:
                c.kategorie = "Lohn / Gehalt"
                c.erwarteter_betrag = Decimal(median(t.betrag for t in haupt[-3:])).quantize(Decimal("0.01"))
                c.betrag_gestiegen, c.vorheriger_betrag = False, None
                contracts.append(c)
                continue
        if methode == "sepa":  # ein Mandat = ein Vertrag; der Betrag darf schwanken (Abschläge)
            c = _build(txs, methode, f"{methode}|{key}", today)
            if c:
                contracts.append(c)
            continue
        if _dichte(txs) > DICHTE_MAX:
            # Ein Laden mit vielen Einkäufen – ein Abo dort (Amazon Prime, Lieferdienst-Pass) fällt trotzdem auf:
            # immer derselbe Betrag, einmal im Monat, am selben Tag.
            for part in _cluster_by_amount(txs, GLEICH_TOLERANZ):
                c = _build(part, methode, f"{methode}|{key}|{abs(part[0].betrag)}", today) if len(part) >= 3 else None
                if c and c.turnus in ("woechentlich", "zweiwoechentlich", "monatlich") \
                        and len({t.buchungsdatum for t in part}) == len(part):
                    contracts.append(c)
            continue
        if txs[0].betrag < 0 and _schwankung(txs) > SCHWANKUNG_MAX and _regelmaessig_ausgewiesen(txs):
            # Lastschrift oder Dauerauftrag im festen Rhythmus, aber mit Ausreißern beim Betrag (Nachzahlung,
            # anteiliger erster Beitrag): Es zählt der Rhythmus, erwartet wird die Mitte der letzten Zahlungen.
            c, rest = _ein_vertrag(_build(txs, methode, f"{methode}|{key}", today)), []
            if c is None:
                # … oder nur die großen Zahlungen folgen einem Rhythmus (Jahresbeitrag neben kleinen Nachträgen)
                grenze = max(abs(t.betrag) for t in txs) * Decimal("0.4")
                haupt = [t for t in txs if abs(t.betrag) >= grenze]
                if 2 <= len(haupt) < len(txs):
                    # Kennung über den ältesten Betrag – bleibt stabil und kollidiert nicht mit dem Rest der Gruppe
                    c = _ein_vertrag(_build(haupt, methode, f"{methode}|{key}|{abs(min(haupt, key=lambda t: t.buchungsdatum).betrag)}", today))
                    rest = [t for t in txs if abs(t.betrag) < grenze] if c else []
            if c:
                c.erwarteter_betrag = Decimal(median(t.betrag for t in c.transaktionen[-3:])).quantize(Decimal("0.01"))
                c.betrag_gestiegen, c.vorheriger_betrag = False, None
                contracts.append(c)
                if not rest:
                    continue
                txs = rest  # die kleinen Zahlungen daneben laufen durch die übliche Erkennung
        if _schwankung(txs) <= SCHWANKUNG_MAX:  # ein Vertrag mit leicht variablem Betrag (Zinsen, Handyrechnung)
            c = _build(txs, methode, f"{methode}|{key}", today)
            if c:
                contracts.append(c)
                continue
        for part in _cluster_by_amount(txs):
            # Cluster über den ältesten Betrag identifizieren: bleibt stabil, wenn neue Buchungen dazukommen.
            c = _build(part, methode, f"{methode}|{key}|{abs(part[0].betrag)}", today)
            # Jährliche Muster brauchen nur zwei Zahlungen – bei einem Café mit vielen Besuchen ist das Zufall.
            if c and c.turnus in ("halbjaehrlich", "jaehrlich") and len(part) * 2 < len(txs):
                continue
            if c:
                contracts.append(c)
    # Jede Kennung gibt es genau einmal – sie ist der Schlüssel, unter dem der Nutzer bestätigt oder ablehnt
    gesehen: dict[str, int] = {}
    for c in contracts:
        gesehen[c.schluessel] = gesehen.get(c.schluessel, 0) + 1
        if gesehen[c.schluessel] > 1:
            c.schluessel = f"{c.schluessel}|{abs(c.erwarteter_betrag)}#{gesehen[c.schluessel]}"
    return sorted(contracts, key=lambda c: (c.typ, c.naechste_faelligkeit))


def _monthly_sum(contracts: list[Contract], pred) -> Decimal:
    return sum((c.monatlich for c in contracts if c.status != "inaktiv" and pred(c)), Decimal(0))


def average_monthly_expenses(contracts: list[Contract]) -> Decimal:
    return _monthly_sum(contracts, lambda c: c.typ == "ausgabe" and c.kategorie not in NICHT_AUSGABEN)


def average_monthly_savings(contracts: list[Contract]) -> Decimal:
    return _monthly_sum(contracts, lambda c: c.typ == "ausgabe" and c.kategorie in NICHT_AUSGABEN)


def summary_by_turnus(contracts: list[Contract]) -> dict[str, dict[str, dict]]:
    """{typ: {turnus: {"anzahl": n, "summe": Betrag}}} über aktive und überfällige Verträge."""
    out: dict[str, dict[str, dict]] = {"ausgabe": {}, "einnahme": {}}
    for turnus in TURNI:
        for typ in out:
            rows = [c for c in contracts if c.typ == typ and c.turnus == turnus and c.status != "inaktiv"]
            if rows:
                out[typ][turnus] = {"anzahl": len(rows),  # bei geteilten Verträgen zählt der eigene Anteil
                                     "summe": sum((abs(getattr(c, "mein_betrag", c.erwarteter_betrag)) for c in rows),
                                                  Decimal(0))}
    return out
