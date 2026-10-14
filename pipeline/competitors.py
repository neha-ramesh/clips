"""Find a client's competitors from several sources, then check every one.

WHY NOT JUST INSTAGRAM'S SUGGESTIONS

`discover.py` reads Instagram's "Suggested for you" row. Tested on a Bangalore
jeweller, only a third of what it returned were competitors — the rest were
saree shops sharing the audience and jewellers in other cities — and some
accounts get no suggestions at all. The sources here were tested side by side
on the same client (temp/5_evaluate/results.md) and this is what held up.

THE STEPS

  0. Understand the client. Claude reads the Instagram profile and the
     client's website and decides what the business sells, to whom, and
     whether it is LOCAL (a shop, clinic, café — competes with businesses
     nearby) or ONLINE (software, a D2C brand, an app — competes with anyone
     in the same category). Everything after this branches on that: a SaaS
     company's competitors are not on Google Maps and not in its city.
  1. Claude with web search names the competitors, with their websites.
  2. Each competitor's Instagram handle comes from, in order: the competitor's
     own website (most reliable — businesses link their own account), the
     handle web search saw, Instagram's own search on the business name.
  3. LOCAL only: Google Maps around the client's own listing adds the shops
     nearby, each with a Google-checked address.
  4. Instagram's suggestions, which come free with the client's profile.
  5. Every candidate is looked up and graded against the client, so the user
     sees the direct competitors first and the rest set aside with a reason.

Competitors with no usable Instagram are kept and shown with their website:
plenty of businesses, software companies especially, barely post, and a
competitor list that silently drops them is wrong about the market.

COST

About $1-1.50 a run: roughly $0.40 of Apify and the rest Claude. Every Apify
run carries a hard spending cap.
"""

from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from difflib import SequenceMatcher
from typing import Callable, Optional

import requests
from pydantic import BaseModel, Field

from . import cache
from .apify import run as apify_run
from .config import config
from .discover import DiscoveryError, bio_of, handle_of, related_of
from .llm import _salvage, _strip_fences

PROFILE_ACTOR = "apify/instagram-profile-scraper"
SEARCH_ACTOR = "apify/instagram-search-scraper"
MAPS_ACTOR = "compass/crawler-google-places"

MAPS_RADIUS_KM = 4
MAPS_PLACES = 30
WEB_SEARCHES = 12
# Competitor search is left as it was tested, except that candidates are checked
# by Sonnet (config.check_model). An attempt to make it cheaper and faster —
# fewer searches and a 90 s cap on Instagram's name search — cut a SaaS client's
# list from a dozen direct competitors to one: the capped search stopped before
# finding the handles. Do not trade its results for speed without re-testing on
# a real client.
SUGGESTIONS_USED = 15
SITE_CHARS = 6000

LABELS = ("direct", "other_market", "adjacent", "unrelated", "unclear")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


class Understanding(BaseModel):
    """What the client is, as read from its profile and website."""

    summary: str = ""
    kind: str = "local"          # "local" or "online"
    category: str = ""
    customers: str = ""
    market: str = ""             # a city for local; a country, region or "global" for online
    maps_term: str = ""          # what to type into Google Maps; empty for online
    confidence: str = "low"      # high / medium / low
    notes: str = ""
    website: str = ""            # the site that was read, if any


class Found(BaseModel):
    """One candidate, with where it came from and what the check made of it.

    `handle` is empty for a competitor found on the web with no Instagram
    account anyone could find; its `label` is then "no_instagram".
    """

    handle: str = ""
    name: str = ""
    website: str = ""
    followers: int = 0
    posts: int = 0
    last_post: str = ""          # ISO date of the newest post seen, if any
    bio: str = ""
    category: str = ""
    sources: list[str] = Field(default_factory=list)    # web, maps, suggested
    evidence: list[str] = Field(default_factory=list)   # what each source said about it
    label: str = ""     # one of LABELS, "no_instagram" or "not_found"
    city: str = ""
    reason: str = ""

    @property
    def votes(self) -> int:
        return len(self.sources)


