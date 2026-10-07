<img src="frontend/public/icon-192.png" alt="" width="72" align="right">

# BankPocket

*Deutsch · [English](README.en.md)*

Selbst gehosteter Finanz-Tracker: Konten, Verträge, Budgets und Auswertungen – komplett auf deinem eigenen Server. Deine
Bankdaten bleiben bei dir: BankPocket ruft die Umsätze direkt bei deinen Banken ab und speichert sie nur lokal.

> **Stand und Haftung:** BankPocket ist ein privates Projekt ohne Gewähr und steht in keiner Verbindung zu den
> genannten Banken und Diensten. Es liest nur – Überweisungen kann es nicht auslösen. Im Alltag erprobt mit
> ING, Consorsbank, Trade Republic, Bank Norwegian und Binance; andere FinTS-Banken (Sparkassen, Volksbanken, DKB,
> comdirect …) nutzen denselben Weg, sind aber nicht einzeln getestet. Rückmeldungen dazu sind willkommen.

<p>
  <img src="docs/bilder/uebersicht.png" alt="Übersicht mit frei verfügbarem Betrag, Budgets und Konten" width="200">
  <img src="docs/bilder/vertraege.png" alt="Erkannte Verträge zum Bestätigen" width="200">
  <img src="docs/bilder/vertrag.png" alt="Ein Vertrag mit Kosten pro Jahr und nächster Zahlung" width="200">
  <img src="docs/bilder/analysen.png" alt="Vermögensverlauf mit Prognose" width="200">
</p>
<p><img src="docs/bilder/pc-uebersicht.png" alt="Übersicht am PC mit Kennzahlen und Konten" width="820"></p>

Die Bilder zeigen die mitgelieferten Demo-Daten (alles erfunden).

- **Automatische Bankabrufe** per FinTS (ING, Consorsbank, Sparkassen, Volks- und Raiffeisenbanken, DKB,
  comdirect und rund 2.000 weitere deutsche Banken), 4× täglich
- **Freigabe per Banking-App** (ING-App, SecurePlus-App) – etwa alle 90 Tage einmal bestätigen
- **Trade Republic** (Verrechnungskonto + Depot mit Plus/Minus seit Kauf und Wertverlauf je Position),
  **Bank Norwegian** (Kreditkarte über Enable Banking), **Binance** (Krypto in Euro) und **Splitwise**
- **Budgets** je Kategorie mit Warnung bei 80 % und Hochrechnung bis Monatsende
- **Übersicht** mit Kontogruppen, Salden, Gesamtsumme und **„vom Gehalt verfügbar“**: erkennt, wann dein Gehalt
  kommt (fester Tag oder z. B. letzter Bankarbeitstag, mit Wochenenden und Feiertagen), zeigt was pro Tag
  bleibt, welche Fixkosten noch abgehen und was am Ende voraussichtlich übrig ist
- **Verträge & Abos** werden automatisch erkannt (SEPA-Mandate, wiederkehrende Zahlungen, PayPal-Händler,
  Sparpläne – wöchentlich bis jährlich) und dir zur Bestätigung vorgelegt; erst bestätigte Verträge zählen mit.
  Dazu Warnung bei Preiserhöhung und überfälligen Zahlungen, eigene Verträge sammeln passende Buchungen ein
- **Analysen**: Vermögensverlauf mit Prognose, Monatsbilanz, Ausgaben nach Kategorie (Tortendiagramm) und nach
  Tag – jede Zahl führt per Klick zu den Buchungen dahinter
- **Buchungen**: Suche nach Text, Kategorie und Tag; je Buchung Kategorie, Tags, Notiz, Umbuchung und
  Vertragszuordnung; neue Buchungen bleiben markiert, bis du sie liest; unklare Buchungen ordnest du gesammelt zu
