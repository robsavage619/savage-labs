from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from shc.config import settings


@lru_cache(maxsize=1)
def load_personal_context() -> str:
    """Load personal health context from gitignored data/personal_context.md."""
    path: Path = settings.data_dir / "personal_context.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""
