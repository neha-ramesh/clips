"""Fetch and measure public Instagram accounts.

This is `count_posts.py` as a module. Every function here was checked against
the real profile grids before being written down, which the code it replaces
never was — the old version reported 16 posts where the account showed 18, and
14 where it showed 21.

WHAT WENT WRONG BEFORE, SO IT DOES NOT AGAIN

  Two actors.        The profile scraper caps `latestPosts` at about a dozen no
                     matter what you ask for, so every account reported the same
                     post count. Only `apify/instagram-scraper` honours a limit.

  A sliding window.  The cutoff was "this moment minus 30 days", so a post near
                     the edge fell out between two runs an hour apart. It is now
                     anchored to midnight: every run on a given day agrees.

  Tangled functions. Counting posts and measuring likes were computed together,
                     so excluding posts with hidden like counts also removed
                     them from the post count. They are separate questions and
                     now separate functions.

WHAT IS STILL APPROXIMATE

Reels keep gaining likes after a read, and Instagram's API count drifts from the
number its app shows. Expect ±1 post and a few percent on likes between runs.
Fine for "their reels get about 600 and photos about 100"; not a figure to quote
to a client as exact.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

# Two actors, each for the one thing it does.
#
# instagram-scraper returns posts and honours a limit. It does NOT return
# follower counts: `addParentData` sounds like it should attach the owner's
# profile and does not — a scan came back with 0 followers on every account
# because of that assumption, which went unverified because the version that
# reported followers correctly still had the second call in it.
#
# instagram-profile-scraper returns the profile. Its post history is capped at
# about a dozen, which is why it is not used for posts — but one result per
# account for a follower count is cheap, roughly a fiftieth of what the posts
# cost.
POSTS_ACTOR = "apify/instagram-scraper"
PROFILE_ACTOR = "apify/instagram-profile-scraper"


class ScanError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

def _rows(client, actor: str, run_input: dict) -> list[dict]:
    """Run an actor, wait, hand back its dataset rows."""
    run = client.actor(actor).call(run_input=run_input)
    if run is None:
        return []
    ds = (run.get("defaultDatasetId") if isinstance(run, dict)
          else getattr(run, "default_dataset_id", None))
    if not ds:
        return []
    listed = client.dataset(ds).list_items()
    rows = listed.items if hasattr(listed, "items") else listed.get("items", [])
    return [r for r in rows if isinstance(r, dict)]


def get_posts(client, handle: str, limit: int) -> list[dict]:
    """Raw posts for one account, newest first. Exactly `limit` of them."""
    rows = _rows(client, POSTS_ACTOR, {
        "directUrls": [f"https://www.instagram.com/{handle}/"],
        "resultsType": "posts",
        "resultsLimit": limit,
    })
    posts = [r for r in rows if r.get("timestamp")]
    # Apify sometimes returns a few more than asked for, and each extra is billed.
    return posts[:limit]


def get_followers(client, handles: list[str]) -> dict[str, int]:
    """Follower counts for a set of accounts. One run, one result each."""
    return {h: int(p.get("followersCount") or 0)
            for h, p in get_profiles(client, handles).items()}


# The profile fields the report reads. The rest of a profile row is picture
# URLs and twelve embedded posts, which would only bloat every snapshot.
PROFILE_FIELDS = ("fullName", "biography", "externalUrl", "businessCategoryName",
                  "isBusinessAccount", "verified", "private", "highlightReelCount",
                  "postsCount", "followsCount", "followersCount", "facebookPage")


def slim_profile(row: dict) -> dict:
    out = {k: row.get(k) for k in PROFILE_FIELDS if row.get(k) is not None}
    links = []
    for u in row.get("externalUrls") or []:
        url = u.get("url") if isinstance(u, dict) else u
        if url:
            links.append(str(url))
    if links:
        out["externalUrls"] = links
    return out


def get_profiles(client, handles: list[str]) -> dict[str, dict]:
    """Slimmed profiles for a set of accounts. One run, one result each."""
    out: dict[str, dict] = {}
    for r in _rows(client, PROFILE_ACTOR,
                   {"usernames": handles, "resultsLimit": 1}):
        name = (r.get("username") or "").lower()
        if name and not r.get("error"):
            out[name] = slim_profile(r)
    return out


# --------------------------------------------------------------------------- #
# Measuring. No network, no shared state — each answers one question.
# --------------------------------------------------------------------------- #

def parse_time(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def window_start(days: int) -> datetime:
    """Midnight, `days` ago. Not "this moment minus `days`".

    An exact-timestamp cutoff slides through the day, so a post near the edge
    falls out between two runs an hour apart — a count went 21 then 20 for
    exactly that reason with nothing having changed on Instagram.
    """
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0)


def in_last_days(posts: list[dict], days: int) -> list[dict]:
    cutoff = window_start(days)
    out = []
    for p in posts:
        t = parse_time(p.get("timestamp", ""))
        if t and t >= cutoff:
            out.append(p)
    return out


def kind_of(post: dict) -> str:
    t = (post.get("type") or "").lower()
    return "reel" if t == "video" else "carousel" if t == "sidecar" else "photo"


def likes_of(posts: list[dict]) -> list[int]:
    """Like counts we can read.

    An account hiding its likes returns -1. Counting that as zero would drag the
    typical figure down, so it is excluded here — the post is still counted as a
    post by everything else.
    """
    return [int(p.get("likesCount") or 0) for p in posts
            if int(p.get("likesCount") or 0) >= 0]


def comments_of(posts: list[dict]) -> list[int]:
    return [int(p.get("commentsCount") or 0) for p in posts
            if int(p.get("likesCount") or 0) >= 0]


def typical(values: list[int]) -> float:
    """The middle value, not the average.

    Eight posts at 100 likes and two at 15,000 average to 3,080, which describes
    no post that exists. The middle value says 100.
    """
    if not values:
        return 0.0
    v = sorted(values)
    n = len(v)
    return float(v[n // 2]) if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def by_kind(posts: list[dict]) -> dict[str, float]:
    """Typical likes for each kind of post."""
    out: dict[str, float] = {}
    for label in ("reel", "carousel", "photo"):
        got = likes_of([p for p in posts if kind_of(p) == label])
        if got:
            out[label] = typical(got)
    return out


def kind_counts(posts: list[dict]) -> Counter:
    return Counter(kind_of(p) for p in posts)


def hidden_count(posts: list[dict]) -> int:
    return sum(1 for p in posts if int(p.get("likesCount") or 0) < 0)


def caption_of(post: dict) -> str:
    return " ".join((post.get("caption") or "").split())


def url_of(post: dict) -> str:
    return post.get("url") or post.get("permalink") or ""


# --------------------------------------------------------------------------- #
# Posting rhythm and time of day
#
# Lifted unchanged from check_timing.py, which was written specifically to be
# checkable by hand and then checked. Two things in it are easy to get wrong and
# were:
#
#   Gaps count EVERY post, including ones with hidden like counts. Dropping
#   those first merges the gaps either side into one false silence.
#
#   Time-of-day is measured against each account's OWN usual, never pooled.
#   Pooled, one big account posting at night made night look 200 times better
#   than any other hour — which reported when that account posts, not what hour
#   works.
# --------------------------------------------------------------------------- #

IST = timedelta(hours=5, minutes=30)

BANDS = [
    (5, 9, "early morning"),
    (9, 12, "late morning"),
    (12, 15, "afternoon"),
    (15, 19, "evening"),
    (19, 24, "night"),
    (0, 5, "small hours"),
]

# A band needs this many posts, from this many accounts, before it is allowed to
# claim anything.
MIN_POSTS = 5
MIN_ACCOUNTS = 2


def post_times(posts: list[dict]) -> list[datetime]:
    """Publish times, oldest first. Every post, hidden likes included."""
    times = [t for t in (parse_time(p.get("timestamp", "")) for p in posts) if t]
    times.sort()
    return times


def gaps_between(times: list[datetime]) -> list[float]:
    """Days from each post to the next."""
    return [(b - a).total_seconds() / 86400 for a, b in zip(times, times[1:])]


def ist_hour(t: datetime) -> int:
    return (t + IST).hour


def band_of(hour: int) -> str:
    for lo, hi, label in BANDS:
        if lo <= hour < hi:
            return label
    return "small hours"


class Rhythm(BaseModel):
    """How often one account posts, and its longest silence."""

    handle: str
    posts: int = 0
    usual_gap_days: float = 0.0
    longest_gap_days: float = 0.0
    longest_after: str = ""
    span_days: int = 0


def rhythm_of(account: "Account") -> Optional[Rhythm]:
    times = post_times(account.posts)
    if len(times) < 2:
        return None
    gaps = gaps_between(times)
    worst = max(gaps)
    return Rhythm(
        handle=account.handle,
        posts=len(times),
        usual_gap_days=statistics.median(gaps),
        longest_gap_days=worst,
        longest_after=(times[gaps.index(worst)] + IST).date().isoformat(),
        span_days=(times[-1] - times[0]).days,
    )


class Band(BaseModel):
    """One time-of-day band across every account."""

    label: str
    span: str
    posts: int = 0
    accounts: int = 0
    who: list[str] = Field(default_factory=list)
    typical_likes: float = 0.0
    vs_usual: float = 0.0
    trusted: bool = False


def timing_bands(accounts: list["Account"]) -> list[Band]:
    """Time-of-day performance, normalised per account."""
    rows: list[tuple[str, int, int]] = []      # handle, ist hour, likes
    for a in accounts:
        if a.error:
            continue
        for p in a.posts:
            t = parse_time(p.get("timestamp", ""))
            likes = int(p.get("likesCount") or 0)
            if t and likes >= 0:               # hidden likes cannot be averaged
                rows.append((a.handle, ist_hour(t), likes))
    if not rows:
        return []

    usual: dict[str, float] = {}
    for h in {r[0] for r in rows}:
        mine = [r[2] for r in rows if r[0] == h]
        usual[h] = statistics.median(mine) or 1

    out = []
    for lo, hi, label in BANDS:
        here = [r for r in rows if band_of(r[1]) == label]
        if not here:
            continue
        who = {r[0] for r in here}
        out.append(Band(
            label=label,
            span=f"{lo}\u2013{hi}",
            posts=len(here),
            accounts=len(who),
            who=sorted(who),
            typical_likes=statistics.median(r[2] for r in here),
            vs_usual=statistics.median(r[2] / usual[r[0]] for r in here),
            trusted=len(here) >= MIN_POSTS and len(who) >= MIN_ACCOUNTS,
        ))
    return out


# --------------------------------------------------------------------------- #
# Hashtags
#
# Three things make a tag useless to a client, and all three are computable.
#
#   It is somebody's brand.   #krishnabaran and #abarantimelessjewellery are
#                             Abaran's own. Nobody searches them, and a client
#                             using them is tagging a competitor.
#
#   It is an event.           #janmashtami was superb in early September and is
#                             worth nothing in November. A festival tag's posts
#                             cluster into a few days; an evergreen tag's are
#                             spread across the month. That spread is the test.
#
#   One account uses it.      A tag appearing on a single account's posts says
#                             what that account does, not what works.
# --------------------------------------------------------------------------- #

TAG_RE = re.compile(r"#(\w{2,40})")


class Tag(BaseModel):
    label: str
    posts: int = 0
    accounts: int = 0
    typical_likes: float = 0.0
    span_days: int = 0            # first to last use
    branded: bool = False         # belongs to one of the accounts
    seasonal: bool = False        # used within a few days, not across the month
    who: list[str] = Field(default_factory=list)


# Words that appear in half the handles in any given trade, and so cannot
# identify anybody. Stripped before looking for a brand stem, or #goldjewellery
# would count as belonging to @lalithaajewellery_.
_GENERIC = re.compile(
    r"jewell?er(?:y|s)?|jewels?|dental|clinic|dentist|official|store|shop|"
    r"bangalore|chennai|mumbai|delhi|india|[_.\-]"
)


def brand_name(handle: str) -> str:
    """The name at the front of a handle, before any trade word.

    Taken as the leading chunk rather than by deleting the trade words, because
    deletion leaves debris: @davanam_jewellers minus "jewel" is "davanamlers",
    which is not a tag anyone would build.

    @davanam_jewellers -> davanam
    @lumadentalcare    -> luma
    @b.b.jewellers     -> bb
    """
    parts = [p for p in _GENERIC.split(handle.lower()) if p]
    return parts[0] if parts else handle.lower()


def brand_stem(handle: str) -> str:
    """The first few letters of the distinctive part, for MATCHING only.

    @abarantimelessjewellery gives "abaran", which is what #krishnabaran and
    #celebratewithabaran share with it — matching on the whole handle finds
    neither. Six characters because it has to be short enough to appear inside
    a longer tag, which also makes it wrong for display: it would suggest
    #celebratewithdavana. Use brand_name for anything a reader sees.
    """
    h = brand_name(handle)
    return h[:6] if len(h) >= 6 else h


def _is_branded(tag: str, handles: list[str]) -> bool:
    """Does this tag carry an account's name?"""
    t = tag.lower()
    for h in handles:
        stem = brand_stem(h)
        if len(stem) >= 5 and stem in t:
            return True
    return False


