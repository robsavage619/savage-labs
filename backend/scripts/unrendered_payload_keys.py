#!/usr/bin/env python
"""Find values the API computes that no frontend file ever mentions.

The most common defect found in this codebase during the 2026-09-06 audit was
not a broken metric — it was a *correct* metric nobody could see. FIB-4 had an
implementation, a route, a typed payload and a test suite, and had never once
rendered. `rem_pct_last` is computed every request and appears nowhere. Three
tiles on the research panel were dead for their whole lives because a swallowed
exception rendered as an em-dash rather than an error.

Run this against a live dev API:

    backend/.venv/bin/python backend/scripts/unrendered_payload_keys.py

Read the output as a LEAD, not a verdict. It has known blind spots in both
directions and neither is worth "fixing" by making the script cleverer:

  * FALSE POSITIVES — dynamic map keys. `allostatic_load.input_dates.trig` is
    rendered, via `Object.entries(...)`, but the literal string "trig" never
    appears in the source. Any payload the UI iterates rather than destructures
    will show up here.
  * FALSE NEGATIVES — generic key names. A leaf called `value`, `delta` or
    `unit` will match some unrelated line somewhere in the frontend and look
    consumed even when it is not.

So: treat a hit as "go look at the consumer", and confirm by reading the
component. That confirmation step is the whole job — a grep proved FIB-4 was
"referenced" when the only reference was its own type declaration.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
ENDPOINTS = (
    "/api/clinical/risk",
    "/api/state/today",
    "/api/clinical-research/insights",
    "/api/signals/noise-floor",
)
# .ts as well as .tsx: `lib/api.ts` holds the response types, and a key that
# appears ONLY there is typed but not displayed — exactly the FIB-4 case.
_FIND = (
    "find frontend/components frontend/app frontend/lib "
    r"\( -name '*.tsx' -o -name '*.ts' \) -not -path '*/node_modules/*'"
)


def _frontend_source() -> str:
    paths = subprocess.run(["bash", "-c", _FIND], capture_output=True, text=True).stdout.split()
    return "\n".join(open(p, encoding="utf-8", errors="ignore").read() for p in paths)


def _leaves(obj: object, path: str = "") -> dict[str, str]:
    """Map dotted path -> leaf key name, descending the first element of lists."""
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                out.update(_leaves(v, p))
            else:
                out[p] = k
    elif isinstance(obj, list) and obj:
        out.update(_leaves(obj[0], path + "[]"))
    return out


def main() -> int:
    src = _frontend_source()
    total = missing = 0
    for ep in ENDPOINTS:
        try:
            payload = json.loads(urllib.request.urlopen(BASE + ep, timeout=30).read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  {ep}: {exc}")
            continue
        leaves = _leaves(payload)
        total += len(leaves)
        gone = sorted(
            {p for p, k in leaves.items() if len(k) > 3 and not re.search(rf"\b{re.escape(k)}\b", src)}
        )
        missing += len(gone)
        print(f"\n{ep}  ({len(leaves)} leaves, {len(gone)} with no frontend reference)")
        for g in gone:
            print(f"    {g}")
    print(f"\nTOTAL: {missing}/{total} payload leaves have no frontend reference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
