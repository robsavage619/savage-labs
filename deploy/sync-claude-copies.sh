#!/usr/bin/env zsh
# Refreshes the host's copies of the files its unattended Claude jobs read.
# Usage: deploy/sync-claude-copies.sh user@host
# The sources live outside this repo, so their paths come from the environment
# (nothing personal belongs in a public repo). An unset one is skipped with a note:
#   SHC_MEMORY_DIR  the project's memory files  -> ~/.config/shc/memory
#                   (default: this checkout's Claude Code project memory)
#   SHC_SKILL_DIR   the shc-workout skill       -> ~/.config/shc/shc-workout
#                   (default: ~/.claude/skills/shc-workout)
#   SHC_VAULT_WIKI  vault wiki notes            -> ~/.config/shc/vault/wiki (read-only on the host)
# The research agents and the job runner always come from this repo.
# deploy/imac.sh runs this on every deploy, so the copies cannot drift for long.
set -euo pipefail
host=$1
cd "${0:A:h}/.."
: "${SHC_MEMORY_DIR:=$HOME/.claude/projects/${PWD//[\/.]/-}/memory}"
: "${SHC_SKILL_DIR:=$HOME/.claude/skills/shc-workout}"
[ -d "$SHC_MEMORY_DIR" ] || SHC_MEMORY_DIR=
[ -d "$SHC_SKILL_DIR" ] || SHC_SKILL_DIR=
ssh "$host" 'mkdir -p ~/.config/shc/agents ~/.config/shc/memory ~/.config/shc/shc-workout ~/.config/shc/vault/wiki'

rsync -a --delete .claude/agents/ "${host}:.config/shc/agents/"
echo "agents: synced"
rsync -a --chmod=u+rwx,go+rx deploy/run-job.sh "${host}:.config/shc/run-job.sh"
echo "run-job.sh: installed"

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