- **Kategorien** automatisch über eine große Händlerliste und den Buchungstext der Bank; BankPocket lernt aus
  deinen Korrekturen. Bei Kartenzahlungen zählt auch die Händlerart der Karte. Optional ordnet **Mistral**
  (Mistral-API) unbekannte Händler ein
- **Web-App** in hellem oder dunklem Design: auf dem Handy wie eine App (mit Push-Benachrichtigungen), am PC als
  Dashboard mit Kennzahlen
- **Datenschutz**: keine Cloud – PINs verschlüsselt auf deinem Server, Abruf direkt bei deiner Bank

## Erst ausprobieren (ohne Bankzugang)

Mit erfundenen Demo-Daten siehst du in ein paar Minuten, ob BankPocket etwas für dich ist. Gebraucht werden
Python ab 3.11 und Node.js ab 20:

```bash
git clone https://github.com/gurkengraeber/BankPocket.git bankpocket && cd bankpocket
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
BANKPOCKET_DATA_DIR=demo-daten .venv/bin/python -m bankpocket.demo
BANKPOCKET_DATA_DIR=demo-daten BANKPOCKET_AUTH=aus BANKPOCKET_SCHEDULER=aus \
  .venv/bin/uvicorn bankpocket.main:app --port 8000
```

Dann `http://localhost:8000` öffnen. `BANKPOCKET_AUTH=aus` schaltet die Anmeldung ab – nur für die Demo.

## 1. Voraussetzungen

1. Ein Rechner, der durchläuft (Heimserver, Raspberry Pi, NAS mit Docker) – am einfachsten Linux mit Docker und
   Docker Compose; prüfen mit `bash scripts/check_server.sh`. Ohne Docker genügen Python ab 3.11 und, zum Bauen
   der Oberfläche, Node.js ab 20.
2. Für Banken über FinTS (ING, Consorsbank, Sparkassen, Volksbanken, DKB …) eine **FinTS-Produkt-ID** der
   Deutschen Kreditwirtschaft: https://www.fints.org/de/hersteller/produktregistrierung
   Die Registrierung ist kostenlos, jede Installation braucht ihre eigene ID, und die Zusendung kann einige Tage
   dauern. Ohne sie lehnen die Banken den Abruf ab – alles andere (Trade Republic, Binance, CSV-Import, manuelle
   Konten) funktioniert schon vorher.
3. Die Banking-App deiner Bank auf dem Handy für die Freigabe (ING-App, SecurePlus, S-pushTAN …).

## 2. Installation

```bash
git clone https://github.com/gurkengraeber/BankPocket.git bankpocket && cd bankpocket
cp .env.example .env          # Produkt-ID eintragen, ggf. Abrufzeiten anpassen
docker compose up -d --build
docker compose exec -u bankpocket bankpocket python -m bankpocket.passwort   # Login-Passwort festlegen
docker compose exec -u bankpocket bankpocket python -m bankpocket.seed       # optional: Bargeld & Co. anlegen
```

Dann im Heimnetz öffnen: `http://<IP-deines-Servers>:8000`

**Wichtig:** Im Router keine Portfreigabe einrichten – BankPocket gehört nicht ins offene Internet. Für den Zugriff
von unterwegs siehe Abschnitt 4 (Tailscale).

**Aktualisieren:** `git pull && docker compose up -d --build`. Neue Spalten in der Datenbank legt BankPocket beim
Start selbst an; vor größeren Sprüngen schadet eine Sicherung nicht (Abschnitt 6).

### Ohne Docker

Wenn Docker auf dem Server nicht zur Verfügung steht, läuft BankPocket auch direkt mit Python:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..      # oder frontend/dist von einem anderen Rechner kopieren
cp .env.example .env
set -a; . ./.env; set +a
BANKPOCKET_DATA_DIR=$PWD/data .venv/bin/python -m bankpocket.passwort     # Login-Passwort festlegen
umask 077                                                 # Datenbank und Protokoll nur für dich lesbar
BANKPOCKET_DATA_DIR=$PWD/data BANKPOCKET_FRONTEND_DIR=$PWD/frontend/dist \
  .venv/bin/uvicorn bankpocket.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers
