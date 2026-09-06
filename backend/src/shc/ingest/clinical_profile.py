"""Load Rob's clinical profile (conditions, meds, labs, vitals) from a YAML file.

The YAML lives at ``backend/data/clinical_profile.yml`` by default. Rerunning is
idempotent — rows are wiped and reinserted by source on every run so edits to
the YAML always win.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

SOURCE = "kaiser_summary"


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        return datetime.fromisoformat(v)
    return None


def _insert_lab(conn: Any, lid: str, lab: dict, ts: datetime | None, panel: str | None) -> None:
    value = lab.get("value")
    value_text = lab.get("value_text")
    is_abnormal = lab.get("is_abnormal")
    if is_abnormal is None and value is not None:
        rl, rh = lab.get("ref_low"), lab.get("ref_high")
        if (rl is not None and value < rl) or (rh is not None and value > rh):
            is_abnormal = True
    conn.execute(
        """
        INSERT INTO labs (id, loinc, name, value, value_text, unit, ref_low, ref_high,
                          ref_text, panel, is_abnormal, collected_at)
        VALUES ($id, $loinc, $name, $value, $vt, $unit, $rl, $rh, $rt, $panel, $abn, $ts)
        """,
        {
            "id": lid,
            "loinc": lab.get("loinc"),
            "name": lab["name"],
            "value": float(value) if value is not None else None,
            "vt": value_text,
            "unit": lab.get("unit"),
            "rl": lab.get("ref_low"),
            "rh": lab.get("ref_high"),
            "rt": lab.get("ref_text"),
            "panel": panel,
            "abn": is_abnormal,
            "ts": ts,
        },
    )


def _default_yaml_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "clinical_profile.yml"


def subject_dob(yaml_path: Path | None = None) -> date | None:
    """The subject's date of birth, read from the gitignored clinical profile.

    Deliberately NOT a source constant. This repo is public, and a full DOB is
    an identity credential in a way the age the engine prints everywhere is not
    — so it lives in `backend/data/clinical_profile.yml` (gitignored) beside the
    other clinical facts, under `patient.dob`.

    Returns None when the profile or the key is absent. Callers must decide what
    a missing DOB means; there is no fallback to today's age, because scoring a
    historical draw with today's age is the precise error an age-dependent index
    must not make silently.
    """
    path = yaml_path or _default_yaml_path()
    try:
        raw = (yaml.safe_load(path.read_text()) or {}).get("patient", {}).get("dob")
    except (OSError, yaml.YAMLError) as exc:
        log.warning("clinical profile unreadable at %s: %s", path, exc)
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            log.warning("patient.dob is not an ISO date: %r", raw)
    return None


def ingest_clinical_profile(yaml_path: Path | None = None) -> dict[str, int]:
    """Wipe + reload conditions, medications, labs, and vitals from YAML."""
    from shc.db.schema import get_read_conn

    if yaml_path is None:
        yaml_path = _default_yaml_path()

    if not yaml_path.exists():
        raise FileNotFoundError(f"Clinical profile YAML not found at {yaml_path}")

    log.info("Loading clinical profile from %s", yaml_path)
    data = yaml.safe_load(yaml_path.read_text())

    conn = get_read_conn()

    # Wipe prior YAML rows AND API-bootstrap test rows (UUID-shaped IDs from
    # the /api/clinical/medication endpoint that was used to seed bare-bones
    # data before this YAML existed). Migration-seeded rows like 'obs-*' are
    # preserved.
    UUID_LIKE = "________-____-____-____-____________"

    # Conditions
    conn.execute("DELETE FROM conditions WHERE id LIKE $p", {"p": f"{SOURCE}:%"})
    conn.execute("DELETE FROM conditions WHERE id LIKE $p", {"p": UUID_LIKE})
    n_cond = 0
    for c in data.get("conditions", []) or []:
        cid = f"{SOURCE}:cond:{_hash(c['name'], str(c.get('onset', '')))}"
        valid_to = _parse_ts(c.get("resolved")) if c.get("status") == "resolved" else None
        conn.execute(
            """
            INSERT INTO conditions (id, icd10, name, onset, status, valid_to)
            VALUES ($id, $icd10, $name, $onset, $status, $valid_to)
            """,
            {
                "id": cid,
                "icd10": c.get("icd10"),
                "name": c["name"],
                "onset": c.get("onset"),
                "status": c.get("status", "active"),
                "valid_to": valid_to,
            },
        )
        n_cond += 1

    # Medications
    conn.execute("DELETE FROM medications WHERE id LIKE $p", {"p": f"{SOURCE}:%"})
    conn.execute("DELETE FROM medications WHERE id LIKE $p", {"p": UUID_LIKE})
    n_med = 0
    for m in data.get("medications", []) or []:
        mid = f"{SOURCE}:med:{_hash(m['name'], str(m.get('started', '')))}"
        conn.execute(
            """
            INSERT INTO medications (id, rxnorm, name, dose, frequency, started, stopped)
            VALUES ($id, $rxnorm, $name, $dose, $frequency, $started, $stopped)
            """,
            {
                "id": mid,
                "rxnorm": m.get("rxnorm"),
                "name": m["name"],
                "dose": m.get("dose"),
                "frequency": m.get("frequency"),
                "started": m.get("started"),
                "stopped": m.get("stopped"),
            },
        )
        n_med += 1

    # Labs — note: labs.id is opaque; clear by source_doc_id pattern via id prefix
    conn.execute("DELETE FROM labs WHERE id LIKE $p", {"p": f"{SOURCE}:%"})
    n_lab = 0
    # Top-level `labs:` are unpaneled (legacy trended analytes).
    for lab in data.get("labs", []) or []:
        ts = _parse_ts(lab.get("collected_at"))
        lid = f"{SOURCE}:lab:{_hash(lab['name'], str(ts), str(lab.get('value')))}"
        _insert_lab(conn, lid, lab, ts, panel=None)
        n_lab += 1
    # `panels:` group qualitative + numeric results from a single order.
    for panel in data.get("panels", []) or []:
        panel_name = panel["name"]
        panel_ts = _parse_ts(panel.get("collected_at"))
        for lab in panel.get("results", []) or []:
            ts = _parse_ts(lab.get("collected_at")) or panel_ts
            lid = f"{SOURCE}:lab:{_hash(panel_name, lab['name'], str(ts), str(lab.get('value')), str(lab.get('value_text')))}"
            _insert_lab(conn, lid, lab, ts, panel=panel_name)
            n_lab += 1

    # Vitals → measurements table
    conn.execute("DELETE FROM measurements WHERE source = $s", {"s": SOURCE})
    n_vit = 0
    for v in data.get("vitals", []) or []:
        ts = _parse_ts(v["ts"])
        ext_id = f"{SOURCE}:{v['metric']}:{int(ts.timestamp()) if ts else 0}"
        ch = _hash(SOURCE, v["metric"], str(ts), str(v["value"]))
        conn.execute(
            """
            INSERT INTO measurements (source, metric, ts, value_num, unit, external_id, content_hash)
            VALUES ($s, $m, $ts, $val, $u, $eid, $ch)
            """,
            {
                "s": SOURCE,
                "m": v["metric"],
                "ts": ts,
                "val": float(v["value"]),
                "u": v.get("unit"),
                "eid": ext_id,
                "ch": ch,
            },
        )
        n_vit += 1

    conn.close()
    result = {"conditions": n_cond, "medications": n_med, "labs": n_lab, "vitals": n_vit}
    log.info("Clinical profile ingest complete: %s", result)
    return result