def hashtags(accounts: list["Account"], min_posts: int = 1,
             evergreen_days: int = 10) -> list[Tag]:
    """Every tag used more than once, with what makes it usable or not."""
    live = [a for a in accounts if not a.error and a.posts]
    if not live:
        return []
    handles = [a.handle for a in live]

    seen: dict[str, list[tuple[str, int, datetime]]] = {}
    for a in live:
        for p in a.posts:
            likes = int(p.get("likesCount") or 0)
            t = parse_time(p.get("timestamp", ""))
            if likes < 0 or not t:
                continue
            for tag in {x.lower() for x in TAG_RE.findall(p.get("caption") or "")}:
                seen.setdefault(tag, []).append((a.handle, likes, t))

    out = []
    for tag, uses in seen.items():
        if len(uses) < min_posts:
            continue
        who = sorted({u[0] for u in uses})
        times = sorted(u[2] for u in uses)
        span = (times[-1] - times[0]).days
        out.append(Tag(
            label=tag,
            posts=len(uses),
            accounts=len(who),
            typical_likes=statistics.median(u[1] for u in uses),
            span_days=span,
            branded=_is_branded(tag, handles),
            # Used across only a few days — an event, not a standing tag. A
            # branded tag can also be bursty, and when it is, "belongs to them"
            # is the more useful label of the two.
            seasonal=span <= 3 and len(uses) >= 2 and not _is_branded(tag, handles),
            who=who,
        ))
    out.sort(key=lambda t: -t.typical_likes)
    return out