```

Genau ein Worker – Abrufe und Zeitplan laufen im selben Prozess. Für den Dauerbetrieb den letzten Befehl in ein
Startskript legen und mit `setsid nohup ./start.sh >> bankpocket.log 2>&1 &` starten (oder als systemd-Dienst).

Aktualisieren ohne Docker: `git pull`, `.venv/bin/pip install -r requirements.txt`, die Oberfläche neu bauen
(`cd frontend && npm ci && npm run build`) und BankPocket neu starten – aber nicht, während gerade ein Abruf oder
eine Anmeldung bei einer Bank läuft (BankPocket wartet beim Beenden bis zu 90 Sekunden auf laufende Abrufe).
War der Server zu einer Abrufzeit aus, holt BankPocket den Abruf kurz nach dem Start nach.

## 3. Konten verbinden

In der App: **Konto hinzufügen** → Quelle wählen. Beim ersten Abruf holt BankPocket so viel Historie,
wie die Quelle hergibt.

| Quelle | So geht's |
|---|---|
| **ING, Consorsbank** | Zugangsdaten eingeben → in der ING- bzw. SecurePlus-App bestätigen, falls die Bank danach fragt. Consorsbank: als Login die Kontonummer mit `001` am Ende. Beide liefern nur die letzten 90 Tage |
| **Sparkasse, Volksbank, DKB & Co.** | Bank per Name, Ort, BLZ oder IBAN suchen → Zugangsdaten eingeben → in der Banking-App (S-pushTAN, SecureGo plus, DKB-App …) bestätigen |
| **Trade Republic** | Handynummer mit Ländervorwahl (+49 …) + PIN → Anmeldung in der Trade-Republic-App bestätigen; ist dort die Zwei-Faktor-Anmeldung per Authenticator eingerichtet, erst den Code eingeben, dann in der App bestätigen. Inoffizielle Schnittstelle (pytr) – kann brechen, wenn Trade Republic etwas ändert |
| **Bank Norwegian** | Auf enablebanking.com kostenlos eine App für „Production“ registrieren, als Redirect-URL die in BankPocket angezeigte Adresse eintragen, das eigene Konto über „Activate by linking accounts“ freischalten, dann Application-ID und Inhalt der `.pem`-Datei in BankPocket einfügen. Ohne HTTPS landest du nach der Freigabe auf einer Fehlerseite – deren Adresse kopierst du in BankPocket. Freigabe etwa alle 180 Tage |
| **Binance** | Lese-Schlüssel anlegen (Profil → API-Verwaltung, nur „Lesen“), Key + Secret einfügen |
| **Splitwise** | Ohne Pro: als Konto anlegen und über „Stand eintragen“ den aktuellen Stand eintippen. Mit Splitwise Pro: auf secure.splitwise.com/apps eine App registrieren, den „API key“ einfügen |

Danach läuft alles automatisch. Etwa alle 90 Tage verlangt die Bank eine neue Freigabe – BankPocket
meldet sich dann per Push bzw. mit einem Hinweis in der App, und du tippst auf **Jetzt freigeben**.
Läuft die Trade-Republic-Anmeldung ab, fordert BankPocket im Hintergrund bewusst keine neue an (sonst
fragt die App zu zufälligen Zeiten) – du bekommst einen Hinweis und meldest dich mit einem Tipp neu an.

Umbuchungen zwischen deinen eigenen Konten (z. B. Girokonto → Trade Republic) zählen nicht als Ausgaben.
Trägst du in den Einstellungen unter „Umbuchungen“ deinen Namen ein, gilt das auch für Buchungen mit deinem Namen
als Absender oder Empfänger – also für eigene Konten, die nicht angebunden sind.
Splitwise korrigiert deine Ausgaben: Zahlst du für andere mit, zählt nur dein Anteil.

Schutz deines Zugangs: Lehnt die Bank die PIN ab, stoppt BankPocket alle automatischen Versuche, bis du die
Zugangsdaten in der App korrigierst – so sperrt die Bank deinen Zugang nicht nach drei Fehlversuchen.

## 4. HTTPS über Tailscale (für Push, App-Modus und Zugriff von unterwegs)

Browser erlauben Push-Benachrichtigungen und „Zum Startbildschirm“ nur über HTTPS. Am einfachsten geht das mit
Tailscale: BankPocket bekommt ein eigenes Gerät `bankpocket` in deinem Tailnet mit echtem Zertifikat – erreichbar
nur von deinen eigenen Tailscale-Geräten, zu Hause und unterwegs. Auf dem Server werden keine Ports belegt
(Apache & Co. bleiben unberührt), im Router wird nichts freigegeben.

Einmalig in der Tailscale-Verwaltung (login.tailscale.com):

1. **DNS → MagicDNS** und **HTTPS Certificates** aktivieren
2. **Settings → Keys → Generate auth key** (einmalig verwendbar reicht), Schlüssel in die `.env` als `TS_AUTHKEY`

Auf dem Server:

```bash
docker compose --profile tailscale up -d
docker compose logs tailscale | tail    # sollte „bankpocket“ als angemeldet zeigen
```

3. In der Tailscale-Verwaltung beim Gerät `bankpocket`: **⋯ → Disable key expiry** (sonst alle 180 Tage neu anmelden)
4. `TS_AUTHKEY` in der `.env` wieder leeren – er wird nicht mehr gebraucht
5. Auf dem Handy die Tailscale-App installieren und anmelden, dann in Chrome
   `https://bankpocket.<dein-tailnet>.ts.net` öffnen (genaue Adresse: in der Tailscale-App unter dem Gerät)
   – das erste Laden dauert ein paar Sekunden, weil das Zertifikat geholt wird
