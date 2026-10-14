"""A small cache on disk, keyed by Instagram handle and post.

What it saves paying for twice:

  profiles   a profile row, with its latest 12 posts. Kept 24 hours: follower
             counts and new posts move, but a re-run the same day — or the
             audit run straight after competitor search — should not re-fetch.
  labels     what a post's image shows. Kept forever: the image never changes,
             so a weekly re-audit only labels the posts that are new.

Local files for now (`data/cache`). The functions are the whole interface, so
moving to Supabase later means rewriting this file and nothing else.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

ROOT = Path(os.getenv("CACHE_DIR", "data/cache"))
PROFILE_HOURS = 24


def _path(kind: str, key: str) -> Path:
    safe = "".join(c for c in key.lower() if c.isalnum() or c in "._-")
    return ROOT / kind / f"{safe}.json"


def _get(kind: str, key: str, max_age_h: Optional[float] = None):
    p = _path(kind, key)
    if not p.exists():
        return None
    if max_age_h is not None and time.time() - p.stat().st_mtime > max_age_h * 3600:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _put(kind: str, key: str, value) -> None:
    p = _path(kind, key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass        # a cache that cannot be written is just a slower run


def get_profile(handle: str) -> Optional[dict]:
    return _get("profiles", handle, PROFILE_HOURS)


def put_profile(handle: str, row: dict) -> None:
    _put("profiles", handle, row)


def get_label(post_key: str, model: str) -> Optional[dict]:
    got = _get("labels", post_key)
    return got if got and got.get("_model") == model else None


def put_label(post_key: str, model: str, label: dict) -> None:
    _put("labels", post_key, {**label, "_model": model})
