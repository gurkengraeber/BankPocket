"""Logos für Verträge: Zu bekannten Anbietern gehört eine Internetadresse, deren Seitensymbol als Logo dient.

Datenschutz: Der Server holt das Symbol einmal und speichert es in `data/logos/`. Nach außen geht dabei nur die
Adresse des Anbieters (z. B. „congstar.de“) – keine Beträge, keine Buchungen. Dein Browser spricht nur mit
deinem eigenen Server.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# Stichwort im Namen (klein geschrieben) → Adresse. Reihenfolge zählt: der erste Treffer gewinnt.
MARKEN: list[tuple[str, str]] = [
    # Telefon & Internet
    ("congstar", "congstar.de"), ("telekom", "telekom.de"), ("vodafone", "vodafone.de"), ("o2 ", "o2online.de"),
    ("telefonica", "o2online.de"), ("1&1", "1und1.de"), ("1und1", "1und1.de"), ("pyur", "pyur.com"),
    ("aldi talk", "alditalk.de"), ("fraenk", "fraenk.de"), ("freenet", "freenet.de"), ("simyo", "simyo.de"),
    # Streaming & Medien
    ("netflix", "netflix.com"), ("spotify", "spotify.com"), ("tidal", "tidal.com"), ("disney", "disneyplus.com"),
    ("dazn", "dazn.com"), ("youtube", "youtube.com"), ("audible", "audible.de"), ("deezer", "deezer.com"),
    ("apple", "apple.com"), ("amazon prime", "amazon.de"), ("amazon", "amazon.de"), ("sky ", "sky.de"),
    ("joyn", "joyn.de"), ("rtl", "rtl.de"), ("crunchyroll", "crunchyroll.com"), ("twitch", "twitch.tv"),
    ("patreon", "patreon.com"), ("steady", "steadyhq.com"), ("taz", "taz.de"), ("zeit ", "zeit.de"),
    ("spiegel", "spiegel.de"), ("rundfunk", "rundfunkbeitrag.de"), ("beitragsservice", "rundfunkbeitrag.de"),
    # Software & KI
    ("anthropic", "anthropic.com"), ("claude", "claude.ai"), ("openai", "openai.com"), ("chatgpt", "openai.com"),
    ("mistral", "mistral.ai"), ("github", "github.com"), ("google", "google.com"), ("microsoft", "microsoft.com"),
    ("adobe", "adobe.com"), ("dropbox", "dropbox.com"), ("proton", "proton.me"), ("mailbox.org", "mailbox.org"),
    ("1password", "1password.com"), ("bitwarden", "bitwarden.com"), ("nordvpn", "nordvpn.com"),
    ("mullvad", "mullvad.net"), ("jetbrains", "jetbrains.com"), ("notion", "notion.so"), ("canva", "canva.com"),
    ("hetzner", "hetzner.com"), ("netcup", "netcup.de"), ("strato", "strato.de"), ("ionos", "ionos.de"),
    ("cloudflare", "cloudflare.com"), ("todoist", "todoist.com"),
    # Versicherung & Gesundheit
    ("getsafe", "hellogetsafe.com"), ("allianz", "allianz.de"), ("huk", "huk.de"), ("axa", "axa.de"),
    ("ergo", "ergo.de"), ("debeka", "debeka.de"), ("signal iduna", "signal-iduna.de"), ("devk", "devk.de"),
    ("gothaer", "gothaer.de"), ("barmenia", "barmenia.de"), ("cosmos", "cosmosdirekt.de"),
    ("wuertt. gemeinde", "wgv.de"), ("württ. gemeinde", "wgv.de"), ("wgv", "wgv.de"), ("techniker", "tk.de"),
    ("barmer", "barmer.de"), ("aok", "aok.de"), ("dak", "dak.de"),
    # Energie & Wohnen
    ("vattenfall", "vattenfall.de"), ("e.on", "eon.de"), ("enbw", "enbw.com"), ("naturstrom", "naturstrom.de"),
    ("lichtblick", "lichtblick.de"), ("tibber", "tibber.com"), ("ostrom", "ostrom.de"), ("yello", "yello.de"),
    ("eprimo", "eprimo.de"), ("immergrün", "immergruen-energie.de"), ("immergruen", "immergruen-energie.de"),
    ("rheinische elektrizit", "immergruen-energie.de"), ("vonovia", "vonovia.de"),
    # Mobilität
    ("deutsche bahn", "bahn.de"), ("db vertrieb", "bahn.de"), ("bahncard", "bahn.de"), ("flixbus", "flixbus.de"),
    ("flixtrain", "flixbus.de"), ("flix se", "flixbus.de"),
    ("blablacar", "blablacar.de"), ("nextbike", "nextbike.de"), ("teilauto", "teilauto.net"), ("adac", "adac.de"),
    ("leipziger verkehrsbetriebe", "l.de"), ("bvg", "bvg.de"),
    # Vereine, Spenden, Politik
    ("ver.di", "verdi.de"), ("vereinte dienstleistungsgewerkschaft", "verdi.de"), ("campact", "campact.de"),
    ("rote hilfe", "rote-hilfe.de"), ("die linke", "die-linke.de"), ("medico", "medico.de"),
    ("sea-watch", "sea-watch.org"), ("sea watch", "sea-watch.org"), ("sea punks", "seapunks.de"),
    ("welthungerhilfe", "welthungerhilfe.de"), ("wikimedia", "wikimedia.de"), ("greenpeace", "greenpeace.de"),
    ("unicef", "unicef.de"), ("amnesty", "amnesty.de"), ("ärzte ohne grenzen", "aerzte-ohne-grenzen.de"),
    ("effektives spenden", "effektiv-spenden.org"), ("nabu", "nabu.de"), ("wwf", "wwf.de"),
    # Fitness, Freizeit, Handel
    ("urban sports", "urbansportsclub.com"), ("mcfit", "mcfit.com"), ("fitx", "fitx.de"), ("clever fit", "clever-fit.com"),
    ("paypal", "paypal.com"), ("klarna", "klarna.com"), ("zalando", "zalando.de"), ("ikea", "ikea.com"),
    # Alltag: Läden, Lieferdienste, Reisen – für die Buchungsliste
    ("rewe", "rewe.de"), ("edeka", "edeka.de"), ("aldi", "aldi-nord.de"), ("lidl", "lidl.de"), ("penny", "penny.de"),
    ("kaufland", "kaufland.de"), ("netto", "netto-online.de"), ("konsum leipzig", "konsum-leipzig.de"),
    ("alnatura", "alnatura.de"), ("denns", "biomarkt.de"), ("dm-drogerie", "dm.de"), ("dm drogerie", "dm.de"),
    ("rossmann", "rossmann.de"), ("lieferando", "lieferando.de"), ("wolt", "wolt.com"), ("too good to go", "toogoodtogo.com"),
    ("mcdonald", "mcdonalds.com"), ("burger king", "burgerking.de"), ("starbucks", "starbucks.de"),
    ("booking.com", "booking.com"), ("airbnb", "airbnb.de"), ("sunexpress", "sunexpress.com"), ("condor", "condor.com"),
    ("ryanair", "ryanair.com"), ("lufthansa", "lufthansa.com"), ("eurowings", "eurowings.com"), ("easyjet", "easyjet.com"),
    ("ebay", "ebay.de"), ("kleinanzeigen", "kleinanzeigen.de"), ("vinted", "vinted.de"), ("etsy", "etsy.com"),
    ("decathlon", "decathlon.de"), ("mediamarkt", "mediamarkt.de"), ("saturn", "saturn.de"), ("otto ", "otto.de"),
    ("h&m", "hm.com"), ("thalia", "thalia.de"), ("hornbach", "hornbach.de"), ("bauhaus", "bauhaus.info"),
    ("obi ", "obi.de"), ("tchibo", "tchibo.de"), ("shell", "shell.de"), ("aral", "aral.de"), ("esso", "esso.de"),
    ("eventim", "eventim.de"), ("steam", "steampowered.com"), ("nintendo", "nintendo.de"), ("playstation", "playstation.com"),
    ("dhl", "dhl.de"), ("hermes", "myhermes.de"), ("uber", "uber.com"), ("mangopay", "mangopay.com"),
    # Banken & Broker
    ("trade republic", "traderepublic.com"), ("scalable", "scalable.capital"), ("ing-diba", "ing.de"),
    ("consors", "consorsbank.de"), ("comdirect", "comdirect.de"), ("dkb", "dkb.de"), ("sparkasse", "sparkasse.de"),
    ("binance", "binance.com"), ("bank norwegian", "banknorwegian.de"), ("borussia dortmund", "bvb.de"),
]
_RE_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
QUELLEN = ("https://www.google.com/s2/favicons?domain={domain}&sz=128", "https://icons.duckduckgo.com/ip3/{domain}.ico")
# Banken und Quellen – die Oberfläche ordnet sie über die Art des Kontos zu
BANKEN = {"ing.de", "consorsbank.de", "paypal.com", "banknorwegian.de", "traderepublic.com", "binance.com",
          "splitwise.com", "sparkasse.de", "vr.de", "dkb.de", "comdirect.de", "postbank.de", "deutsche-bank.de",
          "commerzbank.de", "n26.com", "barclays.de", "c24.de", "scalable.capital", "revolut.com", "wise.com",
          "exodus.com", "getmonero.org"}
# Ein Stichwort gilt nur am Wortanfang, kurze nur als ganzes Wort – sonst bekäme „Bergmann“ das Logo von ERGO
_MARKEN_MUSTER = [(re.compile(r"(?<![a-zäöüß0-9])" + re.escape(w) + (r"(?![a-zäöüß0-9])" if len(w) <= 4 and not w.endswith(" ") else "")), d)
                  for w, d in MARKEN]
BEKANNT = {domain for _, domain in MARKEN} | BANKEN


def bildtyp(daten: bytes) -> str | None:
    """Medientyp nach dem Dateianfang – die Dienste liefern PNG, manchmal aber auch ICO oder JPEG."""
    if daten.startswith(b"\x89PNG"):
        return "image/png"
    if daten.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if daten.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    if daten.startswith(b"GIF8"):
        return "image/gif"
    if daten[:4] == b"RIFF" and daten[8:12] == b"WEBP":
        return "image/webp"
    return None


def domain_fuer(name: str) -> str | None:
    """Internetadresse eines bekannten Anbieters – None, wenn der Name zu keiner Marke passt."""
    n = f"{name.lower()} "
    return next((domain for muster, domain in _MARKEN_MUSTER if muster.search(n)), None)


def logo_datei(data_dir: Path, domain: str, http: httpx.Client | None = None) -> Path | None:
    """Pfad zum gespeicherten Logo; beim ersten Mal wird es geholt. None, wenn es keins gibt."""
    if domain not in BEKANNT or not _RE_DOMAIN.fullmatch(domain):
        return None  # nur Adressen aus der eigenen Liste – der Server ruft nichts Beliebiges ab
    ordner = Path(data_dir) / "logos"
    datei, fehlt = ordner / f"{domain}.png", ordner / f"{domain}.fehlt"
    if datei.exists():
        return datei
    if fehlt.exists():
        return None
    ordner.mkdir(parents=True, exist_ok=True)
    client = http or httpx.Client(timeout=8, follow_redirects=True)
    for vorlage in QUELLEN:
        try:
            r = client.get(vorlage.format(domain=domain))
        except httpx.HTTPError as e:
            log.info("Logo für %s nicht erreichbar: %s", domain, e)
            return None  # später erneut versuchen, nichts merken
        # sehr kleine Antworten sind das Platzhalter-Symbol des Dienstes
        if r.status_code == 200 and bildtyp(r.content) and len(r.content) > 400:
            datei.write_bytes(r.content)
            return datei
    fehlt.touch()
    return None
