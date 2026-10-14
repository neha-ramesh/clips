"""Facebook pages, their recent posts, and whether they are running ads.

WHY FACEBOOK

For a lot of Indian small businesses Facebook is the bigger audience — Davanam
has 24K there against 2.7K on Instagram — and the 30-55 buyers the hand-written
audits name as the real customers are on it. An Instagram-only audit misses
where most of the client's audience already is.

FINDING THE PAGE

In order: a URL the user typed, a facebook.com link in the Instagram bio, the
`facebookPage` field Instagram sometimes returns, a facebook.com link on the
business's website. Pages that cannot be found are listed as such rather than
guessed at.

ADS

Meta's Ad Library is public: every active ad, its text, its call to action and
when it started. The scraper is third-party and its field names drift, so
everything here is read defensively and the raw rows are kept in the cache for
checking. Treat this section as an experiment.

Each page gets its own scraper run, so a result can never be attributed to the
wrong account. Cost: about $0.01 a page, $0.005 a post, $0.006 an ad.
"""

from __future__ import annotations

import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import requests
from pydantic import BaseModel, Field

from .apify import run as _run
from .scan import Account

PAGES_ACTOR = "apify/facebook-pages-scraper"
POSTS_ACTOR = "apify/facebook-posts-scraper"
ADS_ACTOR = "apify/facebook-ads-scraper"

POSTS_PER_PAGE = 6
ADS_PER_PAGE = 3

FB_LINK = re.compile(r"(?:https?://)?(?:www\.|m\.|web\.)?facebook\.com/"
                     r"(profile\.php\?id=\d+|[A-Za-z0-9.\-]{3,80})", re.I)
NOT_A_PAGE = {"sharer", "sharer.php", "share", "plugins", "tr", "dialog", "login",
              "policies", "privacy", "help", "groups", "events", "watch", "pages",
              "home.php", "people", "hashtag", "story.php", "photo.php"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


class FbPage(BaseModel):
    handle: str                     # the Instagram account it belongs to
    url: str = ""
    found_via: str = ""
    name: str = ""
    followers: int = 0
    likes: int = 0
    category: str = ""
    detail: bool = False            # True when recent posts were read
    posts: int = 0                  # posts in the window that came back
    typical_likes: float = 0.0      # reactions on a normal post
    typical_comments: float = 0.0
    typical_shares: float = 0.0
    videos: int = 0
    best: dict = Field(default_factory=dict)   # text, likes, url, date
    error: str = ""


class FbAds(BaseModel):
    handle: str
    url: str = ""
    active: int = 0
    capped: bool = False            # True when we stopped at ADS_PER_PAGE
    samples: list[dict] = Field(default_factory=list)   # text, cta, started, platforms
    error: str = ""
    raw: list[dict] = Field(default_factory=list)       # first rows, for checking


def _page_url(m: str) -> Optional[str]:
    slug = m.split("?")[0].strip("/").lower() if not m.startswith("profile.php") else m
    if not slug or slug.split("/")[0] in NOT_A_PAGE:
        return None
    return f"https://www.facebook.com/{m.strip('/')}"


def _links_in(text: str) -> list[str]:
    out = []
    for m in FB_LINK.findall(text or ""):
        u = _page_url(m)
        if u and u not in out:
            out.append(u)
    return out


def find_pages(accounts: list[Account],
               overrides: dict[str, str]) -> dict[str, tuple[str, str]]:
    """handle -> (page url, how it was found)."""
    out: dict[str, tuple[str, str]] = {}

    def site_links(url: str) -> list[str]:
        try:
            r = requests.get(url if url.startswith("http") else "https://" + url,
                             timeout=12, headers=UA)
            return _links_in(r.text) if r.ok else []
        except requests.RequestException:
            return []

    for a in accounts:
        if a.error:
            continue
        h = a.handle.lower()
        if overrides.get(h):
            out[h] = (overrides[h], "typed in")
            continue
        prof = a.profile or {}
        links = [prof.get("externalUrl") or ""] + list(prof.get("externalUrls") or [])
        fb = [u for link in links for u in _links_in(link)]
        if fb:
            out[h] = (fb[0], "Instagram bio link")
            continue
        page = prof.get("facebookPage")
        if isinstance(page, dict):
            u = page.get("url") or (f"https://www.facebook.com/{page['id']}"
                                     if page.get("id") else "")
            if u:
                out[h] = (u, "Instagram profile")
                continue
        elif isinstance(page, str) and page:
            out[h] = (page if page.startswith("http") else
                      f"https://www.facebook.com/{page}", "Instagram profile")
            continue
        site = next((u for u in links if u and "facebook.com" not in u
                     and "instagram.com" not in u and "wa.me" not in u), "")
        if site:
            found = site_links(site)
            if found:
                out[h] = (found[0], "its website")
    return out


def _first(d: Any, *paths: str, default: Any = None) -> Any:
    """The first present value among dotted paths: 'snapshot.body.text'."""
    for path in paths:
        cur = d
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return default


def _int(v: Any) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _when(v: Any) -> Optional[datetime]:
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)) or str(v).isdigit():
            n = float(v)
            return datetime.fromtimestamp(n / 1000 if n > 1e12 else n, timezone.utc)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