6. Chrome-Menü → **Zum Startbildschirm hinzufügen**, dann in BankPocket **Einstellungen → Push aufs Handy → Aktivieren**

Läuft alles über Tailscale, kannst du den Zugang im Heimnetz schließen: `BANKPOCKET_PORT=127.0.0.1:8000` in der `.env`.

**Alternative ohne Tailscale** (nur Heimnetz): `docker compose --profile https up -d` startet Caddy mit eigener
Zertifizierungsstelle auf `https://<BANKPOCKET_HOST>:8443`. Das Stammzertifikat
`caddy-daten/caddy/pki/authorities/local/root.crt` muss dann einmal aufs Handy (*Einstellungen → Sicherheit →
Verschlüsselung & Anmeldedaten → Zertifikat installieren → CA-Zertifikat*).

## 5. Kategorien mit KI (optional)

Unter **Einstellungen → Kategorien mit KI** einen API-Schlüssel von console.mistral.ai hinterlegen. Danach
ordnet Mistral nach jedem Abruf die Händler ein, die keine Regel erkennt – jeden nur einmal.

- Gesendet werden nur Händlername und ein gekürzter Verwendungszweck – ohne IBAN, Beträge, Kontostände oder
  längere Nummern. Überweisungen an Privatpersonen werden gar nicht gesendet.
- Deine Regeln und eigenen Korrekturen haben immer Vorrang.
- Modell: Mistral Small. Kosten: beim ersten Lauf wenige Cent, danach meist unter 10 Cent im Monat.

## 6. Datensicherung

Alles Wichtige liegt in `data/`:

| Datei | Inhalt |
|---|---|
| `bankpocket.db` | Konten, Umsätze, Verträge, Einstellungen |
| `secret.key` | Schlüssel für die gespeicherten PINs – **ohne ihn sind die PINs nicht lesbar** |
| `vapid_private.pem` | Schlüssel für Push-Benachrichtigungen |

