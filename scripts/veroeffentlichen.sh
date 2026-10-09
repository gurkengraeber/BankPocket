#!/usr/bin/env bash
# Veröffentlicht den eingecheckten Stand von „main“ als fertigen Zweig „release“ auf GitHub: der Code und die
# gebaute Oberfläche (frontend/dist, im Repo sonst nicht enthalten). Der Heimserver holt „release“ alle paar
# Minuten selbst (scripts/auto_deploy.sh) – ein Server ohne Node braucht so nichts zu bauen.
#
#     scripts/veroeffentlichen.sh
#
# „release“ wird jedes Mal neu geschrieben (ein Commit, kein wachsender Verlauf).
set -euo pipefail
cd "$(dirname "$0")/.."

[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "Bitte auf dem Zweig main ausführen." >&2; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "Es gibt nicht eingecheckte Änderungen – erst committen." >&2; exit 1; }

remote=$(git remote get-url origin)
stand=$(git rev-parse --short HEAD)
[ -d frontend/node_modules ] || (cd frontend && npm ci)
(cd frontend && npm run build >/dev/null)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git archive HEAD | tar -x -C "$tmp"
mkdir -p "$tmp/frontend"
cp -r frontend/dist "$tmp/frontend/dist"
chmod +x "$tmp"/scripts/*.sh

cd "$tmp"
git init -q -b release
git add -A -f   # frontend/dist steht in der .gitignore
git -c user.name=BankPocket -c user.email=noreply@bankpocket.invalid commit -q -m "Stand $stand"
git push -q --force "$remote" release
echo "release = Stand $stand veröffentlicht – der Server übernimmt ihn innerhalb von 5 Minuten."
