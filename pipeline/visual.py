"""What is actually in each post, read from its image.

WHY THIS EXISTS

Every finding in the hand-written audits that clients remembered came from
looking at the posts, not their captions: "a post showing only the product gets
15 likes; the reel of a person in the showroom explaining it got 600+", "the
consultation-camp flyers get 5-7 likes; the one reel with a real kid dancing got
51", "same face, same outfit, every reel". Captions cannot see any of it. So the
cover image of every post goes to Claude with its numbers, one call per account,
and comes back labelled.

The labels are a fixed set so they can be counted. `typical likes by format`
is then plain arithmetic — the model never sees, and so cannot bend, the totals.

LIMITS

A reel is judged by its cover frame. "Made from a still graphic" is an inference
from a designed, text-heavy cover; a real video with a poster-style cover would
be miscounted. The report says "judging by the cover" wherever it uses this.
"""

from __future__ import annotations

import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from pydantic import BaseModel, Field

from .config import config
from .llm import complete_json
from .media import has_thumb, image_block, post_key
from .scan import Account, caption_of, kind_of, likes_of

MAX_POSTS = 24

FORMATS = {
    "people_talking": "A person talking or acting on camera",
    "people_wearing": "A model or person wearing / using it",
    "product_only": "The product on its own",
    "poster_graphic": "A designed poster, offer or text graphic",
    "festival_greeting": "A festival or greeting post",
    "behind_the_scenes": "The place, the team, the process",
    "other": "Something else",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "format": {"type": "string", "enum": list(FORMATS)},
                "real_person": {"type": "boolean"},
                "text_heavy": {"type": "boolean"},
                "ai_look": {"type": "boolean"},
                "describe": {"type": "string"},
            },
            "required": ["id", "format", "real_person", "text_heavy",
                         "ai_look", "describe"],
            "additionalProperties": False,
        }},
        "presenter": {"type": "string"},
        "style": {"type": "string"},
    },
    "required": ["posts", "presenter", "style"],
    "additionalProperties": False,
}

SYSTEM = """You label Instagram posts by what is visibly in them, so a
business can see which kinds of post earn attention. You get each post's cover
image with its kind, likes and caption.

For each post, by its id:
- format, exactly one:
  people_talking     a real person speaks, explains, acts or reacts on camera
                     (owner, staff, doctor, customer, actor in a skit)
  people_wearing     a model or person wears, holds or uses the product
                     without addressing the camera
  product_only       the product or service object alone, no person
  poster_graphic     a designed graphic: offer, flyer, info card, quote,
                     price list, mostly text and shapes
  festival_greeting  a greeting for a festival or day (Diwali, Doctors' Day)
  behind_the_scenes  the premises, the team, the making or the process,
                     without a sales pitch
  other              none of these
- real_person: true if a real human (not an illustration or AI render) is
  clearly visible.
- text_heavy: true if text covers a large part of the image.
- ai_look: true only if the image clearly looks AI-generated or a 3D render
  (waxy skin, impossible detail, illustrated people). When unsure, false.
- describe: at most 12 plain words - what a scroller sees.

Then for the account:
- presenter: if the same person appears as the face of several posts, say who
  they seem to be in a few words ("the same woman doctor in a clinic, in 9 of
  14 reels"); otherwise "".
- style: one line on the look of the feed overall.

Judge only what is visible. A reel is judged by its cover frame."""


class PostTag(BaseModel):
    format: str = "other"
    real_person: bool = False
    text_heavy: bool = False
    ai_look: bool = False
    describe: str = ""


class AccountLook(BaseModel):
    handle: str
    posts: dict[str, PostTag] = Field(default_factory=dict)   # post_key -> tag
    presenter: str = ""
    style: str = ""
    skipped: str = ""      # why nothing was labelled, when nothing was


def _choose(a: Account, out_dir) -> list[dict]:
    """Up to MAX_POSTS with an image: the best, the worst, then the newest.

    The extremes carry the finding; the newest show what they do now.
    """
    have = [p for p in a.posts if has_thumb(out_dir, p)]
    if len(have) <= MAX_POSTS:
        return have
    by_likes = sorted(have, key=lambda p: -int(p.get("likesCount") or 0))
    pick = by_likes[:8] + by_likes[-6:]
    for p in sorted(have, key=lambda p: p.get("timestamp") or "", reverse=True):
        if len(pick) >= MAX_POSTS:
            break
        if p not in pick:
            pick.append(p)
    return pick