Bei Tailscale zusätzlich `tailscale-daten/` sichern – sonst muss sich `bankpocket` neu anmelden.

BankPocket sichert diese drei Dateien einmal täglich (nach dem ersten automatischen Abruf) als ein Archiv nach
`data/backups/` – die letzten 14 Tage und je Monat die erste Sicherung, ein Jahr zurück. Stand und „Jetzt sichern“
stehen unter *Einstellungen → Sicherung*; schlägt eine Sicherung fehl, erscheint ein Hinweis.

Das allein hilft nicht, wenn die Festplatte ausfällt. Für eine verschlüsselte Kopie außer Haus in der `.env`:

```
BANKPOCKET_BACKUP_PASSWORT=ein-langes-passwort
BANKPOCKET_BACKUP_ZIEL=meinecloud:Backup/BankPocket
```

Das Ziel ist ein [rclone](https://rclone.org)-Ziel (einmal mit `rclone config` einrichten – pCloud, Nextcloud,
S3 und viele mehr) oder ein Ordner, z. B. auf einer zweiten Platte. Hochgeladen wird nur verschlüsselt (AES-256);
der Cloud-Anbieter sieht nur eine unlesbare Datei. **Das Passwort gehört in den Passwortmanager** – liegt es nur auf
dem Server, ist die Sicherung nach einem Ausfall wertlos.

Wiederherstellen:

```bash
python -m bankpocket.backup entschluesseln bankpocket-2026-10-04.tar.gz.enc   # mit dem Passwort aus der .env
# oder ganz ohne BankPocket:
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -in bankpocket-2026-10-04.tar.gz.enc -out sicherung.tar.gz
tar -xzf sicherung.tar.gz -C data/     # BankPocket vorher beenden
```

Die Server-Festplatte zusätzlich zu verschlüsseln schützt bei Diebstahl des Servers.

## Sicherheit im Überblick

- Bank-PINs und FinTS-Sitzungsdaten verschlüsselt (Fernet/AES), Schlüssel getrennt von der Datenbank
- Web-App mit Passwort (scrypt), Session-Cookie `HttpOnly` + `SameSite=Strict`, Bremse nach Fehlversuchen
- Der Browser lädt Skripte nur vom eigenen Server (Content-Security-Policy); die Datenbank ist nur für den
  Benutzer lesbar, unter dem BankPocket läuft
- Ohne HTTPS gehen Passwort und Sitzung unverschlüsselt durchs Heimnetz – nur in einem WLAN nutzen, dem du traust
- Push-Inhalte Ende-zu-Ende verschlüsselt; FinTS-Protokoll landet nicht im Log
- Container läuft ohne Root-Rechte

## Konten ohne Bankanbindung

- **Manuelle Konten** (Bargeld, Kautionen & Schulden, Krypto): *Konto hinzufügen → Manuelles Konto*,
  Buchungen per „Buchung hinzufügen“ oder den aktuellen Stand per „Stand eintragen“ (jeweils mit Datum).
  Selbst eingetragene Buchungen lassen sich nachträglich ändern und löschen; ein eingetragener Anfangsstand
  zählt im Vermögensverlauf nicht als Zugewinn
- **Konten umbenennen**: Stift oben rechts auf der Kontoseite
- **CSV-Import** (PayPal, Norwegian, ING- und Consorsbank-Export): *Konto hinzufügen → Kontoauszug importieren*.
  Spaltennamen werden automatisch erkannt; weitere Aliasse in `bankpocket/csv_import.py`. Enthält der Auszug
  keinen Kontostand, trägst du ihn über „Stand eintragen“ nach – erst dann zählt das Konto zum Vermögen.
- **Depotübersicht als CSV** (z. B. Consorsbank „Depotübersicht … Kompakt“): derselbe Weg, als neues Konto. Das
  Konto wird zum Depot mit allen Positionen, Kaufkursen und Plus/Minus seit Kauf; für einen neuen Stand einfach
  die nächste Depotübersicht in dasselbe Konto importieren.
