#!/usr/bin/env zsh
# Ships the code to the always-on host Mac and (re)starts it under launchd.
# Usage, from anywhere: deploy/imac.sh user@host
# Code only. The database and the backend env file live on the host and are never
# touched here (rsync --delete leaves excluded paths alone); they moved once, by hand.
set -euo pipefail
host=$1
cd "${0:A:h}/.."

rsync -az --delete \
  --exclude node_modules --exclude .venv --exclude .next --exclude .git \
  --exclude 'backend/data/' --exclude '.claude/' --exclude '.env*' \
  ./ "${host}:Projects/savage-health-center/"

ssh -t "$host" 'set -e
cd ~/Projects/savage-health-center
export PATH=$HOME/.local/node/bin:$HOME/.local/bin:$PATH
(cd backend && uv sync --no-dev --frozen)
# Empty API base: the browser calls /api on the same origin, which tailscale serve routes to :8000.
(cd frontend && npm ci --no-audit --no-fund && NEXT_PUBLIC_API_URL= npm run build)
mkdir -p ~/Library/Logs/shc-sync
tmp=$(mktemp -d)
for label in com.savage.shc-api com.savage.shc-web com.savage.shc-sync; do
  sed -e "s#__HOME__#$HOME#g" -e "s#__USER__#$(whoami)#g" deploy/$label.plist > "$tmp/$label.plist"
  sudo install -m 644 -o root -g wheel "$tmp/$label.plist" /Library/LaunchDaemons/$label.plist
  sudo launchctl bootout system/$label 2>/dev/null || true
  # bootout returns before the job is gone; bootstrapping too early fails with error 5.
  while sudo launchctl print system/$label >/dev/null 2>&1; do sleep 0.5; done
  sudo launchctl bootstrap system /Library/LaunchDaemons/$label.plist
done
echo deployed'
