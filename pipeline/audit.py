"""Everything the audit adds on top of the scan, run once and cached.

    scan  ->  enrich (images, what is in them, comments, search visibility,
              Facebook, ads)  ->  ideas + plan  ->  offer  ->  report

The scan stays the scan: counts checked against real grids. Each step here is
independent and may fail on its own — a scraper changes its fields, a page has
no Facebook — without taking the report down. What failed is written into
`log` and shown, never silently skipped.

Results are saved beside the snapshot as `{client}_extras_{stamp}.json`, so
re-rendering a report, or rebuilding it from "Use last scan", costs nothing.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field

from . import comments as comments_mod
from . import facebook as fb_mod
from . import media, visibility as vis_mod, visual
from .comments import CommentRead
from .facebook import FbAds, FbPage
from .habits import Habits, habits_of
from .offer import Offer, pitch
from .scan import Account
from .visibility import Visibility
from .visual import AccountLook


class Options(BaseModel):
    visual: bool = True
    comments: bool = True
    visibility: bool = True
    facebook: bool = True
    ads: bool = True
    search_terms: list[str] = Field(default_factory=list)
    fb_overrides: dict[str, str] = Field(default_factory=dict)   # handle -> url


class Extras(BaseModel):
    stamp: str = ""
    local: bool = True
    thumbs_saved: int = 0
    thumbs_missing: int = 0
    looks: dict[str, AccountLook] = Field(default_factory=dict)
    comments: dict[str, CommentRead] = Field(default_factory=dict)
    visibility: Optional[Visibility] = None
    fb_pages: dict[str, FbPage] = Field(default_factory=dict)
    fb_ads: dict[str, FbAds] = Field(default_factory=dict)
    fb_missing: list[str] = Field(default_factory=list)
    offer: Optional[Offer] = None
    place_words: list[str] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)

    def habits(self, accounts: list[Account]) -> dict[str, Habits]:
        """Free to compute, so never cached — always matches the scan."""
        return {a.handle.lower(): habits_of(a, self.place_words)
                for a in accounts if not a.error}


def extras_path(out_dir, client: str, stamp: str) -> Path:
    return Path(out_dir) / f"{client}_extras_{stamp}.json"


def load(out_dir, client: str, stamp: str) -> Optional[Extras]:
    p = extras_path(out_dir, client, stamp)
    if not p.exists():
        return None
    try:
        return Extras(**json.loads(p.read_text(encoding="utf-8")))
    except (ValueError, TypeError):
        return None


def save(extras: Extras, out_dir, client: str) -> Path:
    p = extras_path(out_dir, client, extras.stamp)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(extras.model_dump_json(indent=1), encoding="utf-8")
    return p


def place_words(place: str, locations: str = "") -> list[str]:
    words = re.split(r"[,|/;·]+", f"{place},{locations}")
    return [w.strip() for w in words if len(w.strip()) >= 3]


def enrich(token: str, accounts: list[Account], client: str, stamp: str,
           out_dir, *, business: str, place: str, local: bool,
           locations: str = "", options: Optional[Options] = None,
           reuse: Optional[dict] = None,
           progress: Callable[[str], None] = print) -> Extras:
    """`reuse`: what competitor search already found (its Instagram search
    results, Maps places and the client's listing). Nothing is searched twice."""
    opt = options or Options()
    ex = Extras(stamp=stamp, local=local, place_words=place_words(place, locations))

    def say(msg: str) -> None:
        ex.log.append(msg)
        progress(msg)

    say("Saving post images...")
    ex.thumbs_saved, ex.thumbs_missing = media.fetch_thumbs(accounts, out_dir)
    if ex.thumbs_missing:
        say(f"{ex.thumbs_missing} post images could not be downloaded "
            "(Instagram's links expire a few days after a scan).")

    reuse = reuse or {}
    terms = [t.strip() for t in opt.search_terms if t.strip()]
    have_search = bool(reuse.get("ig_search")) and not terms
    if opt.visibility and not terms and not have_search and business:
        try:
            terms = vis_mod.suggest_terms(business, place, local)
            say("Searches to check: " + ", ".join(f"'{t}'" for t in terms))
        except Exception as e:
            say(f"Could not come up with search terms: {e}")

    # Four independent steps; each one's failure is its own.
    jobs: dict[str, Callable[[], object]] = {}
    if opt.visual:
        jobs["visual"] = lambda: visual.look_at_all(accounts, out_dir, say)
    if opt.comments:
        jobs["comments"] = lambda: comments_mod.read_comments(accounts, say)
    if opt.visibility and (terms or have_search or reuse.get("maps_places")):
        jobs["visibility"] = lambda: vis_mod.check(
            token, accounts, client, terms, place=place, local=local,
            reuse=reuse if not terms else {k: v for k, v in reuse.items()
                                           if k in ("maps_places", "client_place")},
            progress=say)
    if opt.facebook or opt.ads:
        jobs["facebook"] = lambda: fb_mod.check(
            token, accounts, opt.fb_overrides, days=accounts[0].days if accounts else 30,
            pages=opt.facebook, ads=opt.ads, client=client, progress=say)

    say("Looking at posts, comments, search results and Facebook...")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(fn) for name, fn in jobs.items()}
        for name, fut in futures.items():
            try:
                got = fut.result()
            except Exception as e:
                say(f"{name} failed, carrying on without it: {str(e)[:200]}")
                continue
            if name == "visual":
                ex.looks = got
            elif name == "comments":
                ex.comments = got
            elif name == "visibility":
                ex.visibility = got
                ex.log.extend(got.notes)
            elif name == "facebook":
                ex.fb_pages, ex.fb_ads, ex.fb_missing = got
    save(ex, out_dir, client)
    return ex


