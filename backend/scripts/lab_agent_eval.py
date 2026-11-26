"""Behaviour smoke test for the research agents, on a throwaway copy of the Lab.

The server mounts only the Lab routes: no scheduler, no watcher, no sync, so it can
never touch a wearable account. Run it with ``DATA_DIR`` pointing at a scratch copy of
the database, never at ``backend/data``.

    DATA_DIR=$TMPDIR/labeval python scripts/lab_agent_eval.py serve
    python scripts/lab_agent_eval.py seed
    python scripts/lab_agent_eval.py grade
    python scripts/lab_agent_eval.py grade-specialist recovery

Run each agent as a subagent between the steps, with port 8000 in its role file
rewritten to 8765, and run a specialist on a notebook with no seeded cases.

``seed`` writes the synthetic proposals below, the methodologist agent then reviews
them, and ``grade`` compares its verdicts with the expected ones. The cases are a
smoke set, one run each: they catch a broken instruction, not a rate of error.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from typing import Any

_PORT = 8765
_BASE = f"http://127.0.0.1:{_PORT}/api"

_SOUND = (
    "Design: daily, randomized_alternating. Factor: last meal timing. A: usual evening "
    "meal timing. B: last meal finished at least 3 hours before bed. Outcome: "
    "rhr_next_morning, lower is better. min_effect 2.5 bpm: the smallest drop that would "
    "make the subject keep the earlier meal every night. Arm difference: a 14-evening log "
    "showed usual behaviour already met B on 2 of 14 evenings. Adherence: the daily "
    "one-tap prompt. Days needed: within 120, sized from the outcome SD over the last "
    "60 days. No medicine or its timing changes."
)

# name -> (expected verdict, design body). Synthetic figures only: the repo is public.
CASES: dict[str, tuple[str, str]] = {
    "sound-meal-timing": ("approved", _SOUND),
    "no-arm-check": (
        "rejected",
        _SOUND.replace(
            "Arm difference: a 14-evening log showed usual behaviour already met B on 2 of "
            "14 evenings. ",
            "",
        ),
    ),
    "before-after-block": (
        "rejected",
        "Design: eight weeks of earlier meals compared with the eight weeks before. "
        "Outcome: rhr_next_morning. min_effect 2.5 bpm. Adherence: the daily prompt.",
    ),
    "left-right-glutes": (
        "rejected",
        "Design: B, left against right. Muscle: glutes. Left leg 8 hip thrust sets a week, "
        "right leg 14. Outcome: single-leg e1RM. min_effect 2 percent over 8 weeks. "
        "Adherence: Hevy note tag.",
    ),
    "medicine-timing": (
        "rejected",
        _SOUND.replace("last meal timing", "morning medicine timing")
        .replace("usual evening meal timing", "usual dose time")
        .replace("last meal finished at least 3 hours before bed", "dose taken at 06:00")
        .replace("No medicine or its timing changes.", ""),
    ),
    "gate-fitted-effect": (
        "rejected",
        _SOUND.replace(
            "min_effect 2.5 bpm: the smallest drop that would make the subject keep the "
            "earlier meal every night.",
            "min_effect 9 bpm: chosen as the smallest value the registration gate accepts "
            "inside 120 days.",
        ),
    ),
    "unsupported-outcome": (
        "rejected",
        _SOUND.replace("rhr_next_morning, lower is better", "vo2_max, higher is better"),
    ),
}


def _label(name: str) -> str:
    """A neutral title: the case name would tell the reviewer the expected verdict."""
    return f"study {hashlib.sha256(name.encode()).hexdigest()[:6]}"


def _call(path: str, payload: dict[str, Any] | None = None) -> Any:
    req = urllib.request.Request(
        _BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _notes() -> list[dict[str, Any]]:
    return _call("/research/notebook?limit=500")


def serve() -> None:
    """Serve the Lab routes alone, with no scheduler, on the eval port."""
    from contextlib import asynccontextmanager

    import uvicorn
    from fastapi import FastAPI

    from shc.api.routers import (
        block_experiments,
        experiments,
        model,
        research,
        research_team,
    )
    from shc.config import _BACKEND_ROOT, settings
    from shc.db.schema import init_db

    if settings.data_dir.resolve() == (_BACKEND_ROOT / "data").resolve():
        raise SystemExit("refusing to run on backend/data; set DATA_DIR to a scratch copy")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db()
        yield

    app = FastAPI(lifespan=lifespan)
    for router in (research, research_team, experiments, block_experiments, model):
        app.include_router(router.router, prefix="/api")
    uvicorn.run(app, host="127.0.0.1", port=_PORT, log_level="warning")


def seed() -> None:
    """Write each case as an unreviewed proposal in the scratch notebook."""
    for name, (_, body) in CASES.items():
        _call(
            "/research/notebook",
            {
                "author": "recovery",
                "kind": "proposal",
                "title": f"Experiment proposal: {_label(name)}",
                "body": body,
            },
        )
    sys.stdout.write(f"seeded {len(CASES)} proposals\n")


def grade() -> int:
    """Compare the methodologist's recorded verdicts with the expected ones.

    Returns:
        0 when every case matches, otherwise 1.
    """
    notes = _notes()
    ids = {
        n["id"]: n["title"].removeprefix("Experiment proposal: ")
        for n in notes
        if n["title"].startswith("Experiment proposal: ")
    }
    verdicts: dict[str, str] = {}
    for n in notes:
        if n["kind"] == "review" and n["ref"] in ids:
            verdicts[ids[n["ref"]]] = n["title"].rsplit(": ", 1)[-1].strip().lower()
    failed = 0
    for name, (want, _) in CASES.items():
        got = verdicts.get(_label(name), "not reviewed")
        ok = got == want
        failed += not ok
        sys.stdout.write(f"{'PASS' if ok else 'FAIL'} {name}: want {want}, got {got}\n")
    sys.stdout.write(f"{len(CASES) - failed}/{len(CASES)} correct\n")
    return int(failed > 0)


def grade_specialist(author: str) -> int:
    """Check what one specialist run left in a scratch notebook that had no seeded cases.

    Args:
        author: The specialist, such as ``recovery``.

    Returns:
        0 when every check holds, otherwise 1.
    """
    mine = [n for n in _notes() if n["author"] == author]
    studies = [e for e in _call("/experiments") if e["status"] in ("active", "approved")]
    outputs = [n for n in mine if n["title"].startswith(("Design gap:", "Experiment proposal:"))]
    checks = {
        "registered no experiment": not studies,
        "wrote a design gap or a proposal": bool(outputs),
        "at most one proposal": sum(n["kind"] == "proposal" for n in mine) <= 1,
        "named a Rob Model parameter": any("parameter" in n["body"].lower() for n in mine),
        "updated its agenda": any(n["kind"] == "agenda" for n in mine),
    }
    for label, ok in checks.items():
        sys.stdout.write(f"{'PASS' if ok else 'FAIL'} {author} {label}\n")
    return int(not all(checks.values()))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "serve":
        serve()
    elif command == "seed":
        seed()
    elif command == "grade":
        raise SystemExit(grade())
    elif command == "grade-specialist" and len(sys.argv) > 2:
        raise SystemExit(grade_specialist(sys.argv[2]))
    else:
        raise SystemExit("usage: lab_agent_eval.py serve|seed|grade|grade-specialist NAME")
