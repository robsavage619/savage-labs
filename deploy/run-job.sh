#!/bin/zsh
# Runs one unattended Claude Code job on the host: run-job.sh <job>
# Installed to ~/.config/shc/run-job.sh by deploy/sync-claude-copies.sh; launchd
# (com.savage.shc-coach, com.savage.shc-lab) calls that copy.
# Prompt: ~/.config/shc/jobs/<job>.md; tools and turn cap: ~/.config/shc/jobs/<job>.conf
# (TOOLS=..., TURNS=...). Output goes to ~/Library/Logs/shc-<job>.log.
# Alerts: if ~/.config/shc/ntfy-topic exists, a failed run, a down API or a token
# near expiry posts a one-line notice to ntfy.sh/<topic>. It never carries health data.
set -u
job=$1
cfg=$HOME/.config/shc
log=$HOME/Library/Logs/shc-$job.log
# launchd gives a bare PATH. ~/.local/bin is where the native installer links
# `claude`; without it every run died with "command not found: claude" (2026-11-12..17).
export PATH=$HOME/.local/bin:$HOME/.local/node/bin:/usr/local/bin:/usr/bin:/bin
# A boot daemon has no TMPDIR; agents write scratch files there.
export TMPDIR=$cfg/tmp/
mkdir -p "$TMPDIR"

say() { echo "$*" >> "$log"; }
alert() {
  say "alert: $1"
  [ -f "$cfg/ntfy-topic" ] || { say "alert: not sent (no $cfg/ntfy-topic)"; return; }
  curl -s -m 10 -o /dev/null -H "Title: SHC $job" -d "$1" "https://ntfy.sh/$(tr -d '[:space:]' < "$cfg/ntfy-topic")" \
    || say "alert: send failed"
}

say "=== $(date '+%F %T') $job"

command -v claude >/dev/null || { alert "claude not found on PATH"; say "=== exit 127"; exit 127; }

# Strip whitespace: the token prints wrapped, so a copy carries line breaks.
export CLAUDE_CODE_OAUTH_TOKEN=$(tr -d '[:space:]' < "$cfg/claude-oauth")
# setup-token tokens last one year and do not refresh. claude-oauth.expires holds
# the YYYY-MM-DD it dies; warn from 30 days out so it is renewed before runs fail.
if [ -f "$cfg/claude-oauth.expires" ]; then
  left=$(( ( $(date -j -f %F "$(cat "$cfg/claude-oauth.expires")" +%s) - $(date +%s) ) / 86400 ))
  [ "$left" -le 30 ] && alert "Claude token expires in $left days: run 'claude setup-token' on the iMac"
fi

# The API restarts itself under launchd (KeepAlive). Give it 3 minutes rather than
# spend a whole Claude run discovering it is down.
for i in {1..18}; do
  curl -s -m 5 -o /dev/null -f http://127.0.0.1:8000/api/workout/routine-status && break
  [ "$i" -eq 18 ] && { alert "API on :8000 down for 3 min, run skipped"; say "=== exit 2"; exit 2; }
  sleep 10
done

# Heartbeat: a Lab notebook entry at start and end, so a missed run is visible on the
# Lab screen. Best effort: a failed POST never changes the job or its exit code.
beat() {
  curl -s -m 10 -o /dev/null -X POST -H 'Content-Type: application/json' \
    -d "{\"author\":\"job-runner\",\"kind\":\"note\",\"title\":\"$1\"}" \
    http://127.0.0.1:8000/api/research/notebook || say "heartbeat: post failed"
}
beat "$job job started"

source "$cfg/jobs/$job.conf"
cd "$HOME/Projects/savage-health-center" || { alert "repo missing"; exit 1; }
claude -p "$(cat "$cfg/jobs/$job.md")" --allowedTools "$TOOLS" --max-turns "$TURNS" < /dev/null >> "$log" 2>&1
rc=$?
say "=== exit $rc"
beat "$job job finished exit $rc"
[ "$rc" -eq 0 ] || alert "run failed (exit $rc), see ~/Library/Logs/shc-$job.log"
exit $rc