def by_day(posts: list[dict]) -> dict[str, list[dict]]:
    """Posts grouped by the date they went up."""
    out: dict[str, list[dict]] = {}
    for p in posts:
        t = parse_time(p.get("timestamp", ""))
        if t:
            out.setdefault(t.date().isoformat(), []).append(p)
    return out


# --------------------------------------------------------------------------- #
# One account's numbers, computed once
# --------------------------------------------------------------------------- #

class Account(BaseModel):
    """Everything the report needs about one account.

    Built by `measure`, which is the only place the functions above get called
    in combination. Keeping the arithmetic out of the report means a change to
    how something is displayed cannot alter what it says.
    """

    handle: str
    followers: int = 0
    days: int = 30
    fetched: int = 0
    posts: list[dict] = Field(default_factory=list)   # inside the window
    error: str = ""
    # Bio, link, highlights, category: see `slim_profile`. Empty for snapshots
    # taken before profiles were kept.
    profile: dict = Field(default_factory=dict)

    typical_likes: float = 0.0
    typical_comments: float = 0.0
    best_likes: int = 0
    likes_by_kind: dict[str, float] = Field(default_factory=dict)
    counts_by_kind: dict[str, int] = Field(default_factory=dict)
    hidden: int = 0
    oldest_fetched: str = ""
    read_at: str = ""
    truncated: bool = False

    @property
    def post_count(self) -> int:
        """Posts they made in the window, hidden like counts included."""
        return len(self.posts)

    @property
    def mix(self) -> dict[str, float]:
        """Share of the feed by kind, as a fraction."""
        n = self.post_count
        return {k: v / n for k, v in self.counts_by_kind.items()} if n else {}

    @property
    def best_kind(self) -> Optional[str]:
        if not self.likes_by_kind:
            return None
        return max(self.likes_by_kind, key=lambda k: self.likes_by_kind[k])


