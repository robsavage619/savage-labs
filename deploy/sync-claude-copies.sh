#!/usr/bin/env zsh
# Refreshes the host's copies of the files its unattended Claude jobs read.
# Usage: deploy/sync-claude-copies.sh user@host
# The sources live outside this repo, so their paths come from the environment
# (nothing personal belongs in a public repo). An unset one is skipped with a note:
#   SHC_MEMORY_DIR  the project's memory files  -> ~/.config/shc/memory
#   SHC_SKILL_DIR   the shc-workout skill       -> ~/.config/shc/shc-workout
#   SHC_VAULT_WIKI  vault wiki notes            -> ~/.config/shc/vault/wiki (read-only on the host)
# The research agents always come from this repo's .claude/agents.
set -euo pipefail
host=$1
cd "${0:A:h}/.."
ssh "$host" 'mkdir -p ~/.config/shc/agents ~/.config/shc/memory ~/.config/shc/shc-workout ~/.config/shc/vault/wiki'

rsync -a --delete .claude/agents/ "${host}:.config/shc/agents/"
echo "agents: synced"

copy() {  # copy <env value> <label> <remote dir>
  if [ -z "${1:-}" ]; then echo "$2: skipped (variable not set)"; return; fi
  rsync -a --delete "${1%/}/" "${host}:$3/" && echo "$2: synced"
}
copy "${SHC_MEMORY_DIR:-}" memory .config/shc/memory
copy "${SHC_SKILL_DIR:-}" skill .config/shc/shc-workout
if [ -n "${SHC_VAULT_WIKI:-}" ]; then
  ssh "$host" 'chmod -R u+w ~/.config/shc/vault'
  copy "$SHC_VAULT_WIKI" vault .config/shc/vault/wiki
  ssh "$host" 'chmod -R a-w ~/.config/shc/vault'
else
  echo "vault: skipped (variable not set)"
fi