- Exodus (BTC/ETH-Adressen) und Monero gibt es noch nicht – bis dahin als manuelles Konto unter „Crypto“.

## Funktionen im Detail

Was hinter den einzelnen Seiten steckt – Verträge, „frei verfügbar“, Analysen, Sparen, Versicherungen, Umbuchungen,
Kategorien – steht in [docs/FUNKTIONEN.md](docs/FUNKTIONEN.md).

## Hilfe bei Problemen

| Was du siehst | Was dahintersteckt |
|---|---|
| „Keine FinTS-Produkt-ID eingetragen“ | `BANKPOCKET_FINTS_PRODUCT_ID` in der `.env` setzen und BankPocket neu starten |
| „Die Bank hat die Anmeldung abgelehnt … Meldung der Bank: 9942 – PIN ungültig“ | Die Bank akzeptiert Login oder PIN nicht. **Nicht mehrfach wiederholen** – nach drei Fehlversuchen sperren Banken den Zugang. Erst auf der Website der Bank anmelden, dann die Zugangsdaten in BankPocket neu eintragen. Consorsbank: Login ist die Kontonummer mit `001` am Ende |
| Eine andere „Meldung der Bank“ | Fehlernummer und Text stammen direkt von der Bank – damit findest du in den Foren der Banking-Programme (Hibiscus, Subsembly) meist die Ursache; gern auch als Issue melden |
| Nur 90 Tage Buchungen | Mehr geben viele Banken per Abruf nicht heraus. Ältere Umsätze als CSV exportieren und über *Konto hinzufügen → Kontoauszug importieren* **in dasselbe Konto** laden – Buchungen, die es dort mit gleichem Datum und Betrag schon gibt, werden nicht doppelt angelegt |
| Altes CSV-Konto und neues Bankkonto nebeneinander | Das alte Konto öffnen → „Konto bearbeiten“ → „In ein anderes Konto übernehmen“. Buchungen, Kategorien und Verträge wandern ins Bankkonto, Doppelte bleiben einmal stehen |
| Trade Republic: „Fehler 401“ oder Zeitüberschreitung | Erst den Code aus der Authenticator-App eingeben, dann die Anfrage in der Trade-Republic-App bestätigen – zügig, die Anmeldung läuft nach rund zwei Minuten ab. Nach mehreren Fehlversuchen sperrt Trade Republic für einige Zeit |
| Bank Norwegian: Fehlerseite unter `https://localhost/…` | Ohne HTTPS gewollt: die Adresse aus der Adresszeile kopieren und in BankPocket einfügen. Steht darin `error=…`, ist das Konto bei Enable Banking nicht verknüpft |
| Kein Push, kein „Zum Startbildschirm“ | Geht nur über HTTPS – Abschnitt 4 |
| Verträge sind nach dem Löschen eines Kontos weg | Löschen nimmt die Buchungen mit, daran hängen die Verträge – die Rückfrage nennt, wie viele. Lieber „Konto ausblenden“ oder in ein anderes Konto übernehmen; sonst aus der Sicherung zurückholen |

Das Protokoll hilft weiter: `docker compose logs bankpocket | tail -50` (ohne Docker: `tail -50 bankpocket.log`).
PINs und der Inhalt der Bankdialoge stehen dort nicht.

## Bekannte Grenzen

- Banken über FinTS brauchen die Produkt-ID (siehe Voraussetzungen); ohne sie schlägt der Abruf fehl.
- Bank Norwegian über Enable Banking funktioniert im kostenlosen Zugang nur für die eigenen, dort verknüpften
  Konten. Für fremde Nutzer bräuchte es je eine eigene Enable-Banking-App oder einen Vertrag mit Enable Banking.