def measure(handle: str, raw: list[dict], days: int,
            followers: int = 0, limit: int = 0) -> Account:
    """Turn raw posts into the numbers the report needs."""
    window = in_last_days(raw, days)
    lk = likes_of(window)
    times = [t for t in (parse_time(p.get("timestamp", "")) for p in raw) if t]

    return Account(
        handle=handle,
        followers=followers,
        days=days,
        fetched=len(raw),
        posts=window,
        typical_likes=typical(lk),
        typical_comments=typical(comments_of(window)),
        best_likes=max(lk) if lk else 0,
        likes_by_kind=by_kind(window),
        counts_by_kind=dict(kind_counts(window)),
        hidden=hidden_count(window),
        oldest_fetched=min(times).date().isoformat() if times else "",
        read_at=datetime.now(timezone.utc).isoformat(),
        # Cut off only if BOTH are true: we returned as many as we asked for,
        # and every one of them is inside the window — so there are older posts
        # we never reached. Getting 6 back when you asked for 40 means the
        # account simply has 6, not that anything was missed.
        truncated=bool(limit and len(raw) >= limit
                       and times and min(times) >= window_start(days)),
    )


def scan(
    token: str,
    handles: list[str],
    *,
    days: int = 30,
    limit: int = 40,
    workers: int = 2,
    verbose: bool = True,
) -> list[Account]:
    """Fetch and measure a set of accounts.

    Cost is `len(handles) * limit` billed results. 40 covers 30 days for anyone
    posting under twice a day, and the account's own report says when it did not
    reach far enough.
    """
    try:
        from apify_client import ApifyClient
    except ImportError as e:
        raise ScanError("Run: pip install apify-client") from e
    if not token:
        raise ScanError("APIFY_TOKEN is not set")

    handles = [h.strip().lstrip("@") for h in handles if h.strip()]
    if not handles:
        return []

    client = ApifyClient(token)
    if verbose:
        billed = len(handles) * limit + len(handles)   # posts + one profile each
        print(f"  fetching {limit} posts each for {len(handles)} account(s) "
              f"— about {billed} billed results, ~${billed * 0.0023:.2f}")

    def one(h: str) -> tuple[str, list[dict], str]:
        try:
            return h, get_posts(client, h, limit), ""
        except Exception as e:
            msg = str(e)
            if "hard limit" in msg or "usage" in msg.lower():
                msg = ("Apify's monthly credit is spent. It resets on your "
                       "billing date; until then lower the limit.")
            return h, [], msg[:200]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        fetched = list(pool.map(one, handles))

    # Followers in a separate pass, after the posts. Mixing two actors into one
    # thread pool is what previously cost us data — three concurrent runs came
    # back with less than three sequential ones.
    profiles: dict[str, dict] = {}
    try:
        profiles = get_profiles(client, handles)
    except Exception as e:
        if verbose:
            print(f"    follower counts unavailable: {str(e)[:90]}")

    out = []
    for h, raw, err in fetched:
        if err:
            out.append(Account(handle=h, days=days, error=err))
            continue
        prof = profiles.get(h.lower(), {})
        a = measure(h, raw, days, int(prof.get("followersCount") or 0), limit)
        a.profile = prof
        out.append(a)

    if verbose:
        for a in out:
            if a.error:
                print(f"    {a.handle}: {a.error[:90]}")
            else:
                flag = " (limit reached — there are more)" if a.truncated else ""
                print(f"    {a.handle}: {a.followers:,} followers, "
                      f"{a.post_count} posts in {days} days{flag}")
    return out