class Discovery(BaseModel):
    understood: Understanding
    found: list[Found] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)       # one line per step, for the UI
    # Collected along the way and reused by the audit, so it never pays twice:
    profiles: dict[str, dict] = Field(default_factory=dict)  # handle -> profile row
    search_terms: list[str] = Field(default_factory=list)
    ig_search: dict[str, list[str]] = Field(default_factory=dict)  # term -> handles
    maps_places: list[dict] = Field(default_factory=list)    # nearby places, in order
    client_place: Optional[dict] = None                      # the client's own listing


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

_run = apify_run    # kept under the old name; visibility and facebook import it


def _profiles(token: str, handles: list[str]) -> dict[str, dict]:
    """Full profile rows, latest 12 posts included. Today's are reused."""
    out: dict[str, dict] = {}
    missing = []
    for h in dict.fromkeys(_clean(h) for h in handles if h):
        got = cache.get_profile(h)
        if got:
            out[h] = got
        else:
            missing.append(h)
    if missing:
        rows = _run(token, PROFILE_ACTOR, {"usernames": missing, "resultsLimit": 1},
                    cap_usd=round(len(missing) * 0.003 + 0.05, 2))
        for r in rows:
            h = handle_of(r)
            if h and not r.get("error"):
                out[h] = r
                cache.put_profile(h, r)
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _clean(h: str) -> str:
    return (h or "").strip().lstrip("@").strip("/").lower()


def _name_match(name: str, profile: dict) -> float:
    """How well an Instagram profile matches a business name, 0 to 1."""
    n = _norm(name)
    best = 0.0
    for other in (profile.get("fullName"), profile.get("username")):
        o = _norm(other)
        if not n or not o:
            continue
        if len(n) >= 5 and len(o) >= 5 and (n in o or o in n):
            best = max(best, 0.9)
        best = max(best, SequenceMatcher(None, n, o).ratio())
    return best


def _last_post(profile: dict) -> str:
    stamps = [p.get("timestamp") for p in profile.get("latestPosts") or []
              if p.get("timestamp")]
    return max(stamps)[:10] if stamps else ""


# --------------------------------------------------------------------------- #
# Websites
# --------------------------------------------------------------------------- #

IG_LINK = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})", re.I)
NOT_A_HANDLE = {"p", "reel", "reels", "explore", "stories", "accounts", "tv",
                "direct", "about", "developer", "legal", "instagram", "share"}
# Links in a bio that are not the business's own site.
NOT_A_SITE = re.compile(r"instagram\.com|wa\.me|whatsapp\.com|facebook\.com|"
                        r"youtube\.com|youtu\.be|t\.me", re.I)


def _handles_in(text: str) -> list[str]:
    out = []
    for m in IG_LINK.findall(text or ""):
        h = _clean(m).rstrip(".")
        if h and h not in NOT_A_HANDLE and h not in out:
            out.append(h)
    return out


def _fetch(url: str) -> str:
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = requests.get(url, timeout=12, headers=UA)
        return r.text if r.ok else ""
    except requests.RequestException:
        return ""


def _site_handles(url: str) -> list[str]:
    return _handles_in(_fetch(url))


def _site_text(url: str) -> str:
    """Readable text of a homepage: title, description, then the body."""
    page = _fetch(url)
    if not page:
        return ""
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)',
                     page, re.I)
    body = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page,
                  flags=re.I | re.S)
    body = html.unescape(re.sub(r"<[^>]+>", " ", body))
    parts = [f"Title: {title.group(1).strip()}" if title else "",
             f"Description: {html.unescape(desc.group(1))}" if desc else "",
             " ".join(body.split())]
    return "\n".join(p for p in parts if p)[:SITE_CHARS]


