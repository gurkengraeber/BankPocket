#!/bin/sh
# Datenverzeichnis dem App-Benutzer geben (Docker legt Bind-Mounts als root an),
# dann ohne Root-Rechte weiterlaufen.
set -e
if [ "$(id -u)" = "0" ]; then
  chown -R bankpocket:bankpocket /data
  exec setpriv --reuid=bankpocket --regid=bankpocket --init-groups "$@"
fi
exec "$@"
