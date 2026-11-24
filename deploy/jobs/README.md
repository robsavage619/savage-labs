# Unattended job definitions

`jobs/<job>.md` is the run prompt and `jobs/<job>.conf` sets `TOOLS` and `TURNS` for
`run-job.sh <job>`. On the host they live in `~/.config/shc/jobs/`.

## `lab` is a reconstruction

The real `lab.md`, `lab.conf` and the `com.savage.shc-lab` plist existed only on the
host. These files were drafted from `.claude/agents/research-*.md` and the cycle the
README describes (specialists, methodologist, run-all, devil's advocate). They are
not copies. **Diff them against the host files before overwriting anything.**

Guessed, not known:

- The whole prompt wording, the specialist order, and the "already challenged" test.
- `TOOLS` (`Task,Bash,Read,Grep,Glob`) and `TURNS=200`.
- The schedule: weekdays 13:00, inferred from specialist notebook entries around
  13:00 on 11-16, 17, 18, 19 and 23. A placeholder until it is checked against the host plist.
- Vault retrieval and the discovery-queue path are omitted: the agents say "the run
  prompt gives the path", and that path is host-specific. Add them from the host prompt.

## Install

`sync-claude-copies.sh` copies `jobs/` to the host only for files that are absent
there; `--force-jobs` overwrites. `imac.sh` does not install the lab plist (its loop
names labels explicitly), so adding it to the host schedule stays a deliberate step.

## Heartbeat

`run-job.sh` posts `job-runner` notebook entries (`<job> job started`,
`<job> job finished exit N`) to the Lab notebook, best effort. A missing "started"
entry on a scheduled day means the job never reached the API check.
