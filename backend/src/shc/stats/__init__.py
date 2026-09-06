"""Read-only statistical helpers for the API and the engine.

Nothing in this package feeds a gate, threshold, band-fit, volume decision or
classifier — see ENGINE_INVARIANTS.md, "the rule for changing the engine".
These modules report; they do not decide.
"""

from __future__ import annotations

from shc.stats.correlation import correlate, fisher_ci, pearson
from shc.stats.noise_floor import NoiseVerdict, classify_change, swc

__all__ = [
    "NoiseVerdict",
    "classify_change",
    "correlate",
    "fisher_ci",
    "pearson",
    "swc",
]
