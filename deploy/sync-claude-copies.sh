#!/usr/bin/env zsh
# Refreshes the host's copies of the files its unattended Claude jobs read.
# Usage: deploy/sync-claude-copies.sh [--force-jobs] user@host
# deploy/jobs/ is installed to ~/.config/shc/jobs only for files the host lacks;
# --force-jobs overwrites the host's working prompts and confs.
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
force_jobs=0
[ "${1:-}" = --force-jobs ] && { force_jobs=1; shift; }
host=$1
cd "${0:A:h}/.."
: "${SHC_MEMORY_DIR:=$HOME/.claude/projects/${PWD//[\/.]/-}/memory}"
: "${SHC_SKILL_DIR:=$HOME/.claude/skills/shc-workout}"
[ -d "$SHC_MEMORY_DIR" ] || SHC_MEMORY_DIR=
[ -d "$SHC_SKILL_DIR" ] || SHC_SKILL_DIR=
ssh "$host" 'mkdir -p ~/.config/shc/agents ~/.config/shc/memory ~/.config/shc/shc-workout ~/.config/shc/vault/wiki ~/.config/shc/jobs'

rsync -a --delete .claude/agents/ "${host}:.config/shc/agents/"
echo "agents: synced"
rsync -a --chmod=u+rwx,go+rx deploy/run-job.sh "${host}:.config/shc/run-job.sh"
echo "run-job.sh: installed"

# The committed job files carry __HOME__ in place of the host's home directory; fill it
# in here so the copy and the host can be compared byte for byte.
remote_home=$(ssh "$host" 'printf %s "$HOME"')
jobs_src=$(mktemp -d "${TMPDIR:-/tmp}/shc-jobs.XXXXXX") || { echo "jobs: could not make a temp dir, nothing installed" >&2; exit 1; }
[ -d "$jobs_src" ] || { echo "jobs: temp dir missing, nothing installed" >&2; exit 1; }
trap 'rm -rf "$jobs_src"' EXIT
for f in deploy/jobs/*; do
  [ "${f:t}" = README.md ] && continue
  sed "s#__HOME__#${remote_home}#g" "$f" > "$jobs_src/${f:t}"
done
# Host files that exist and differ from the repo: drift someone must resolve, never silence.
drift=$(rsync -anc --existing --out-format='%n' "$jobs_src/" "${host}:.config/shc/jobs/" | grep -v '/$' || true)
if [ "$force_jobs" -eq 1 ]; then
  rsync -ac "$jobs_src/" "${host}:.config/shc/jobs/"
  echo "jobs: installed, host copies overwritten (--force-jobs)${drift:+: ${drift//$'\n'/, }}"
else
  rsync -a --ignore-existing "$jobs_src/" "${host}:.config/shc/jobs/"
  if [ -n "$drift" ]; then
    echo "jobs: WARNING host differs from the repo for ${drift//$'\n'/, }; kept the host copy. Diff it, then copy it back into deploy/jobs or rerun with --force-jobs"
  else
    echo "jobs: in sync with the repo"
  fi
fi

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
