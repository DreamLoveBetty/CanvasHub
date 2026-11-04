"""Size budget for upstream's prompt-embedding cache, which never evicts. Entries can always be re-encoded."""
from __future__ import annotations

import os
from pathlib import Path

MAX_BYTES = 2 * 1024**3


def touch(cache, prompts, max_tokens):
    """Refresh hits so the budget evicts by last use. `_path` is pinned by the locked upstream version."""
    paths = [cache._path(prompt, max_tokens) for prompt in prompts]
    for path in paths:
        try:
            os.utime(path)
        except OSError:
            pass
    return paths


def evict(root, *, limit=MAX_BYTES, keep=()):
    """Delete oldest entries until the tree fits; entries of the current job stay. Returns removed count."""
    keep = {Path(path) for path in keep}
    entries = []
    for path in Path(root).rglob("*.safetensors"):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime_ns, stat.st_size, path))
    total = sum(size for _, size, _ in entries)
    removed = 0
    for _, size, path in sorted(entries, key=lambda item: item[0]):
        if total <= limit:
            break
        if path in keep:
            continue
        path.unlink(missing_ok=True)
        total -= size
        removed += 1
    return removed