def _client_site(me: dict, given: str) -> str:
    if given.strip():
        return given.strip()
    urls = [me.get("externalUrl") or ""] + [
        (u.get("url") if isinstance(u, dict) else str(u))
        for u in me.get("externalUrls") or []]
    return next((u for u in urls if u and not NOT_A_SITE.search(u)), "")


# --------------------------------------------------------------------------- #
# Step 0: understand the client
# --------------------------------------------------------------------------- #

UNDERSTAND_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "kind": {"type": "string", "enum": ["local", "online"]},
        "category": {"type": "string"},
        "customers": {"type": "string"},
        "market": {"type": "string"},
        "maps_term": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "notes": {"type": "string"},
    },
    "required": ["summary", "kind", "category", "customers", "market",
                 "maps_term", "confidence", "notes"],
    "additionalProperties": False,
}

UNDERSTAND_SYSTEM = """You work out what a business is, so its competitors can
be found. You get its Instagram profile, recent captions and the text of its
website, plus optional hints the user typed.

Decide:
- summary: one sentence - what it sells and to whom.
- kind: "local" if customers come to it or it serves one area (shop,
  restaurant, clinic, salon, gym, local services) - its competitors are nearby.
  "online" if it sells across a country or worldwide (software / SaaS, apps,
  D2C brands shipping nationally, online courses, agencies serving clients
  anywhere) - its competitors are anyone in the same category, wherever based.
- category: the specific category a buyer would compare it within, e.g.
  "fine gold and diamond jewellery retail" or "AI meeting-notes software for
  sales teams". Be specific; "SaaS" or "retail" alone is useless.
- customers: who buys - consumers or businesses, which kind, price tier.
- market: where its customers are. A city or area for local businesses; a
  country, region or "global" for online ones.
- maps_term: for local businesses, the 1-3 words you would type into Google
  Maps to find similar places ("jewellery store", "dental clinic"). Empty for
  online businesses.
- confidence: how sure you are, given what you were shown.
- notes: anything unclear or contradictory, briefly.

The website and captions are better evidence than the user's hints; use the
hints to break ties or fill gaps, and say in notes if they disagree."""


