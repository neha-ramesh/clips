"""Posting habits, worked out from what the scan already holds. No calls.

Each of these is something the hand-written audits noticed by scrolling a grid:
"no location on any post", "doesn't use hashtags", "speaks in Tamil", "every
reel under 45 seconds", "five reels on the same day and then nothing", "add
highlights", "we need to add location to our page". All of it is in the post
and profile data; it only has to be counted.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from typing import Optional

from pydantic import BaseModel, Field

from .scan import Account, by_day, kind_of

# Unicode blocks for the scripts Indian accounts post in. Romanised Tamil or
# Kannada ("Ramanand branch ku") reads as English here — a known blind spot.
SCRIPTS = {
    "Tamil": (0x0B80, 0x0BFF), "Kannada": (0x0C80, 0x0CFF),
    "Telugu": (0x0C00, 0x0C7F), "Malayalam": (0x0D00, 0x0D7F),
    "Hindi/Marathi": (0x0900, 0x097F), "Bengali": (0x0980, 0x09FF),
    "Gujarati": (0x0A80, 0x0AFF), "Punjabi": (0x0A00, 0x0A7F),
}
LATIN = re.compile(r"[A-Za-z]")


def scripts_of(text: str) -> set[str]:
    found = set()
    for ch in text or "":
        o = ord(ch)
        for name, (lo, hi) in SCRIPTS.items():
            if lo <= o <= hi:
                found.add(name)
                break
    if LATIN.search(text or ""):
        found.add("English")
    return found


class Habits(BaseModel):
    handle: str
    posts: int = 0
    with_location: int = 0
    top_locations: list[str] = Field(default_factory=list)
    with_hashtags: int = 0
    tags_per_post: float = 0.0           # middle value, posts that use any
    languages: dict[str, int] = Field(default_factory=dict)   # script -> posts
    reels: int = 0
    reel_seconds: float = 0.0            # middle reel length
    reels_under_45s: int = 0
    busiest_day: str = ""
    busiest_day_posts: int = 0
    burst_days: int = 0                  # days with 3+ posts
    collabs: int = 0                     # co-authored or paid partnership posts
    # Profile checklist. None = unknown (the snapshot predates profiles).
    bio: str = ""
    has_link: Optional[bool] = None
    highlights: Optional[int] = None
    category: str = ""
    location_in_bio: Optional[bool] = None
    business_account: Optional[bool] = None


def habits_of(a: Account, place_words: list[str] = ()) -> Habits:
    """`place_words` — the city and areas — decide whether the bio says where."""
    posts = a.posts
    h = Habits(handle=a.handle, posts=len(posts))
    if not posts:
        return h

    locs = Counter(p.get("locationName") for p in posts if p.get("locationName"))
    h.with_location = sum(locs.values())
    h.top_locations = [name for name, _ in locs.most_common(3)]

    counts = [len(p.get("hashtags") or []) for p in posts]
    used = [c for c in counts if c]
    h.with_hashtags = len(used)
    h.tags_per_post = float(statistics.median(used)) if used else 0.0

    lang: Counter = Counter()
    for p in posts:
        for s in scripts_of(p.get("caption") or ""):
            lang[s] += 1
    h.languages = dict(lang.most_common())

    reels = [p for p in posts if kind_of(p) == "reel"]
    secs = [float(p["videoDuration"]) for p in reels if p.get("videoDuration")]
    h.reels = len(reels)
    if secs:
        h.reel_seconds = round(statistics.median(secs), 1)
        h.reels_under_45s = sum(1 for s in secs if s < 45)

    days = by_day(posts)
    if days:
        busiest = max(days, key=lambda d: len(days[d]))
        h.busiest_day, h.busiest_day_posts = busiest, len(days[busiest])
        h.burst_days = sum(1 for d in days.values() if len(d) >= 3)

    h.collabs = sum(1 for p in posts
                    if p.get("coauthorProducers") or p.get("paidPartnership"))

    prof = a.profile or {}
    if prof:
        h.bio = prof.get("biography") or ""
        h.has_link = bool(prof.get("externalUrl") or prof.get("externalUrls"))
        h.highlights = prof.get("highlightReelCount")
        h.category = prof.get("businessCategoryName") or ""
        h.business_account = prof.get("isBusinessAccount")
        words = [w.lower() for w in place_words if w and len(w) >= 3]
        if words:
            bio = h.bio.lower()
            h.location_in_bio = any(w in bio for w in words) or "📍" in h.bio
        else:
            h.location_in_bio = "📍" in h.bio or None
    return h


def checklist(h: Habits) -> list[tuple[str, Optional[bool], str]]:
    """(item, ok?, detail) for the client's profile. None = could not tell."""
    out = []
    if h.location_in_bio is not None:
        out.append(("Location in the bio", h.location_in_bio,
                    "says where you are" if h.location_in_bio else
                    "the bio does not say where to find you"))
    if h.highlights is not None:
        n = int(h.highlights or 0)
        out.append(("Story highlights", n >= 4,
                    f"{n} highlight{'s' if n != 1 else ''}"))
    if h.has_link is not None:
        out.append(("Link in bio", h.has_link,
                    "present" if h.has_link else "none"))
    if h.business_account is not None:
        out.append(("Business account", bool(h.business_account),
                    h.category or ("yes" if h.business_account else "no")))
    if h.posts:
        out.append(("Location tags on posts", h.with_location >= h.posts / 2,
                    f"{h.with_location} of {h.posts} posts"))
        out.append(("Hashtags", h.with_hashtags >= h.posts / 2,
                    f"on {h.with_hashtags} of {h.posts} posts"))
    return out
