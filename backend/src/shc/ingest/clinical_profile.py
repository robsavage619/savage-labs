"""Load Rob's clinical profile (conditions, meds, labs, vitals) from a YAML file.

The YAML lives at ``backend/data/clinical_profile.yml`` by default. Rerunning is
idempotent — rows are wiped and reinserted by source on every run so edits to
the YAML always win.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
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


def ingest_clinical_profile(yaml_path: Path | None = None) -> dict[str, int]:
    """Wipe + reload conditions, medications, labs, and vitals from YAML."""
    from shc.db.schema import get_read_conn

    if yaml_path is None:
        yaml_path = Path(__file__).resolve().parents[3] / "data" / "clinical_profile.yml"

    if not yaml_path.exists():
        raise FileNotFoundError(f"Clinical profile YAML not found at {yaml_path}")

    log.info("Loading clinical profile from %s", yaml_path)
    data = yaml.safe_load(yaml_path.read_text())

    conn = get_read_conn()

    # Conditions
    conn.execute("DELETE FROM conditions WHERE id LIKE $p", {"p": f"{SOURCE}:%"})
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
    for lab in data.get("labs", []) or []:
        ts = _parse_ts(lab.get("collected_at"))
        lid = f"{SOURCE}:lab:{_hash(lab['name'], str(ts), str(lab.get('value')))}"
        conn.execute(
            """
            INSERT INTO labs (id, loinc, name, value, unit, ref_low, ref_high, collected_at)
            VALUES ($id, $loinc, $name, $value, $unit, $rl, $rh, $ts)
            """,
            {
                "id": lid,
                "loinc": lab.get("loinc"),
                "name": lab["name"],
                "value": float(lab["value"]) if lab.get("value") is not None else None,
                "unit": lab.get("unit"),
                "rl": lab.get("ref_low"),
                "rh": lab.get("ref_high"),
                "ts": ts,
            },
        )
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