def look_at(a: Account, out_dir) -> AccountLook:
    """Labels for the account's posts. Posts labelled before are not re-sent:
    a post's image never changes, so a weekly re-audit pays only for new ones."""
    from . import cache

    model = config.vision_model
    posts = _choose(a, out_dir)
    if not posts:
        return AccountLook(handle=a.handle,
                           skipped="no post images were saved for this account")
    look = AccountLook(handle=a.handle)
    fresh = []
    for p in posts:
        got = cache.get_label(post_key(p), model)
        if got:
            look.posts[post_key(p)] = PostTag(**{k: v for k, v in got.items()
                                                 if not k.startswith("_")})
        else:
            fresh.append(p)
    summary = cache.get_label(f"account_{a.handle}", model) or {}
    look.presenter, look.style = summary.get("presenter", ""), summary.get("style", "")
    if not fresh:
        return look

    blocks: list[dict] = [{"type": "text", "text": (
        f"Account @{a.handle}, {a.followers:,} followers. "
        f"{len(fresh)} posts follow, each as a label line then its image.")}]
    for p in fresh:
        likes = int(p.get("likesCount") or 0)
        secs = p.get("videoDuration")
        kind = kind_of(p) + (f" {float(secs):.0f}s" if secs else "")
        blocks.append({"type": "text", "text": (
            f"[{post_key(p)}] {kind} · "
            f"{'likes hidden' if likes < 0 else f'{likes:,} likes'} · "
            f"{int(p.get('commentsCount') or 0):,} comments · "
            f'caption: "{caption_of(p)[:140]}"')})
        img = image_block(out_dir, p)
        if img:
            blocks.append(img)

    got = complete_json(SYSTEM, blocks, schema=SCHEMA, list_key="posts",
                        required_field="format", model=model, temperature=1.0,
                        effort="medium")
    # A recurring face is judged on the posts sent; keep an earlier finding
    # when this batch was too small to show one.
    look.presenter = got.get("presenter") or look.presenter
    look.style = got.get("style") or look.style
    cache.put_label(f"account_{a.handle}", model,
                    {"presenter": look.presenter, "style": look.style})
    wanted = {post_key(p) for p in fresh}
    for row in got.get("posts", []):
        pid = str(row.get("id", "")).strip("[]")
        if pid in wanted:
            fmt = row.get("format") if row.get("format") in FORMATS else "other"
            tag = PostTag(format=fmt, real_person=bool(row.get("real_person")),
                          text_heavy=bool(row.get("text_heavy")),
                          ai_look=bool(row.get("ai_look")),
                          describe=str(row.get("describe") or "")[:120])
            look.posts[pid] = tag
            cache.put_label(pid, model, tag.model_dump())
    return look


def look_at_all(accounts: list[Account], out_dir,
                progress: Callable[[str], None] = print) -> dict[str, AccountLook]:
    live = [a for a in accounts if not a.error and a.posts]

    def one(a: Account) -> AccountLook:
        try:
            return look_at(a, out_dir)
        except Exception as e:
            return AccountLook(handle=a.handle, skipped=f"failed: {str(e)[:160]}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        looks = list(pool.map(one, live))
    done = sum(1 for lk in looks if lk.posts)
    progress(f"Looked at the posts of {done} of {len(live)} accounts.")
    return {lk.handle.lower(): lk for lk in looks}


# --------------------------------------------------------------------------- #
# Arithmetic on the labels
# --------------------------------------------------------------------------- #

class FormatRow(BaseModel):
    format: str
    posts: int
    typical_likes: float
    best_likes: int


def by_format(a: Account, look: AccountLook) -> list[FormatRow]:
    """Typical likes per format, for this account's labelled posts."""
    groups: dict[str, list[dict]] = {}
    for p in a.posts:
        tag = look.posts.get(post_key(p))
        if tag:
            groups.setdefault(tag.format, []).append(p)
    rows = []
    for fmt, ps in groups.items():
        lk = likes_of(ps)
        rows.append(FormatRow(format=fmt, posts=len(ps),
                              typical_likes=float(statistics.median(lk)) if lk else 0.0,
                              best_likes=max(lk) if lk else 0))
    rows.sort(key=lambda r: -r.typical_likes)
    return rows


def graphic_reels(a: Account, look: AccountLook) -> int:
    """Reels whose cover is a designed graphic or a product shot: likely a
    still image set to music, which Instagram shows to few people."""
    n = 0
    for p in a.posts:
        tag = look.posts.get(post_key(p))
        if (tag and kind_of(p) == "reel" and not tag.real_person
                and tag.format in ("poster_graphic", "festival_greeting", "product_only")):
            n += 1
    return n


def counts(look: AccountLook) -> dict[str, int]:
    c: dict[str, int] = {}
    for t in look.posts.values():
        c[t.format] = c.get(t.format, 0) + 1
    c["_real_person"] = sum(1 for t in look.posts.values() if t.real_person)
    c["_ai_look"] = sum(1 for t in look.posts.values() if t.ai_look)
    c["_labelled"] = len(look.posts)
    return c
