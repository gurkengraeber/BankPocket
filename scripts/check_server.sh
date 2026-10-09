#!/usr/bin/env bash
# Prüft das Server-Setup für BankPocket. Auf dem Heimserver ausführen: bash scripts/check_server.sh
ok()   { printf '  [ok]   %s\n' "$*"; }
warn() { printf '  [FEHLT] %s\n' "$*"; }

echo "== System =="
. /etc/os-release 2>/dev/null && ok "$PRETTY_NAME ($(uname -m), Kernel $(uname -r))"
ok "CPU-Kerne: $(nproc), RAM: $(free -h | awk '/Mem:/{print $2}')"
ok "Frei auf $(pwd): $(df -h . | awk 'NR==2{print $4}')"

echo "== Docker =="
if command -v docker >/dev/null; then
  ok "$(docker --version)"
  docker info >/dev/null 2>&1 && ok "Daemon erreichbar" || warn "Daemon nicht erreichbar (Rechte? 'sudo usermod -aG docker \$USER')"
  docker compose version >/dev/null 2>&1 && ok "$(docker compose version)" || warn "Docker Compose Plugin"
else warn "docker"; fi

echo "== Python =="
if command -v python3 >/dev/null; then
  ok "$(python3 --version)"
  python3 -c 'import sys; sys.exit(sys.version_info < (3,11))' || warn "Python >= 3.11 empfohlen"
else warn "python3"; fi
command -v git >/dev/null && ok "git" || warn "git"

echo "== VPN (Zugriff nur per VPN) =="
command -v wg >/dev/null && ok "WireGuard ($(wg --version | head -1))" || warn "WireGuard (wg)"
command -v tailscale >/dev/null && ok "Tailscale" || warn "Tailscale (eines von beiden genügt)"

echo "== Netzwerk-Exposition =="
echo "  Auf allen Interfaces lauschende Ports (sollten nicht ins Internet zeigen):"
(ss -tlnH 2>/dev/null || true) | awk '{print "    " $4}' | sort -u