def _needs_more(posts: list[dict], days: int) -> bool:
    """True when the profile's latest posts do not reach back to the window's
    start — the account posted more than the profile shows."""
    times = [parse_time(p.get("timestamp", "")) for p in posts if not p.get("isPinned")]
    times = [t for t in times if t]
    return bool(times) and len(times) >= 10 and min(times) >= window_start(days)


def scan_fast(
    token: str,
    handles: list[str],
    *,
    days: int = 30,
    limit: int = 40,
    profiles: Optional[dict[str, dict]] = None,
    comment_posts: int = 3,
    progress=print,
) -> list[Account]:
    """The scan, from profiles first. Same Account as `scan`, a fraction of
    the cost and time.

    A profile lookup ($0.0026) already carries the account's latest 12 posts
    with likes, comments, captions, images, hashtags and locations. For most
    accounts that covers the whole window, and competitor search has usually
    fetched the profile already — so the post scraper ($0.0027 a post, ~30 s an
    account) runs only for accounts that posted more than the profile shows,
    and only back to the window's start.

    Profiles carry no comment text and no reel length, so the `comment_posts`
    best posts of each account are fetched once more for those.
    """
    from concurrent.futures import ThreadPoolExecutor

    from .apify import run as apify_run
    from .competitors import _profiles

    handles = [h.strip().lstrip("@").lower() for h in handles if h.strip()]
    have = {h: p for h, p in (profiles or {}).items() if h in handles}
    missing = [h for h in handles if h not in have]
    if missing:
        progress(f"Looking up {len(missing)} profile(s)...")
        have.update(_profiles(token, missing))

    since = window_start(days).date().isoformat()
    heavy = [h for h in handles if h in have
             and _needs_more(have[h].get("latestPosts") or [], days)]

    def more(h: str) -> tuple[str, list[dict], str]:
        try:
            rows = apify_run(token, POSTS_ACTOR,
                             {"directUrls": [f"https://www.instagram.com/{h}/"],
                              "resultsType": "posts", "resultsLimit": limit,
                              "onlyPostsNewerThan": since},
                             cap_usd=round(limit * 0.003 + 0.02, 2))
            return h, [r for r in rows if r.get("timestamp")][:limit], ""
        except Exception as e:
            return h, [], str(e)[:200]

    extra: dict[str, list[dict]] = {}
    if heavy:
        progress(f"{len(heavy)} account(s) posted more than their profile shows; "
                 "fetching the rest of their month...")
        with ThreadPoolExecutor(max_workers=5) as pool:
            for h, rows, err in pool.map(more, heavy):
                if rows:
                    extra[h] = rows

    out: list[Account] = []
    for h in handles:
        prof = have.get(h)
        if not prof:
            out.append(Account(handle=h, days=days,
                               error="No profile came back. Check the handle, "
                                     "or the account may be private."))
            continue
        raw = extra.get(h) or [p for p in prof.get("latestPosts") or []
                               if p.get("timestamp")]
        a = measure(h, raw, days, int(prof.get("followersCount") or 0),
                    limit if h in extra else 0)
        a.profile = slim_profile(prof)
        out.append(a)

    # Comments and reel lengths for each account's best posts.
    want: dict[str, dict] = {}
    for a in out:
        top = sorted([p for p in a.posts if int(p.get("likesCount") or 0) >= 0],
                     key=lambda p: -int(p.get("likesCount") or 0))[:comment_posts]
        for p in top:
            if url_of(p) and not p.get("latestComments"):
                want[url_of(p).rstrip("/")] = p
    if want:
        progress(f"Reading the comments on {len(want)} top posts...")
        try:
            rows = apify_run(token, POSTS_ACTOR,
                             {"directUrls": list(want), "resultsType": "posts",
                              "resultsLimit": 1},
                             cap_usd=round(len(want) * 0.003 + 0.02, 2))
            for r in rows:
                p = want.get((r.get("url") or r.get("inputUrl") or "").rstrip("/"))
                if p is None:
                    continue
                for k in ("latestComments", "videoDuration", "videoPlayCount"):
                    if r.get(k) is not None:
                        p[k] = r[k]
        except Exception as e:
            progress(f"Comments could not be fetched: {str(e)[:120]}")
    return out