def _understand(handle: str, me: dict, site: str, site_text: str,
                business: str, place: str) -> Understanding:
    import anthropic

    posts = me.get("latestPosts") or []
    payload = {
        "instagram": {
            "handle": handle,
            "name": me.get("fullName"),
            "bio": me.get("biography"),
            "category": me.get("businessCategoryName"),
            "followers": me.get("followersCount"),
            "posts": me.get("postsCount"),
            "recent_captions": [" ".join((p.get("caption") or "").split())[:200]
                                for p in posts[:8]],
            "recent_locations": sorted({p.get("locationName") for p in posts
                                        if p.get("locationName")}),
        },
        "website": {"url": site, "text": site_text} if site_text else
                   ({"url": site, "text": "(could not be read)"} if site else None),
        "user_hints": {"business": business or None, "city": place or None},
    }
    api = anthropic.Anthropic(api_key=config.anthropic_api_key)
    resp = api.messages.create(
        model=config.discovery_model, max_tokens=16000, system=UNDERSTAND_SYSTEM,
        output_config={"effort": "high",
                       "format": {"type": "json_schema", "schema": UNDERSTAND_SCHEMA}},
        messages=[{"role": "user",
                   "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return Understanding(**json.loads(text), website=site)


# --------------------------------------------------------------------------- #
# Step 1: Claude with web search names the competitors
# --------------------------------------------------------------------------- #

NAME_SYSTEM_LOCAL = """You find a local business's direct competitors.

A direct competitor sells the same kind of product or service to the same kind
of customer in the same area: someone choosing the client could plausibly
choose them instead. Not competitors: brands or suppliers the client stocks,
wholesalers that do not sell to the public, influencers, media pages, and
businesses in other cities. Prefer competitors close to the client in price
tier and in the parts of the city the client serves.

Use web search. Good sources are map and directory listings, "best <trade> in
<city>" articles and the businesses' own websites."""

NAME_SYSTEM_ONLINE = """You find an online business's direct competitors.

A direct competitor sells a product in the same category to the same kind of
customer: a buyer evaluating the client would shortlist them too. Location
matters only as far as the client's market does - a company selling in the
same country or worldwide counts wherever it is based. Not competitors:
tools the client integrates with, platforms it sells through, resellers,
agencies, influencers and media pages. Prefer competitors of a similar size
and price point to the client over the category's giants, but include the
leaders a buyer would certainly compare against.

Use web search. Good sources are review and comparison sites (G2, Capterra,
Product Hunt, "alternatives to X" and "best <category>" articles), startup
databases, and the companies' own websites."""

NAME_RULES = """
For each competitor give its website (homepage URL) whenever you can find it -
it is used to find the Instagram account. Include an Instagram handle only if
you saw it in a source. Never construct one from a name; give null instead -
handles are looked up separately."""


def _web_named(handle: str, client_name: str, u: Understanding) -> list[dict]:
    import anthropic

    system = (NAME_SYSTEM_ONLINE if u.kind == "online" else NAME_SYSTEM_LOCAL) + NAME_RULES
    user = (f"Client: @{handle} ({client_name})\n"
            f"What it is: {u.summary}\nCategory: {u.category}\n"
            f"Customers: {u.customers}\nMarket: {u.market}\n"
            + (f"Website: {u.website}\n" if u.website else "")
            + "\nFind up to 20 direct competitors. Reply with JSON only:\n"
            '{"competitors": [{"name": "...", "website": "... or null", '
            '"handle": "... or null", "source_url": "...", '
            '"why": "one line: what they sell, to whom, why they compete"}]}')
    api = anthropic.Anthropic(api_key=config.anthropic_api_key)
    messages: list = [{"role": "user", "content": user}]
    tools = [{"type": "web_search_20260209", "name": "web_search",
              "max_uses": WEB_SEARCHES}]
    resp = None
    for _ in range(4):
        resp = api.beta.messages.create(
            model=config.discovery_model, max_tokens=16000, system=system,
            messages=messages, tools=tools, output_config={"effort": "high"},
            # A refusal is re-run on a fallback model instead of failing.
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if resp.stop_reason != "pause_turn":
            break
        # The server's search loop hit its turn limit; hand it back to finish.
        messages = messages + [{"role": "assistant", "content": resp.content}]
    if resp is None or resp.stop_reason == "refusal":
        return []
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        rows = json.loads(_strip_fences(text)).get("competitors", [])
    except (ValueError, AttributeError):
        rows = _salvage(text, "name")
    return [r for r in rows if isinstance(r, dict) and r.get("name")]


# --------------------------------------------------------------------------- #
# Step 2: an Instagram handle for each named competitor
# --------------------------------------------------------------------------- #

SEARCH_PUNCT = re.compile(r"""[!?.,:;\-+=*&%$#@/\\~^|<>()\[\]{}"'`]""")


def _handles_from_sites(named: list[dict]) -> None:
    """Fill r["_handle"] from each competitor's own website, where it links one."""
    todo = [r for r in named if r.get("website")]

    def one(r: dict) -> tuple[dict, list[str]]:
        return r, _site_handles(r["website"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        for r, found in pool.map(one, todo):
            if found:
                r["_handle"], r["_via"] = found[0], "its website"


def _handles_from_search(token: str, named: list[dict], u: Understanding) -> dict[str, dict]:
    """Instagram search for every competitor still without a handle.

    Returns handle -> profile for the matches. The handle web search saw is
    preferred when the search returns it; otherwise the closest name match,
    if close. A local business is searched with its city, an online one
    without — "Notion Chennai" finds nothing.
    """
    queries = {}
    for r in named:
        if r.get("_handle"):
            continue
        q = r["name"] + (f" {u.market}" if u.kind == "local" and u.market else "")
        # The actor rejects the whole run if any term carries punctuation, and
        # business names are full of it: "C. Krishniah Chetty & Sons".
        q = " ".join(SEARCH_PUNCT.sub(" ", q).split())
        if q:
            queries[q] = r
    if not queries:
        return {}
    rows = _run(token, SEARCH_ACTOR,
                {"search": ", ".join(queries), "searchType": "user",
                 "searchLimit": 3},
                cap_usd=round(len(queries) * 3 * 0.003 + 0.05, 2))

    hits: dict[str, list[dict]] = {}
    for row in rows:
        hits.setdefault(row.get("searchTerm") or "", []).append(row)

    profiles: dict[str, dict] = {}
    for q, r in queries.items():
        given = _clean(r.get("handle") or "")
        cands = [h for h in hits.get(q, []) if handle_of(h) and not h.get("error")]
        pick = next((h for h in cands if handle_of(h) == given), None)
        if pick is None and cands:
            best = max(cands, key=lambda h: _name_match(r["name"], h))
            if _name_match(r["name"], best) >= 0.6:
                pick = best
        if pick is not None:
            r["_handle"], r["_via"] = handle_of(pick), "Instagram search"
            profiles[handle_of(pick)] = pick
        elif given:
            r["_handle"], r["_via"] = given, "web search"
    return profiles


# --------------------------------------------------------------------------- #
# Step 3: Google Maps around the client (local businesses only)
# --------------------------------------------------------------------------- #

def _maps(token: str, client_name: str, u: Understanding,
          log: Callable[[str], None]
          ) -> tuple[Optional[dict], dict[str, dict], list[dict]]:
    """(the client's own listing or None, handle -> nearby place, every place).

    Every place is returned too: the audit's "can people find you on Maps"
    section reuses them instead of searching Maps a second time.
    """
    me = None
    if client_name and u.market:
        rows = _run(token, MAPS_ACTOR,
                    {"searchStringsArray": [client_name], "locationQuery": u.market,
                     "maxCrawledPlacesPerSearch": 1, "language": "en"},
                    cap_usd=0.5)
        # A name search returns the nearest-sounding business, which may not
        # be the client. Only trust it as the search centre if the names agree.
        if rows and rows[0].get("location") and SequenceMatcher(
                None, _norm(client_name), _norm(rows[0].get("title"))).ratio() >= 0.6:
            me = rows[0]

    term = u.maps_term or (me or {}).get("categoryName") or u.category
    run_input = {"searchStringsArray": [term], "language": "en",
                 "maxCrawledPlacesPerSearch": MAPS_PLACES, "scrapeContacts": True}
    if me:
        loc = me["location"]
        run_input["customGeolocation"] = {"type": "Point", "radiusKm": MAPS_RADIUS_KM,
                                          "coordinates": [loc["lng"], loc["lat"]]}
        log(f"Maps: '{term}' within {MAPS_RADIUS_KM} km of {me.get('title')}")
    elif u.market:
        run_input["locationQuery"] = u.market
        log(f"Maps: client not found on Maps, searching '{term}' across {u.market}")
    else:
        log("Maps: skipped — no city to search in")
        return None, {}, []
    rows = _run(token, MAPS_ACTOR, run_input, cap_usd=0.5)

    def handles(p: dict) -> list[str]:
        """The contact add-on's links first, then the Maps website field,
        then the website itself."""
        found = _handles_in(" ".join(p.get("instagrams") or []))
        site = p.get("website") or ""
        if not found and "instagram.com" in site:
            found = _handles_in(site)
        if not found and site:
            found = _site_handles(site)
        return found

    # Every website at once: one slow site no longer holds up the rest.
    with ThreadPoolExecutor(max_workers=10) as pool:
        found_all = list(pool.map(handles, rows))

    out: dict[str, dict] = {}
    for p, found in zip(rows, found_all):
        # The first link on a business's site is nearly always its own account;
        # later ones are brands it stocks or the web designer's credit.
        if found and found[0] not in out:
            out[found[0]] = p
    return me, out, rows


# --------------------------------------------------------------------------- #
# Step 5: the check
# --------------------------------------------------------------------------- #

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"labels": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "handle": {"type": "string"},
            "label": {"type": "string", "enum": list(LABELS)},
            "city": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["handle", "label", "city", "reason"],
        "additionalProperties": False,
    }}},
    "required": ["labels"],
    "additionalProperties": False,
}


def _rubric(client: dict, u: Understanding) -> str:
    head = f"""You are checking candidate competitors for a client.

Client: @{client['handle']} - {client['name']}
What it is: {u.summary}
Category: {u.category}
Customers: {u.customers}
Market: {u.market}
{('Address: ' + client['address']) if client.get('address') else ''}

Label each Instagram profile with exactly one of:"""
    if u.kind == "online":
        body = """
- "direct": sells a product in the same category to the same kind of
  customer, in a market that overlaps the client's. Where it is based does
  not matter if it sells where the client sells.
- "other_market": the same category, but evidently sold to a market the
  client does not serve (another country only, or a very different segment).
- "adjacent": related but not like-for-like - tools the client integrates
  with, platforms, resellers, agencies or consultants, influencers, news or
  media pages, communities.
- "unrelated": a different category altogether.
- "unclear": possibly a competitor, but the profile does not show enough of
  what it sells to say.

Judge from the profile and its `external_evidence`. A web source is evidence of
what that page says. If the evidence names a business that is not this
profile, say so and do not count the evidence. Put the company's base or main
market in `city`."""
    else:
        body = """
- "direct": sells the same kind of product or service as the client, to the
  same kind of customer, in the client's area or clearly serving it. Chains
  with outlets in the area count.
- "other_market": the same kind of business, but its outlets and customers
  are evidently elsewhere.
- "adjacent": related but not like-for-like - suppliers, brands sold through
  shops like the client's, wholesalers, a clearly different tier or substitute
  product, rental services, influencers, news or media pages.
- "unrelated": a different trade altogether.
- "unclear": the right trade, but nothing shows where it sells.

Judge from the profile and its `external_evidence`. A map listing's address is
reliable location evidence; a web source is evidence of what that page says.
If the evidence names a business that is not this profile, say so and do not
count the evidence. Be strict: "direct" needs evidence of the area."""
    return head + body


def _card(h: str, prof: dict, evidence: list[str], website: str) -> dict:
    posts = prof.get("latestPosts") or []
    return {
        "handle": h,
        "name": prof.get("fullName"),
        "bio": prof.get("biography"),
        "category": prof.get("businessCategoryName"),
        "followers": prof.get("followersCount"),
        "website": prof.get("externalUrl") or website,
        "last_post": _last_post(prof),
        "recent_captions": [" ".join((p.get("caption") or "").split())[:160]
                            for p in posts[:5]],
        "recent_locations": sorted({p.get("locationName") for p in posts
                                    if p.get("locationName")}),
        "external_evidence": evidence[:4],
    }


def _judge(client: dict, u: Understanding, cards: list[dict]) -> dict[str, dict]:
    import anthropic

    if not cards:
        return {}
    api = anthropic.Anthropic(api_key=config.anthropic_api_key)
    system = _rubric(client, u)

    def one(batch: list[dict]) -> dict[str, dict]:
        resp = api.messages.create(
            model=config.check_model, max_tokens=16000, system=system,
            output_config={"effort": "high",
                           "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
            messages=[{"role": "user",
                       "content": json.dumps(batch, ensure_ascii=False, indent=1)}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        out = {}
        for row in json.loads(text).get("labels", []):
            out[_clean(row.pop("handle"))] = row
        return out

    batches = [cards[i:i + 15] for i in range(0, len(cards), 15)]
    labels: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for got in pool.map(one, batches):
            labels.update(got)
    return labels


# --------------------------------------------------------------------------- #
# Putting it together
# --------------------------------------------------------------------------- #

def find_competitors(
    token: str,
    seed: str,
    *,
    business: str = "",
    place: str = "",
    website: str = "",
    min_followers: int = 0,
    max_followers: int = 0,
    progress: Callable[[str], None] = print,
) -> Discovery:
    """Every candidate, checked. Direct competitors first.

    `business`, `place` and `website` are optional hints from the dashboard.
    The business is read from its profile and website either way; the hints
    break ties and fill gaps when those say little.
    """
    if not token:
        raise DiscoveryError("APIFY_TOKEN is not set")
    if not config.anthropic_api_key:
        raise DiscoveryError("ANTHROPIC_API_KEY is not set")

    log: list[str] = []

    def say(msg: str) -> None:
        log.append(msg)
        progress(msg)

    seed = _clean(seed)
    say(f"Looking up @{seed}...")
    me = _profiles(token, [seed]).get(seed)
    if not me:
        raise DiscoveryError(f"No profile came back for @{seed}")
    client_name = me.get("fullName") or seed

    site = _client_site(me, website)
    site_text = _site_text(site) if site else ""
    say(f"Reading the website ({site})..." if site_text else
        "No readable website — working from the Instagram profile alone.")
    u = _understand(seed, me, site, site_text, business, place)
    say(f"Read as: {u.summary} [{u.kind}, market: {u.market or '?'}, "
        f"confidence: {u.confidence}]")
    client = {"handle": seed, "name": client_name}

    # Web search, Maps and the audit's Instagram search check are independent
    # and each takes a minute or more, so they run side by side.
    say("Searching the web" + (", Google Maps" if u.kind == "local" else "")
        + " and Instagram...")

    def ig_visibility() -> tuple[list[str], dict[str, list[str]]]:
        from .visibility import suggest_terms, search_instagram
        terms = suggest_terms(u.category or u.summary, u.market, u.kind == "local")
        return terms, search_instagram(token, terms)

    with ThreadPoolExecutor(max_workers=3) as pool:
        web_f = pool.submit(_web_named, seed, client_name, u)
        maps_f = pool.submit(_maps, token, client_name, u, say) if u.kind == "local" else None
        vis_f = pool.submit(ig_visibility)
        try:
            named = web_f.result()
        except Exception as e:
            say(f"Web search failed, carrying on without it: {e}")
            named = []
        my_place, nearby, all_places = None, {}, []
        if maps_f is not None:
            try:
                my_place, nearby, all_places = maps_f.result()
            except Exception as e:
                say(f"Maps failed, carrying on without it: {e}")
        terms, ig_search = [], {}
        try:
            terms, ig_search = vis_f.result()
        except Exception as e:
            say(f"Instagram search check failed, the audit will retry it: {e}")
    if my_place:
        client["address"] = my_place.get("address") or ""
    say(f"Web search named {len(named)} competitors"
        + (f"; Maps found {len(nearby)} nearby with Instagram." if u.kind == "local" else "."))

    # Handles: own website first, then what web search saw, then Instagram search.
    profiles: dict[str, dict] = {}
    if named:
        _handles_from_sites(named)
        say(f"Found {sum(1 for r in named if r.get('_handle'))} handles on "
            "competitors' websites; searching Instagram for the rest...")
        try:
            profiles.update(_handles_from_search(token, named, u))
        except Exception as e:
            say(f"Instagram name search failed, using web search's handles: {e}")
            for r in named:
                if not r.get("_handle") and r.get("handle"):
                    r["_handle"], r["_via"] = _clean(r["handle"]), "web search"

    found: dict[str, Found] = {}

    def add(h: str, source: str, note: str, name: str = "", site: str = "") -> None:
        h = _clean(h)
        if not h or h == seed:
            return
        f = found.setdefault(h, Found(handle=h))
        if source not in f.sources:
            f.sources.append(source)
        if note:
            f.evidence.append(note)
        f.name = f.name or name
        f.website = f.website or site

    web_only: list[Found] = []
    for r in named:
        note = (f"Web source {r.get('source_url')}: {r.get('name')} - {r.get('why')}"
                + (f" (handle from {r['_via']})" if r.get("_via") else ""))
        if r.get("_handle"):
            add(r["_handle"], "web", note, r.get("name", ""), r.get("website") or "")
        else:
            web_only.append(Found(name=r["name"], website=r.get("website") or "",
                                  sources=["web"], evidence=[note],
                                  label="no_instagram", reason=r.get("why") or ""))
    for h, p in nearby.items():
        add(h, "maps", f"Google Maps listing: {p.get('title')} - {p.get('address')} "
                       f"({p.get('categoryName')})", p.get("title") or "",
            p.get("website") or "")
    for r in related_of(me)[:SUGGESTIONS_USED]:
        add(handle_of(r), "suggested", "")

    missing = [h for h in found if h not in profiles]
    say(f"Checking {len(found)} Instagram accounts"
        + (f" ({len(web_only)} more competitors have no Instagram we could find)"
           if web_only else "") + "...")
    profiles.update(_profiles(token, missing))

    cards = []
    for h, f in list(found.items()):
        p = profiles.get(h)
        if not p:
            if "web" in f.sources:
                # Named on the web but the handle led nowhere: still a
                # competitor, just not one with an Instagram to compare.
                web_only.append(f.model_copy(update={
                    "handle": "", "label": "no_instagram",
                    "reason": "Named by web search; its Instagram handle "
                              "does not exist."}))
            else:
                f.label, f.reason = "not_found", "No Instagram profile by this name."
                web_only.append(f)
            del found[h]
            continue
        f.name = p.get("fullName") or f.name
        f.followers = int(p.get("followersCount") or 0)
        f.posts = int(p.get("postsCount") or 0)
        f.last_post = _last_post(p)
        f.bio = bio_of(p)
        f.category = p.get("businessCategoryName") or ""
        f.website = f.website or p.get("externalUrl") or ""
        cards.append(_card(h, p, f.evidence, f.website))

    for h, row in _judge(client, u, cards).items():
        if h in found:
            found[h].label = row["label"]
            found[h].city = row["city"]
            found[h].reason = row["reason"]

    on_ig = [f for f in found.values()
             if not (min_followers and f.followers < min_followers)
             and not (max_followers and f.followers > max_followers)]
    order = {lab: i for i, lab in enumerate(LABELS)}
    on_ig.sort(key=lambda f: (order.get(f.label, 99), -f.votes, -f.followers))
    web_only = [f for f in web_only if f.label == "no_instagram"] + \
               [f for f in web_only if f.label != "no_instagram"]

    say(f"Done: {sum(f.label == 'direct' for f in on_ig)} direct competitors on "
        f"Instagram, {sum(f.label == 'no_instagram' for f in web_only)} more "
        "without a usable Instagram.")
    keep = ("title", "totalScore", "reviewsCount", "categoryName", "address",
            "website", "rank", "searchString")
    return Discovery(
        understood=u, found=on_ig + web_only, log=log,
        profiles={seed: me, **profiles}, search_terms=terms, ig_search=ig_search,
        maps_places=[{k: p.get(k) for k in keep} for p in all_places],
        client_place={k: my_place.get(k) for k in keep} if my_place else None)


def is_stale(f: Found, days: int = 60) -> bool:
    """Has not posted in `days` — still a competitor, but little to compare."""
    if not f.last_post:
        return f.posts == 0
    try:
        return (datetime.now() - datetime.fromisoformat(f.last_post)).days > days
    except ValueError:
        return False
