#!/usr/bin/env zsh
# Copies the host's nightly database backups to this machine, so the data survives
# the host's disk. Usage: scripts/pull-backups.sh user@host [dest-dir]
# The host keeps 7 days; this keeps every copy it has ever pulled (they are the history).
set -euo pipefail
host=$1
dest=${2:-$HOME/Backups/shc}
mkdir -p "$dest"
rsync -a --ignore-existing "${host}:Projects/savage-health-center/backend/data/backups/" "$dest/"
echo "$(ls "$dest" | wc -l | tr -d ' ') backups in $dest, newest: $(ls -t "$dest" | head -1)"
