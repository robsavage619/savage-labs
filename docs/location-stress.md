# Place and stress — Design doc

**Status:** approved (revised: places are discovered, not predefined)
**Date:** 2026-11-11
**Author:** Rob

## Context
SHC now runs on an always-on host, and the phone reaches it over the tailnet. That makes it possible to know *where* Rob was and line it up with what his body was doing. The question: which places raise stress, and do days spent at a place cost him the next morning?

Two stress signals exist:

- **Minute-level stress.** WHOOP's 0–3 stress score, from the private API, lands in `whoop_stress_timeline` (`sampled_at`, `value`, `level`). The table holds 31 days (Aug 5 – Sep 5 2026). Its sync has never been scheduled, and the private-API login did not move to the host.
- **Daily signals.** Overnight HRV, resting HR and recovery already sync daily.

No location data exists.

## Goals
- Find the places Rob spends time at without him listing them first, including ones he would never think to name.
- Ask whether a place raises minute-level stress compared with Rob's own baseline for that hour of day, with exercise minutes excluded.
- Ask whether time at a place predicts next-morning HRV.
- Collect silently until there is enough data; then show results on the Recovery page, where Rob can name a place.

## Non-goals
- No map, no reverse geocoding, no third-party location service. Places are numbered until Rob names them.
- No coordinates, places or names in the repo. The repo is public; location lives only in the host's database (`backend/data`, gitignored).
- No causal claims. Place is confounded with time of day, activity and who Rob is with, so results are associations with stated uncertainty.

## Options considered

### A — OwnTracks, significant-changes mode, HTTP to the host
- **Pros:** fully automatic. Wakes on cell and Wi-Fi changes, so it is light on battery. Queues points while offline and resends them. Needs no setup per place.
- **Cons:** points are sparse, a few per move, so stays have to be inferred from gaps. Stores a location trail on the host.

### B — OwnTracks region mode (places predefined on the phone)
- **Pros:** no coordinates leave the phone.
- **Cons:** only finds places Rob already thought to define. Rejected for that reason.

### C — Google Maps Timeline export
- **Pros:** best place detection.
- **Cons:** export is manual on iOS, with no API and no automation.

### D — Shortcuts hourly sampling
- **Pros:** no new app.
- **Cons:** misses most visits shorter than an hour.

## Decision
**Option A.**

Pieces:

1. **Ingest:** `POST /api/location/owntracks`, using HTTP Basic auth where the password is the webhook key.
   - It accepts `location` messages and stores `(tst, lat, lon, acc)`. Points with accuracy worse than 500 m are dropped. Resends are deduplicated on `tst`.
   - It also accepts `transition` messages: if Rob does define a region on the phone, its `desc` names the matching place.
   - Every other message type is ignored. The endpoint replies `[]`, as OwnTracks expects.
2. **Stays:** a point followed by no movement beyond 150 m for at least 10 minutes is a stay. It runs from that point to the first point more than 150 m away, capped at 12 h, since a long silence can mean the phone was off.
3. **Places:**
   - Each stay joins the nearest known place within 150 m, or founds a new one.
   - Places are stored with a stable id. A place has a name only once Rob gives it one, through the card or a phone region; until then it is shown as "Place N".
   - The card shows each place's typical days and hours to help Rob recognise it, plus an Apple Maps link that is opened only when he taps it.
4. **Retention:** raw points are deleted after 90 days. Stays keep only their place id and times.
5. **Stress source:** schedule the private-metrics sync daily on the host through an API endpoint, since a CLI process can't open the DB while the API holds it. Re-do the private-API login there; its tokens go to the host token file.
6. **Analysis, place → stress:** for each place, compare minute-stress during visits with Rob's mean stress at the same hour of day elsewhere.
   - Minutes inside a workout, and the 30 minutes after one, are excluded.
   - The visit is the unit of analysis, because minutes within a visit are autocorrelated.
   - The report gives the mean difference, a 95% interval, n visits, and stress coverage.
7. **Analysis, place → next morning:** daily hours at each place against next-morning HRV deviation, through the Lab's `estimate()`, with its carryover-adjusted interval. It compares days with no time at the place against days with 2 or more hours there.
8. **Surface:** a "Places" card on the Recovery page. A place reads "collecting" until it has at least 8 visits over at least 3 weeks; after that its effects are shown.
9. **Security fix, shipped with this work:**
   - Behind `tailscale serve`, every request reaches the API from 127.0.0.1, so the loopback exemption in `require_admin_key` waived the key for any proxied request.
   - Now a proxied request skips the key only if it carries `Tailscale-User-Login`, the tailnet identity header.
   - The frontend build carries no key, so requiring one from every tailnet user would 401 the phone.

## Consequences
- **Easier:** any future "where was I" question reuses the stays and places.
- **Harder:** the host now holds a 90-day location trail; it is as sensitive as anything in the DB.
- **Watch for:**
  - Stays split by GPS drift. Points that are inaccurate or jumpy can turn one place into two that sit close together; merge them if that shows up.
  - Days the stress sync failed: report coverage, never silently drop it.
  - Court and gym reading stressful when a session wasn't logged as a workout.

## Open questions
- Whether the private-API login on the host needs an MFA code; if so, Rob enters it once.