def _one_page(token: str, handle: str, url: str, via: str, days: int,
              with_posts: bool = True) -> FbPage:
    page = FbPage(handle=handle, url=url, found_via=via)
    try:
        rows = _run(token, PAGES_ACTOR, {"startUrls": [{"url": url}]}, cap_usd=0.05)
        if rows:
            r = rows[0]
            page.name = _first(r, "title", "name", "pageName", default="")
            page.followers = _int(_first(r, "followers", "followersCount",
                                         "followings", default=0))
            page.likes = _int(_first(r, "likes", "likesCount", default=0))
            cats = _first(r, "categories", "category", default="")
            page.category = ", ".join(cats) if isinstance(cats, list) else str(cats)
    except Exception as e:
        page.error = f"page: {str(e)[:120]}"

    if not with_posts:
        return page
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    try:
        rows = _run(token, POSTS_ACTOR,
                    {"startUrls": [{"url": url}], "resultsLimit": POSTS_PER_PAGE,
                     "onlyPostsNewerThan": since},
                    cap_usd=round(POSTS_PER_PAGE * 0.006 + 0.02, 2))
    except Exception as e:
        page.error = (page.error + "; " if page.error else "") + f"posts: {str(e)[:120]}"
        return page

    page.detail = True
    posts = []
    for r in rows:
        if r.get("error"):
            continue
        posts.append({
            "likes": _int(_first(r, "likes", "reactionsCount", "topReactionsCount",
                                 "reactions", default=0)),
            "comments": _int(_first(r, "comments", "commentsCount", default=0)),
            "shares": _int(_first(r, "shares", "sharesCount", default=0)),
            "video": bool(_first(r, "isVideo", default=False)
                          or _first(r, "media.0.__typename", default="") == "Video"),
            "text": " ".join(str(_first(r, "text", "message", "postText",
                                        default="")).split())[:200],
            "url": _first(r, "url", "postUrl", "topLevelUrl", default=""),
            "date": str(_first(r, "time", "timestamp", "date", default=""))[:10],
        })
    page.posts = len(posts)
    if posts:
        page.typical_likes = float(statistics.median(p["likes"] for p in posts))
        page.typical_comments = float(statistics.median(p["comments"] for p in posts))
        page.typical_shares = float(statistics.median(p["shares"] for p in posts))
        page.videos = sum(p["video"] for p in posts)
        page.best = max(posts, key=lambda p: p["likes"])
    return page


def _one_ads(token: str, handle: str, url: str) -> FbAds:
    ads = FbAds(handle=handle, url=url)
    try:
        rows = _run(token, ADS_ACTOR,
                    {"startUrls": [{"url": url}], "resultsLimit": ADS_PER_PAGE,
                     "activeStatus": "active"},
                    cap_usd=round(ADS_PER_PAGE * 0.007 + 0.02, 2))
    except Exception as e:
        ads.error = str(e)[:160]
        return ads
    rows = [r for r in rows if not r.get("error")]
    ads.raw = rows[:2]
    ads.active = len(rows)
    ads.capped = len(rows) >= ADS_PER_PAGE
    for r in rows[:3]:
        started = _when(_first(r, "startDate", "start_date", "startDateFormatted",
                               "snapshot.start_date"))
        plats = _first(r, "publisherPlatform", "publisher_platform",
                       "publisherPlatforms", default=[])
        ads.samples.append({
            "text": " ".join(str(_first(r, "snapshot.body.text", "snapshot.body",
                                        "body", "adText", "text",
                                        "snapshot.cards.0.body",
                                        default="")).split())[:220],
            "cta": _first(r, "snapshot.cta_text", "ctaText", "cta_text",
                          "snapshot.cards.0.cta_text", default=""),
            "started": started.date().isoformat() if started else "",
            "platforms": ", ".join(plats) if isinstance(plats, list) else str(plats),
        })
    return ads


def check(token: str, accounts: list[Account], overrides: dict[str, str], *,
          days: int, pages: bool = True, ads: bool = True, client: str = "",
          deep_competitors: int = 2,
          progress: Callable[[str], None] = print
          ) -> tuple[dict[str, FbPage], dict[str, FbAds], list[str]]:
    """(pages by handle, ads by handle, handles with no page found).

    Every page gets its follower count ($0.012). Recent posts and ads — the
    expensive part — only for the client and the `deep_competitors` strongest
    competitors on Instagram, which is who the report compares against anyway.
    """
    found = find_pages(accounts, {k.lower(): v for k, v in overrides.items() if v})
    missing = [a.handle for a in accounts
               if not a.error and a.handle.lower() not in found]
    progress(f"Facebook: found pages for {len(found)} of "
             f"{len(found) + len(missing)} accounts.")
    out_pages: dict[str, FbPage] = {}
    out_ads: dict[str, FbAds] = {}
    if not found:
        return out_pages, out_ads, missing

    ranked = sorted((a for a in accounts if not a.error
                     and a.handle.lower() != client.lower()),
                    key=lambda a: -a.typical_likes)
    deep = {client.lower()} | {a.handle.lower() for a in ranked[:deep_competitors]}

    # Pages and ads all at once: each is its own short actor run.
    with ThreadPoolExecutor(max_workers=5) as pool:
        page_jobs = [pool.submit(_one_page, token, h, url, via, days, h in deep)
                     for h, (url, via) in found.items()] if pages else []
        ad_jobs = [pool.submit(_one_ads, token, h, url)
                   for h, (url, _) in found.items() if h in deep] if ads else []
        for f in page_jobs:
            p = f.result()
            out_pages[p.handle.lower()] = p
        for f in ad_jobs:
            a = f.result()
            out_ads[a.handle.lower()] = a
    return out_pages, out_ads, missing
