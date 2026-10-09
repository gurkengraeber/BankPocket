#!/bin/bash
# Automatisches Update auf dem Heimserver (Cronjob alle 5 Minuten, wie beim eventbot):
#
#     */5 * * * * /bin/bash /home/<benutzer>/bankpocket/scripts/auto_deploy.sh
#
# Holt den Zweig „release“ von GitHub (siehe scripts/veroeffentlichen.sh) und übernimmt ihn, wenn er sich
# geändert hat. Nur der Code und die Oberfläche werden ersetzt – .env, data/ und .venv bleiben unberührt.
# Neu gestartet wird nur, wenn sich bankpocket/ oder requirements.txt geändert haben (die Oberfläche liest
# BankPocket direkt von der Platte), und nie mitten in einem Abruf. Läuft BankPocket nach dem Neustart nicht,
# geht es auf den vorigen Stand zurück und versucht denselben Stand nicht noch einmal.
# Ausschalten: Datei .autodeploy_aus im Ordner anlegen.
# Alles in einer Funktion, damit das Skript sich selbst ersetzen darf (bash liest sonst mitten im Lauf weiter).
export PATH=/usr/local/bin:/usr/bin:/bin

main() {
    cd "$(dirname "$(readlink -f "$0")")/.." || exit 1
    [ -e .autodeploy_aus ] && exit 0
    local LOG="$PWD/auto_deploy.log"
    exec 9>.auto_deploy.lock
    flock -n 9 || exit 0
    log() { echo "[$(date -Is)] $*" >> "$LOG"; }
    if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 200000 ]; then
        tail -n 300 "$LOG" > "$LOG.neu" && mv "$LOG.neu" "$LOG"
    fi

    git fetch -q origin release 2>>"$LOG" || { log "git fetch fehlgeschlagen"; exit 0; }
    local lokal neu geaendert neustart=0
    lokal=$(git rev-parse HEAD 2>/dev/null || echo "-")
    neu=$(git rev-parse FETCH_HEAD)
    [ "$lokal" = "$neu" ] && exit 0
    [ "$neu" = "$(cat .auto_deploy_fehler 2>/dev/null)" ] && exit 0   # dieser Stand lief schon einmal nicht

    geaendert=$(git diff --name-only "$lokal" "$neu" 2>/dev/null || echo "bankpocket/")
    echo "$geaendert" | grep -qE '^(bankpocket/|requirements\.txt$)' && neustart=1
    if [ "$neustart" = 1 ] && [ "$(abrufe_laufen)" != 0 ]; then
        log "Update ${neu:0:7} wartet: gerade läuft ein Abruf"
        exit 0
    fi

    log "Update ${lokal:0:7} -> ${neu:0:7} ($(echo "$geaendert" | wc -l) Dateien, Neustart: $neustart)"
    git reset -q --hard "$neu" 2>>"$LOG" || { log "git reset fehlgeschlagen"; exit 0; }
    git clean -fdxq -- frontend/dist   # alte Dateien der Oberfläche
    if echo "$geaendert" | grep -q '^requirements\.txt$'; then
        .venv/bin/pip install -q -r requirements.txt >> "$LOG" 2>&1 || log "pip install fehlgeschlagen"
    fi
    [ "$neustart" = 0 ] && { log "Fertig (nur Oberfläche, kein Neustart)"; exit 0; }

    neu_starten
    if gesund; then
        log "Fertig, BankPocket läuft auf ${neu:0:7}"
    else
        log "FEHLER: BankPocket startet mit ${neu:0:7} nicht – zurück auf ${lokal:0:7}"
        echo "$neu" > .auto_deploy_fehler
        [ "$lokal" != "-" ] && git reset -q --hard "$lokal" && neu_starten
        gesund && log "Zurückgesetzt, BankPocket läuft wieder" || log "FEHLER: läuft auch nach dem Zurücksetzen nicht"
    fi
}

# Anzahl laufender Abrufe; bei jeder Unsicherheit „1“, damit nicht mitten in einem Abruf neu gestartet wird
abrufe_laufen() {
    local n
    n=$(.venv/bin/python -c '
import sqlite3
c = sqlite3.connect("file:data/bankpocket.db?mode=ro", uri=True)
print(c.execute("select count(*) from connections where status=?", ("laeuft",)).fetchone()[0])' 2>/dev/null)
    case "$n" in ''|*[!0-9]*) echo 1 ;; *) echo "$n" ;; esac
}

neu_starten() {
    pkill -f "[u]vicorn bankpocket"
    for _ in $(seq 1 100); do pgrep -f "[u]vicorn bankpocket" >/dev/null || break; sleep 1; done   # wartet auf laufende Abrufe
    setsid nohup ./start.sh >> bankpocket.log 2>&1 < /dev/null &
}

gesund() {
    for _ in $(seq 1 30); do
        [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/)" = 200 ] && return 0
        sleep 1
    done
    return 1
}

main "$@"; exit $?