# --------------------------------------------------------------------------- #
# Snapshots
# --------------------------------------------------------------------------- #

def save_snapshot(accounts: list[Account], out_dir, client: str) -> Any:
    import json
    from pathlib import Path

    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"{client}_scan_{stamp}.json"
    path.write_text(
        json.dumps([a.model_dump() for a in accounts], indent=1,
                   ensure_ascii=False),
        encoding="utf-8")
    return path


class Growth(BaseModel):
    """One account's follower change between two scans."""

    handle: str
    was: int
    now: int
    change: int
    pct: float
    from_date: str
    to_date: str
    days: int
    meaningful: bool = True


def growth_between(out_dir, client: str, min_pct: float = 0.15) -> list[Growth]:
    """Follower change from the oldest stored scan to the newest.

    HOW THE HISTORY EXISTS AT ALL

    Instagram will not tell you what an account's follower count was last week.
    The only way to know is to have written it down, which is what every scan
    does: `{client}_scan_YYYYMMDD.json` holds the count at that moment. Growth
    is a diff between two of those files, so it exists only for weeks the scan
    actually ran, and skipping a week loses it permanently.

    One file per day — running twice in a day overwrites, which is what you
    want.

    WHY SMALL CHANGES ARE MARKED

    A count of 51,119 dropping to 51,115 is four followers, and Instagram's own
    number wobbles by more than that between refreshes. Reporting it as "-0.0%"
    invites a client to read a rounding artefact as a trend, so anything under
    `min_pct` is flagged rather than presented as movement.
    """
    snaps = load_snapshots(out_dir, client)
    if len(snaps) < 2:
        return []

    (d0, first), (d1, last) = snaps[0], snaps[-1]
    was = {a.handle.lower(): a.followers for a in first if a.followers}
    try:
        days = (datetime.strptime(d1, "%Y%m%d")
                - datetime.strptime(d0, "%Y%m%d")).days
    except ValueError:
        days = 0

    out = []
    for a in last:
        prev = was.get(a.handle.lower())
        if not prev or not a.followers:
            continue
        change = a.followers - prev
        pct = change / prev * 100
        out.append(Growth(
            handle=a.handle, was=prev, now=a.followers, change=change,
            pct=pct, from_date=d0, to_date=d1, days=days,
            meaningful=abs(pct) >= min_pct,
        ))
    out.sort(key=lambda g: -g.pct)
    return out


def load_snapshots(out_dir, client: str) -> list[tuple[str, list[Account]]]:
    import json
    from pathlib import Path

    out = []
    for p in sorted(Path(out_dir).glob(f"{client}_scan_*.json")):
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
            out.append((p.stem.rsplit("_", 1)[-1], [Account(**r) for r in rows]))
        except (ValueError, TypeError):
            continue
    return out