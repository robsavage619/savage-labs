from __future__ import annotations

import pytest

from shc.ai.vault import (
    RELEVANT_DOMAINS,
    _classify_domain,
    _parse_frontmatter_domains,
)


def _frontmatter(**fields: str) -> str:
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    return f"---\n{body}\n---\n\n# Note\n\nBody.\n"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            _frontmatter(domains="[exercise-science, sleep-science]"),
            ["exercise-science", "sleep-science"],
        ),
        (_frontmatter(domains='["Sports-Business", marketing]'), ["sports-business", "marketing"]),
        ("---\ndomains:\n  - health\n  - governance\n---\n\nBody.\n", ["health", "governance"]),
        (_frontmatter(tags="[hypertrophy]"), []),
        ("no frontmatter at all", []),
    ],
)
def test_parse_frontmatter_domains(raw: str, expected: list[str]) -> None:
    assert _parse_frontmatter_domains(raw) == expected


def test_declared_health_domain_admits() -> None:
    assert _classify_domain("some-obscure-note", [], ["exercise-science"]) == "training"
    assert _classify_domain("some-obscure-note", [], ["sleep-science"]) == "sleep"


def test_declared_non_health_domain_beats_filename_keyword() -> None:
    """A declared out-of-scope note stays out even when its name says "training".

    ``huyen-2022-ch4-training-data.md`` is ML training data, not resistance
    training; the filename keyword table cannot tell the difference.
    """
    domain = _classify_domain(
        "huyen-2022-ch4-training-data", ["machine-learning"], ["ai-engineering"]
    )
    assert domain not in RELEVANT_DOMAINS


def test_mixed_domains_admit_on_the_health_member() -> None:
    domain = _classify_domain("some-note", [], ["ai-engineering", "exercise-science"])
    assert domain == "training"


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("resistance-training", "training"),
        ("muscle-hypertrophy", "training"),
        ("exercise-science", "training"),
        ("exercise-prescription", "training"),
        ("wearables", "hrv"),
        ("heart-rate", "hrv"),
        ("endurance-training", "hrv"),
    ],
)
def test_health_corpus_tags_admit(tag: str, expected: str) -> None:
    """The health corpus's dominant tags must classify without the filename table.

    These notes previously reached the planner only via the fail-open fallback;
    once admission became evidence-based they had to be classified on purpose.
    """
    assert _classify_domain("author-2024-some-paper", [tag], []) == expected


def test_no_positive_evidence_is_excluded() -> None:
    """Admission is evidence-based — the old fail-open put marketing in the planner."""
    domain = _classify_domain("ries-trout-2001-ch9-13-naming", ["brand-strategy"], [])
    assert domain not in RELEVANT_DOMAINS


def test_filename_keyword_still_classifies_untagged_notes() -> None:
    assert _classify_domain("schoenfeld-2016-rt-volume-hypertrophy", [], []) == "training"
    assert _classify_domain("epstein-2013-ch6-trainability-of-muscle", [], []) == "training"
