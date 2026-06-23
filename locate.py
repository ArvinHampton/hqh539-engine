"""Portable path resolution for HQH-539 module locations."""
from __future__ import annotations

import os
from pathlib import Path


def _search_roots(anchor: Path) -> list[Path]:
    anchor = anchor.resolve()
    return [anchor, *anchor.parents]


def canonical_hqh539_path(anchor: Path) -> Path:
    """Walk parents from anchor until 539_Engine/hqh539.py is found."""
    for parent in _search_roots(anchor):
        for candidate in (
            parent / "539_Engine" / "hqh539.py",
            parent / "Desktop" / "539_Engine" / "hqh539.py",
        ):
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(f"539_Engine/hqh539.py not found above {anchor}")


def sibling_module(anchor: Path, *parts: str) -> Path:
    """Resolve a module path sharing the Desktop parent of 539_Engine."""
    canonical = canonical_hqh539_path(anchor)
    desktop_dir = canonical.parent.parent
    path = desktop_dir.joinpath(*parts)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def downloads_hqh539_path(anchor: Path) -> Path:
    """Resolve Downloads/hqh539.py; optional HQH539_DOWNLOADS override."""
    override = os.environ.get("HQH539_DOWNLOADS")
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise FileNotFoundError(override)
    for parent in _search_roots(anchor):
        candidate = parent / "Downloads" / "hqh539.py"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Downloads/hqh539.py not found above {anchor}")