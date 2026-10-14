"""Post images: fetched once at scan time, kept on disk, reused everywhere.

WHY AT SCAN TIME

Instagram's image links (`displayUrl`) are signed and expire within days. A
report rebuilt next week from a stored scan would have nothing to show and
nothing for the visual step to look at. So every post's cover image is saved
beside the snapshot the day it is scanned, as a small JPEG:

    <out_dir>/thumbs/<shortCode>.jpg

The download is a plain HTTP fetch from Instagram's CDN — nothing billed.
For reels and carousels it is the cover frame, which is what a scroller sees.
"""

from __future__ import annotations

import base64
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests

MAX_SIDE = 512          # enough for the visual step to read text on a flyer
QUALITY = 78

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def post_key(post: dict) -> str:
    return str(post.get("shortCode") or post.get("id") or "")


def thumb_path(out_dir, post: dict) -> Path:
    return Path(out_dir) / "thumbs" / f"{post_key(post)}.jpg"


def _shrink(raw: bytes) -> bytes:
    """Resize to MAX_SIDE and re-encode. Unchanged if Pillow is missing."""
    try:
        from PIL import Image
    except ImportError:
        return raw
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=QUALITY, optimize=True)
        return buf.getvalue()
    except Exception:
        return raw


def _fetch_one(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, timeout=20, headers=UA)
        if not r.ok or not r.content:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_shrink(r.content))
        return True
    except requests.RequestException:
        return False


def fetch_thumbs(accounts, out_dir, workers: int = 8) -> tuple[int, int]:
    """Save every in-window post's cover image. (saved now, unavailable).

    Already-saved images are skipped, so this is safe to call again.
    """
    todo = []
    for a in accounts:
        for p in a.posts:
            dest = thumb_path(out_dir, p)
            if post_key(p) and p.get("displayUrl") and not dest.exists():
                todo.append((p["displayUrl"], dest))
    if not todo:
        return 0, 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        got = list(pool.map(lambda t: _fetch_one(*t), todo))
    return sum(got), len(got) - sum(got)


def has_thumb(out_dir, post: dict) -> bool:
    return bool(out_dir) and post_key(post) != "" and thumb_path(out_dir, post).exists()


def _b64(out_dir, post: dict) -> Optional[str]:
    if not has_thumb(out_dir, post):
        return None
    return base64.b64encode(thumb_path(out_dir, post).read_bytes()).decode("ascii")


def data_uri(out_dir, post: dict) -> str:
    """For embedding in the report, so the HTML file stands on its own."""
    b = _b64(out_dir, post)
    return f"data:image/jpeg;base64,{b}" if b else ""


def image_block(out_dir, post: dict) -> Optional[dict]:
    """The image as a Claude content block, or None if it was never saved."""
    b = _b64(out_dir, post)
    if not b:
        return None
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
