from __future__ import annotations

"""Vault research retrieval system for SHC workout planning.

The vault contains 400+ Obsidian notes covering training science, nutrition,
sleep, HRV, and adjacent topics. This module exposes three things to callers:

    vault_context(state, signals, keyword_hints, limit) → str
        Full retrieval: catalog of all relevant notes + detailed excerpts of
        the top-matched notes. Drop this string into the planner prompt.

    invalidate()
        Force the index to rebuild on the next call (call after vault syncs).

Internal design
───────────────
A VaultIndex is built once per server process (lazy, cached at module level).
Building reads every .md file, extracts metadata, and classifies each note
into a domain. Notes outside the "relevant" domains (ai/ml, economics, etc.)
are excluded from workout planning context.

Scoring for excerpt selection is multi-signal:
  • tag overlap with _TAG_SIGNALS (same as before, but now just one factor)
  • title keyword match against state/hint terms
  • body keyword match (first 1500 chars) against state/hint terms
  • exercise/movement name match (squat, bench, etc.) for session-specific notes
  • always-include flag for pinned foundational notes
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shc.config import settings

log = logging.getLogger(__name__)

# ── Domain classification ─────────────────────────────────────────────────────
# Notes are classified into broad domains by filename keywords.
# Only RELEVANT_DOMAINS appear in workout planning context.

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "training": [
        "hypertrophy", "strength", "periodiz", "volume", "exercise", "overload",
        "sra", "deload", "progressive", "mev", "mrv", "mav", "frequency",
        "intensity", "variation", "eccentric", "concentric", "rep-", "set-",
        "rpe", "rdl", "squat", "bench", "deadlift", "fatigue", "fitness-fatigue",
        "anatomical", "maximum-strength", "muscular", "neural", "neuromuscular",
        "fiber-type", "fiber-partitioning", "satellite", "mechanical-tension",
        "metabolic-stress", "muscle-damage", "effective-reps", "load-selection",
        "lifting-tempo", "tempo", "cluster-sets", "training-methods",
        "training-frequency", "training-intensity", "training-volume",
        "training-load", "training-adherence", "autoregulation", "velocity",
        "explosive", "phase-potentiation", "annual-plan", "microcycle",
        "concurrent", "interference", "cardio-hypertrophy", "resistance",
        "bompa", "helms-2018", "israetel-2020-ch1-specificity",
        "israetel-2020-ch2-overload", "israetel-2020-ch3-fatigue",
        "israetel-2020-ch4-sra", "israetel-2020-ch5-variation",
        "israetel-2020-ch6-phase", "israetel-2020-ch7-individualization",
        "israetel-2020-ch8-summary", "israetel-2020-scientific",
        "schoenfeld", "zatsiorsky", "range-of-motion", "biomechanics",
        "accommodating-resistance", "grip-strength", "compression-morbidity",
        "progression-by-training", "relative-vs-absolute", "sport-specific",
        "force-velocity", "hormonal-environment", "hormonal-response",
        "individualization-hypertrophy", "specificity", "overreaching",
        "cold-water-immersion", "volume-landmarks",
    ],
    "nutrition": [
        "protein", "calorie", "macro", "nutrient", "diet", "supplement",
        "creatine", "caffeine", "fat-loss", "recomposition", "fiber-intake",
        "peri-workout", "nutrition-protein", "nutritional-periodization",
        "helms-2016", "israetel-2020-ch1-diet", "israetel-2020-ch2-calorie",
        "israetel-2020-ch3-macro", "israetel-2020-ch4-nutrient",
        "israetel-2020-ch5-food", "israetel-2020-ch6-supplements",
        "israetel-2020-renaissance", "jager-2017", "rawson-2003", "guest-2021",
        "alcohol-and-performance", "calorie-deficit", "calorie-surplus",
        "flexible-dietary", "protein-target", "supplement-caffeine",
        "supplement-creatine",
    ],
    "sleep": [
        "sleep", "circadian", "rem", "sws", "insomnia", "biphasic",
        "walker-2017", "winter-2017", "dolezal-2017", "fatal-familial",
        "sleep-learning", "sleep-spindles", "sleep-state-misperception",
        "sleepy-vs-fatigued", "unihemispheric", "obstructive-sleep-apnea",
    ],
    "hrv": [
        "hrv", "heart-rate-variability", "resting-hr", "monitoring",
        "buchheit-2014", "chaitanya-2022", "dial-2025", "kiviniemi-2007",
        "malone-2017", "plews-2013", "plews-2014", "shaffer-2017",
        "task-force-1996", "bourdon-2017", "gabbett-2016", "wearable",
        "acwr", "training-load-classification", "zone-2", "cardio",
        "attia-2023-ch11", "attia-2023-ch12", "compression-of-morbidity",
        "grip-strength",
    ],
    "health": [
        "attia-2023", "apob", "apoe",
    ],
}

RELEVANT_DOMAINS = {"training", "nutrition", "sleep", "hrv", "health"}


def _classify_domain(stem: str) -> str:
    lower = stem.lower()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(k in lower for k in keywords):
            return domain
    return "other"


# ── Tag → signal mapping ──────────────────────────────────────────────────────
# Vault frontmatter tags that map to planning signals.

_TAG_SIGNALS: dict[str, tuple[str, ...]] = {
    # Recovery / load
    "hrv": ("hrv_anomaly",),
    "recovery": ("hrv_anomaly", "deload", "illness", "poor_sleep"),
    "overreaching": ("hrv_anomaly", "deload", "high_acwr"),
    "overtraining": ("deload", "high_acwr"),
    "acwr": ("high_acwr",),
    "load": ("high_acwr",),
    "deload": ("deload",),
    "illness": ("illness",),
    "sleep": ("poor_sleep",),
    # Strength / recomposition (always-on)
    "strength": ("default", "recomposition"),
    "hypertrophy": ("default", "recomposition"),
    "progressive-overload": ("default", "recomposition"),
    "overload": ("default",),
    "frequency": ("default",),
    "fitness-fatigue": ("default",),
    "compound-training": ("default", "recomposition"),
    "hormonal-response": ("default", "recomposition"),
    "recomposition": ("default", "recomposition"),
    "fat-loss": ("recomposition",),
    "body-composition": ("recomposition",),
    "density": ("recomposition",),
    "supersets": ("recomposition", "default"),
    "metabolic": ("recomposition",),
    "bodybuilding": ("default", "recomposition"),
    "individualization": ("default",),
    "variation": ("default",),
    "phase-potentiation": ("default",),
    "sra": ("default",),
    # Rest intervals
    "rest-intervals": ("default",),
    "rest-interval": ("default",),
    "cluster-sets": ("default",),
    # SFR / fatigue
    "sfr": ("hrv_anomaly", "deload", "high_acwr"),
    "fatigue-management": ("hrv_anomaly", "deload", "high_acwr", "default"),
    # Push/pull imbalance
    "push-pull-balance": ("push_pull_imbalance",),
    "muscle-balance": ("push_pull_imbalance",),
    "corrective-exercise": ("push_pull_imbalance",),
    "posterior-chain": ("push_pull_imbalance",),
    "pull": ("push_pull_imbalance",),
    # Volume
    "volume": ("default", "volume_spike"),
    "volume-management": ("volume_spike",),
    "periodization": ("default", "volume_spike"),
    "deload-timing": ("volume_spike",),
    "fatigue-accumulation": ("volume_spike", "high_acwr"),
    "supercompensation": ("volume_spike",),
    # Exercise selection
    "strength-training": ("exercise_selection",),
    "resistance-training": ("exercise_selection",),
    "exercise-science": ("exercise_selection",),
    "programming": ("exercise_selection",),
    "biomechanics": ("exercise_selection",),
    "physiology": ("exercise_selection",),
    "muscle-hypertrophy": ("exercise_selection", "recomposition"),
    "exercise-physiology": ("exercise_selection",),
    "exercise-prescription": ("exercise_selection", "recomposition"),
    "exercise-selection": ("exercise_selection",),
    "exercise-variety": ("exercise_selection",),
    "fiber-partitioning": ("exercise_selection",),
    "weak-points": ("exercise_selection",),
    "specificity": ("exercise_selection",),
    "range-of-motion": ("exercise_selection",),
    "eccentric": ("exercise_selection",),
    # Pickleball / 4.5 → 5.0 climb — Rob's primary 2026 goal.
    # Concurrent training papers surface when sport volume is high so the LLM
    # frames lifting in terms of court-power transfer, not generic recomp.
    "concurrent-training":  ("concurrent_training", "pickleball_focus"),
    "interference-effect":  ("concurrent_training", "pickleball_focus"),
    "power-development":    ("concurrent_training", "pickleball_focus", "default"),
    "maximal-strength":     ("concurrent_training", "default"),
    "polarized-training":   ("pickleball_focus", "default"),
    "respiratory-rate":     ("illness",),
    "athlete-sleep":        ("poor_sleep", "default"),
}

# Notes always included in the detailed excerpts, regardless of score.
# These are the scientific foundations for exercise selection and load prescription.
_ALWAYS_INCLUDE = {
    "exercise-selection-strength.md",
    "exercise-selection-hypertrophy.md",
    "exercise-order-strength.md",
    "schoenfeld-2010-hypertrophy-mechanisms.md",
    "rest-interval-hypertrophy.md",
    "rest-interval-strength.md",
    "age-related-hypertrophy.md",
    "variation-hypertrophy.md",
    "eccentric-training-hypertrophy.md",
    "range-of-motion-hypertrophy.md",
    "volume-landmarks-mev-mav-mrv.md",
    "israetel-2020-ch4-sra.md",
    "israetel-2020-ch3-fatigue-management.md",
    "periodization-hypertrophy.md",
    "progressive-overload-strength.md",
    "effective-reps-hypertrophy.md",
    "load-selection-hypertrophy.md",
}

# Sections to extract from note bodies.
_KEEP_HEADINGS = {
    "## Summary",
    "## Prescription",
    "## Practical Takeaways",
    "## Key Claims",
    "## Key Concepts",
    "## Evidence",
    "## Overtraining Continuum",
    "## Sequence of Impairments",
    "## Recovery Time by Muscle Group",
    "## Boundary Conditions",
    "## Exercise Selection Rules",
    "## Application to Training Variables",
    "## Specificity Checklist",
    "## Key Findings",
    "## Recommendations",
    "## Implications",
    "## Takeaways",
    "## Principles",
    "## Guidelines",
    "## Protocol",
}

# ── VaultNote ─────────────────────────────────────────────────────────────────

@dataclass
class VaultNote:
    filename: str
    title: str
    domain: str
    tags: list[str]
    summary: str        # first non-empty paragraph after frontmatter
    headings: list[str]
    body_excerpt: str   # first 1500 chars for keyword scoring
    excerpt: str        # formatted excerpt (sections or truncated body)


# ── VaultIndex ────────────────────────────────────────────────────────────────

class VaultIndex:
    """Scans and caches vault metadata. Built once per process."""

    def __init__(self, wiki_dir: Path) -> None:
        self.wiki_dir = wiki_dir
        self._notes: dict[str, VaultNote] = {}   # filename → note
        self._built = False

    def _build(self) -> None:
        count = 0
        for path in sorted(self.wiki_dir.glob("*.md")):
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as e:
                log.warning("Vault unreadable %s: %s", path, e)
                continue
            note = self._parse(path.name, raw)
            self._notes[path.name] = note
            count += 1
        self._built = True
        log.info("VaultIndex built: %d notes (%d relevant)",
                 count, sum(1 for n in self._notes.values() if n.domain in RELEVANT_DOMAINS))

    @staticmethod
    def _parse(filename: str, raw: str) -> VaultNote:
        tags = _parse_frontmatter_tags(raw)
        content = _strip_frontmatter(raw)
        domain = _classify_domain(Path(filename).stem)

        # Title: first `# ` heading in content, or humanised filename
        title = Path(filename).stem.replace("-", " ").title()
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Summary: first non-empty paragraph
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        summary = ""
        for p in paragraphs:
            if not p.startswith("#"):
                summary = p.replace("\n", " ")[:200]
                break

        # Headings
        headings = [l.strip() for l in content.split("\n") if re.match(r"^#{1,3} ", l)]

        body_excerpt = content[:1500]
        excerpt = _extract_sections(content) or content[:2000]

        return VaultNote(
            filename=filename,
            title=title,
            domain=domain,
            tags=tags,
            summary=summary,
            headings=headings,
            body_excerpt=body_excerpt,
            excerpt=excerpt,
        )

    def _ensure_built(self) -> None:
        if not self._built:
            self._build()

    def all_notes(self) -> list[VaultNote]:
        self._ensure_built()
        return list(self._notes.values())

    def relevant_notes(self) -> list[VaultNote]:
        return [n for n in self.all_notes() if n.domain in RELEVANT_DOMAINS]

    def get(self, filename: str) -> VaultNote | None:
        self._ensure_built()
        return self._notes.get(filename)

    def catalog_section(self) -> str:
        """Compact index of all relevant notes — one line each.

        Injected into every planner call so the AI knows what research exists.
        """
        notes = sorted(self.relevant_notes(), key=lambda n: (n.domain, n.title))
        if not notes:
            return ""
        lines = [f"## VAULT CATALOG ({len(notes)} research notes available)\n"]
        current_domain = ""
        for note in notes:
            if note.domain != current_domain:
                current_domain = note.domain
                lines.append(f"\n### {current_domain.upper()}")
            summary = f" — {note.summary}" if note.summary else ""
            lines.append(f"- **{note.title}** (`{note.filename}`){summary}")
        lines.append(
            "\nWhen generating the plan, cite specific vault notes by filename "
            "to show which research grounded each decision."
        )
        return "\n".join(lines)

    def query(
        self,
        signals: set[str],
        keyword_hints: list[str] | None = None,
        limit: int = 20,
    ) -> list[VaultNote]:
        """Return top `limit` notes ranked by relevance to signals + keywords."""
        hints = [h.lower() for h in (keyword_hints or [])]
        scored: list[tuple[float, VaultNote]] = []

        for note in self.relevant_notes():
            if note.filename in _ALWAYS_INCLUDE:
                # Guaranteed slot — score high enough to always be chosen
                scored.append((1000.0, note))
                continue

            score = 0.0

            # Tag-signal overlap (same logic as before)
            for tag in note.tags:
                for sig in _TAG_SIGNALS.get(tag, ()):
                    if sig in signals:
                        score += 2 if sig != "default" else 1

            # Filename/stem keyword match against signals
            stem = note.filename.lower().replace(".md", "").replace("-", " ")
            for sig in signals:
                if sig != "default" and sig.replace("_", " ") in stem:
                    score += 1

            # Title keyword match against hints
            title_lower = note.title.lower()
            for hint in hints:
                if hint in title_lower or hint in stem:
                    score += 3

            # Body keyword match against hints
            body_lower = note.body_excerpt.lower()
            for hint in hints:
                if hint in body_lower:
                    score += 1

            # Heading match against hints
            for heading in note.headings:
                h_lower = heading.lower()
                for hint in hints:
                    if hint in h_lower:
                        score += 0.5

            if score > 0:
                scored.append((score, note))

        scored.sort(key=lambda x: -x[0])
        # Deduplicate (always-include notes may appear with score 1000 only)
        seen: set[str] = set()
        result: list[VaultNote] = []
        for _, note in scored:
            if note.filename not in seen:
                seen.add(note.filename)
                result.append(note)
            if len(result) >= limit:
                break
        return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        return parts[2].strip() if len(parts) >= 3 else text
    return text


def _parse_frontmatter_tags(raw: str) -> list[str]:
    if not raw.startswith("---"):
        return []
    end = raw.find("---", 3)
    if end == -1:
        return []
    fm = raw[3:end]
    tags: list[str] = []
    inline = re.search(r"^tags:\s*\[([^\]]*)\]", fm, re.MULTILINE)
    if inline:
        tags.extend(t.strip().strip('"\'') for t in inline.group(1).split(","))
    block = re.search(r"^tags:\s*\n((?:\s*-\s*\S+.*\n?)+)", fm, re.MULTILINE)
    if block:
        for line in block.group(1).splitlines():
            t = line.strip().lstrip("-").strip().strip('"\'')
            if t:
                tags.append(t)
    return [t.lower() for t in tags if t]


def _extract_sections(text: str) -> str:
    """Keep whitelisted heading sections; fall back to first paragraph of each section."""
    lines = text.split("\n")
    output: list[str] = []
    capturing = False
    in_any_section = False

    for line in lines:
        stripped = line.strip()
        is_h2 = stripped.startswith("## ") or stripped.startswith("# ")
        if is_h2:
            whitelisted = any(h in stripped for h in _KEEP_HEADINGS)
            if whitelisted:
                capturing = True
                output.append(line)
                continue
            elif in_any_section and not whitelisted:
                # Non-whitelisted h2 starts — stop capture
                capturing = False
            in_any_section = True
        if capturing:
            output.append(line)

    return "\n".join(output).strip()


# ── Module-level singleton ────────────────────────────────────────────────────

_index: VaultIndex | None = None
_index_lock = threading.Lock()


def _get_index() -> VaultIndex | None:
    global _index
    if _index is not None:
        return _index
    with _index_lock:
        if _index is not None:
            return _index
        wiki_dir = settings.vault_path / "wiki"
        if not wiki_dir.exists():
            log.warning("Vault wiki dir not found at %s — vault context disabled", wiki_dir)
            return None
        _index = VaultIndex(wiki_dir)
    return _index


def invalidate() -> None:
    """Force the index to rebuild on the next call."""
    global _index
    with _index_lock:
        _index = None


# ── State signals ─────────────────────────────────────────────────────────────

def state_signals(
    state: dict[str, Any] | None,
    extra: set[str] | None = None,
) -> set[str]:
    """Derive vault-relevance signals from DailyState dict."""
    signals: set[str] = {"default", "recomposition", "exercise_selection"}
    if state is None:
        return signals | (extra or set())
    rec = state.get("recovery") or {}
    load = state.get("training_load") or {}
    chk = state.get("checkin") or {}
    gates = state.get("gates") or {}
    sleep = state.get("sleep") or {}
    if (rec.get("hrv_sigma") or 0) < -1.0:
        signals.add("hrv_anomaly")
    if (load.get("acwr") or 0) > 1.3:
        signals.add("high_acwr")
    if gates.get("deload_required"):
        signals.add("deload")
    if chk.get("illness_flag"):
        signals.add("illness")
    if (sleep.get("last_hours") or 8) < 6:
        signals.add("poor_sleep")

    # Pickleball / concurrent-training signals — Rob's 2026 goal is climbing
    # 4.5 → 5.0 while preserving strength + size. When weekly pickleball
    # volume is high, surface concurrent-training research so the planner
    # frames lifting as court-power transfer, not generic recomp.
    pickleball_min_7d = _pickleball_minutes_last_7d(load)
    if pickleball_min_7d >= 60:
        # Any meaningful pickleball week → pull pickleball-relevant research.
        signals.add("pickleball_focus")
    if pickleball_min_7d >= 150:
        # Heavy sport volume — interference-effect research is now load-bearing.
        signals.add("concurrent_training")

    # Respiratory-rate sentinel signal (Bourdillon / Nicolò early-warning).
    if (rec.get("respiratory_rate_delta") or 0) >= 1.0:
        signals.add("illness")

    if extra:
        signals |= extra
    return signals


def _pickleball_minutes_last_7d(load: dict[str, Any]) -> int:
    """Read pickleball_min_7d directly from training_load."""
    return int(load.get("pickleball_min_7d") or 0)


# ── Public entry point ────────────────────────────────────────────────────────

def vault_context(
    state: dict[str, Any] | None = None,
    extra_signals: set[str] | None = None,
    keyword_hints: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Build the full vault context block for injection into planner prompts.

    Returns two sections:
      1. VAULT CATALOG — compact index of all relevant notes (titles + summaries)
      2. VAULT EXCERPTS — full section extracts from the top-matched notes

    The catalog lets the AI know the full scope of available research.
    The excerpts give it the actual content to reason from.
    """
    idx = _get_index()
    if idx is None:
        return ""

    signals = state_signals(state, extra_signals)
    top_notes = idx.query(signals, keyword_hints=keyword_hints, limit=limit)

    catalog = idx.catalog_section()

    if not top_notes:
        return catalog

    sigs_str = ", ".join(sorted(signals - {"default", "recomposition", "exercise_selection"})) or "baseline"
    excerpt_header = (
        f"## VAULT EXCERPTS (top {len(top_notes)} notes for signals: {sigs_str})\n"
        "Full text of the most relevant notes. Cite these in your plan reasoning.\n"
    )
    excerpts = []
    for note in top_notes:
        always = " [ALWAYS LOADED]" if note.filename in _ALWAYS_INCLUDE else ""
        excerpt_body = note.excerpt or note.body_excerpt[:2000]
        excerpts.append(
            f"### {note.title} (`{note.filename}`){always}\n\n{excerpt_body}"
        )

    return catalog + "\n\n" + excerpt_header + "\n\n---\n\n".join(excerpts)
