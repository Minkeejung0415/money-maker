from __future__ import annotations

from pathlib import Path


def purge_prop_cache(cache_dir: Path) -> int:
    """Delete only *.pkl files in cache_dir and return the deleted count."""
    cache_dir.mkdir(parents=True, exist_ok=True)

    deleted = 0
    for path in sorted(cache_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file() or path.suffix.lower() != ".pkl":
            continue
        try:
            path.unlink()
            deleted += 1
        except FileNotFoundError:
            # File was removed between list and delete; keep purge idempotent.
            continue
    return deleted
