from __future__ import annotations

"""Vault search — grep Rob's Obsidian knowledge graph from the API."""

from fastapi import APIRouter, Query

from shc.ai.vault import search_notes
from shc.config import settings

router = APIRouter(tags=["vault"])


@router.get("/vault/search")
async def vault_search(
    q: str = Query(..., min_length=2, description="Search terms (space-separated)"),
    limit: int = Query(default=10, gt=0, le=50),
) -> list[dict]:
    """Full-text search across all Obsidian vault notes.

    Thin wrapper over :func:`shc.ai.vault.search_notes` — the same on-demand
    search the planner calls in-process to resolve a specific uncertainty.
    """
    return search_notes(q, limit=limit)


@router.get("/vault/notes")
async def vault_notes(subdir: str | None = None) -> list[dict]:
    """List vault notes, optionally filtered to a subdirectory."""
    vault_path = settings.vault_path
    if not vault_path.exists():
        return []

    base = vault_path / subdir if subdir else vault_path
    notes = []
    for md_file in sorted(base.rglob("*.md")):
        relative = md_file.relative_to(vault_path)
        notes.append(
            {
                "path": str(relative),
                "name": md_file.stem,
                "size_bytes": md_file.stat().st_size,
            }
        )
    return notes
