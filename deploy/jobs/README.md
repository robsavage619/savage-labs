# Unattended job definitions

`jobs/<job>.md` is the run prompt and `jobs/<job>.conf` sets `TOOLS` and `TURNS` for
`run-job.sh <job>`. On the host they live in `~/.config/shc/jobs/`.

## `lab`

`lab.md`, `lab.conf` and `../com.savage.shc-lab.plist` are copies of the files running
on the host (checked byte for byte on 2026-11-23), with the host's home directory
written as `__HOME__` (and the plist's user as `__USER__`). The cycle: one specialist
a week (ISO week number mod 4: 0 hypertrophy, 1 recovery, 2 conditioning, 3
metabolic), a blind methodologist, `run-all`, then a blind devil's advocate on
decisive results. The schedule is Monday at 13:00 only, set 2026-11-24 while few
experiments are live (plan decision D4); the run also reports the experiment block
scorer state. To revert: restore the Weekday 1 to 4 entries in the plist and, in
`lab.md` section 0, pick the specialist by weekday (Mon hypertrophy, Tue recovery,
Wed conditioning, Thu metabolic); then reinstall on the host. Vault reading is host-specific: the agents read a
read-only copy under `~/.config/shc/vault`, and the host has no literature search.

When the host copy changes, copy it back here with the same substitution so the repo
stays the source of truth.

## Install

`sync-claude-copies.sh` copies `jobs/` to the host only for files that are absent
there, then fills in `__HOME__`; `--force-jobs` overwrites the host's files. `imac.sh`
does not install the lab plist (its loop names labels explicitly), so changing the
host schedule stays a deliberate step.

## Heartbeat

`run-job.sh` posts `job-runner` notebook entries (`<job> job started`,
`<job> job finished exit N`) to the Lab notebook, best effort. A missing "started"
entry on a scheduled day means the job never reached the API check.