# --------------------------------------------------------------------------- #
# The offer, written last because it answers the findings
# --------------------------------------------------------------------------- #

def findings_text(accounts: list[Account], client: str, ex: Extras, ideas) -> str:
    """A short, factual digest of the audit for the offer step."""
    lines = []
    me = next((a for a in accounts if a.handle.lower() == client.lower()), None)
    habits = ex.habits(accounts)
    if me and not me.error:
        lines.append(f"Client @{me.handle}: {me.followers:,} followers, "
                     f"{me.post_count} posts in {me.days} days, a normal post gets "
                     f"{me.typical_likes:,.0f} likes.")
        h = habits.get(me.handle.lower())
        if h:
            lines.append(f"Client habits: location tag on {h.with_location} of "
                         f"{h.posts} posts, hashtags on {h.with_hashtags}, "
                         f"{h.highlights if h.highlights is not None else '?'} "
                         f"highlights, link in bio: {h.has_link}.")
        look = ex.looks.get(me.handle.lower())
        if look and look.posts:
            c = visual.counts(look)
            lines.append("Client's posts by format: " + ", ".join(
                f"{visual.FORMATS[k].lower()} {v}" for k, v in c.items()
                if not k.startswith("_")))
    pages = ex.fb_pages.get(client.lower())
    if pages and pages.followers:
        lines.append(f"Client Facebook: {pages.followers:,} followers, "
                     f"{pages.posts} recent posts.")
    if ex.visibility:
        for t, handles in ex.visibility.instagram.items():
            r = vis_mod.rank_of(client, handles)
            lines.append(f"Instagram search '{t}': client "
                         + (f"at #{r}" if r else "not in the top results"))
    if ideas is not None:
        for p in getattr(ideas, "patterns", [])[:5]:
            lines.append(f"Pattern: {p.what} ({p.evidence})")
        plan = getattr(ideas, "plan", None)
        if plan and plan.cadence:
            lines.append(f"Recommended cadence: {plan.cadence}")
    return "\n".join(lines)


def make_offer(accounts: list[Account], client: str, ex: Extras, ideas,
               brief_text: str, out_dir,
               progress: Callable[[str], None] = print) -> Optional[Offer]:
    try:
        ex.offer = pitch(findings_text(accounts, client, ex, ideas), brief_text)
        save(ex, out_dir, client)
        return ex.offer
    except Exception as e:
        ex.log.append(f"The Conra AI section could not be written: {e}")
        progress(f"The Conra AI section could not be written: {e}")
        return None