- Die Consorsbank lässt sich über Enable Banking nicht verknüpfen (Stand Oktober 2026); sie läuft über FinTS.
- ING und Consorsbank geben per Abruf nur 90 Tage heraus; Älteres kommt per CSV-Import.
- Binance liefert nur Guthaben, keine einzelnen Umsätze.
- Sitzungen gelten 180 Tage und lassen sich nicht einzeln beenden; ein neues Passwort meldet alle Geräte ab.
- Die Bremse nach Fehlversuchen beim Login gilt für alle gemeinsam und wird bei einem Neustart zurückgesetzt.

## Mitmachen

Fehlerberichte und Erfahrungen mit weiteren Banken sind willkommen – am besten als Issue mit der „Meldung der
Bank“ und dem Namen der Bank. Bitte **keine** Zugangsdaten, IBANs oder echten Kontoauszüge anhängen; die Tests
laufen ausschließlich mit erfundenen Daten.

## Entwicklung

```bash
pip install -r requirements-dev.txt
pytest                                    # Tests mit simulierter Bank, nur synthetische Daten
python scripts/oberflaeche_pruefen.py     # öffnet jede Seite mit Demo-Daten und meldet Fehler (braucht Chromium)

# Oberfläche mit Demo-Daten ansehen (ohne Bankzugang)
BANKPOCKET_DATA_DIR=demo-daten python -m bankpocket.demo
cd frontend && npm install && npm run build && cd ..
BANKPOCKET_DATA_DIR=demo-daten BANKPOCKET_AUTH=aus BANKPOCKET_SCHEDULER=aus \
  uvicorn bankpocket.main:app --port 8000

# Oberfläche mit Hot-Reload (API läuft auf :8000)
cd frontend && npm run dev
```

Erkennung ohne Server testen: `python -m bankpocket.detect exports/mein-export.csv`

API-Dokumentation (nach Login): `/api/docs`

### Aufbau

| Teil | Wo |
|---|---|
| FinTS-Abruf, Freigabe, TAN-Verfahren | `bankpocket/fetchers/fints_source.py` |
| Bankliste (BLZ → FinTS-Adresse) | `bankpocket/bankliste.py`, erzeugt mit `scripts/bankliste_bauen.py` aus [fints-institute-db](https://github.com/jhermsmeier/fints-institute-db) (CC0) |
| Trade Republic, Bank Norwegian (Enable Banking), Binance, Splitwise | `bankpocket/fetchers/trade_republic.py`, `enablebanking.py`, `binance.py`, `splitwise.py` |
| Abruf-Jobs, Status, Hinweise | `bankpocket/sync.py`, `bankpocket/notify.py` |
| Zeitplan | `bankpocket/scheduler.py` |
| Vertragserkennung, Kategorien | `bankpocket/contracts.py` |
| Umbuchungen paaren | `bankpocket/umbuchungen.py` |
| Logos | `bankpocket/logos.py` |
| CSV-Import (Kontoauszug, Depotübersicht) | `bankpocket/csv_import.py` |
| Zahltag-Erkennung (Bankarbeitstage, Feiertage) | `bankpocket/zahltag.py` |
| KI-Einordnung (Mistral-API) | `bankpocket/ki.py` |
| Auswertungen, Budgets | `bankpocket/analysen.py` |
| API | `bankpocket/api.py`, `bankpocket/routes/` |
| Oberfläche (Svelte + Tailwind) | `frontend/src/` |

## Lizenz

BankPocket steht unter der [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0): Du darfst es nutzen,
ändern und weitergeben. Wer eine geänderte Fassung weitergibt oder anderen als Dienst anbietet, muss deren
Quelltext unter derselben Lizenz offenlegen. Es gibt keine Gewährleistung.

Verwendet werden unter anderem [python-fints](https://github.com/raphaelm/python-fints) (LGPL-3.0),
[pytr](https://github.com/pytr-org/pytr) (MIT) und die Bankliste aus
[fints-institute-db](https://github.com/jhermsmeier/fints-institute-db) (CC0).
