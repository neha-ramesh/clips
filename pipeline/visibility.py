"""Can a customer find the client? The searches a customer would type, run.

Both hand-written audits checked this by hand and both found the same thing:
the client did not come up. "Not coming up when we search Bangalore jewellers"
(and five competitors did); "did not even come up when I searched 'dentist in
Mogappair East'" (and twelve clinics did, most with ten times the reviews).

Instagram search: the accounts returned for each term, in order.
Google Maps (local businesses only): the places returned for each term, with
rating and review count, plus the client's own listing.

Instagram's results depend on who is searching and where; a scraper sees the
logged-out version. The report says so, and treats a rank as "shows up near the
top or not", not as an exact position.

Cost: ~$0.10 Instagram + ~$0.20 Maps a run.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable, Optional

from pydantic import BaseModel, Field

from .apify import run as _run
from .config import config
from .llm import complete_json
from .scan import Account

SEARCH_ACTOR = "apify/instagram-search-scraper"
MAPS_ACTOR = "compass/crawler-google-places"
IG_RESULTS = 10
MAPS_RESULTS = 15
SEARCH_TIMEOUT_S = 90      # Instagram's search actor: 2-7 minutes uncapped

PUNCT = re.compile(r"""[!?.,:;\-+=*&%$#@/\\~^|<>()\[\]{}"'`]""")


class Place(BaseModel):
    rank: int
    title: str
    rating: float = 0.0
    reviews: int = 0
    category: str = ""
    address: str = ""
    website: str = ""
    handle: str = ""        # the account in this audit it belongs to, if any


class Visibility(BaseModel):
    terms: list[str] = Field(default_factory=list)
    instagram: dict[str, list[str]] = Field(default_factory=dict)  # term -> handles in order
    maps: dict[str, list[Place]] = Field(default_factory=dict)     # term -> places in order
    client_place: Optional[Place] = None
    notes: list[str] = Field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Words half the businesses in a trade share. Left in, "Kalyan Jewellers" and
# "Davanam Jewellers" score as the same name — the shared "jewellers" outweighs
# the names that differ — and a competitor's listing was marked as the client's.
TRADE_WORDS = re.compile(
    r"\b(jewell?er(y|s)?|jewel(s|ry)?|gold|diamonds?|dental|dentistry|dentist|"
    r"clinic|care|hospital|centre|center|official|store|shop|showroom|boutique|"
    r"pvt|private|ltd|limited|llp|inc|co|company|and|the|of|india|bangalore|"
    r"bengaluru|chennai|mumbai|delhi|hyderabad)\b", re.I)


def _core(s: str) -> str:
    """The distinctive part of a business name or handle."""
    words = re.sub(r"[_.\-]+", " ", s or "")
    return _norm(TRADE_WORDS.sub(" ", words))


def _same(a: str, b: str) -> bool:
    raw_a, raw_b = _norm(a), _norm(b)
    a, b = _core(a), _core(b)
    if len(a) < 3 or len(b) < 3:
        return False
    # A handle run together ("lumadentalcare") keeps its trade words, so look
    # for the other name's distinctive part inside it whole.
    if (len(a) >= 4 and a in raw_b) or (len(b) >= 4 and b in raw_a):
        return True
    if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.8


TERMS_SCHEMA = {
    "type": "object",
    "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
    "required": ["terms"], "additionalProperties": False,
}


def suggest_terms(business: str, place: str, local: bool) -> list[str]:
    """Three searches a customer would really type. Short, lower case."""
    got = complete_json(
        "You write the searches a real customer types into Instagram's and "
        "Google Maps' search box when looking for a business like this. "
        "Two to four words each, lower case, no punctuation, the way people "
        "actually type ('bangalore jewellers', 'dentist mogappair east', "
        "'ai carousel maker'). For a local business, include the city or area.",
        f"Business: {business}\nWhere: {place or 'not given'}\n"
        f"{'Local business' if local else 'Sells online / nationally'}\n"
        "Give 3 searches.",
        schema=TERMS_SCHEMA, list_key="terms", required_field="terms",
        model=config.light_model, temperature=1.0, effort="low")
    terms = [" ".join(PUNCT.sub(" ", t).lower().split())
             for t in got.get("terms", []) if isinstance(t, str)]
    return [t for t in terms if t][:3]


def _place(rank: int, r: dict, accounts: list[Account]) -> Place:
    p = Place(rank=rank, title=r.get("title") or "",
              rating=float(r.get("totalScore") or 0),
              reviews=int(r.get("reviewsCount") or 0),
              category=r.get("categoryName") or "",
              address=r.get("address") or "", website=r.get("website") or "")
    for a in accounts:
        name = (a.profile or {}).get("fullName") or a.handle
        if _same(p.title, name) or _same(p.title, a.handle):
            p.handle = a.handle
            break
    return p


def search_instagram(token: str, terms: list[str]) -> dict[str, list[str]]:
    """term -> handles, in the order Instagram returned them."""
    if not terms:
        return {}
    rows = _run(token, SEARCH_ACTOR,
                {"search": ", ".join(terms), "searchType": "user",
                 "searchLimit": IG_RESULTS},
                cap_usd=round(len(terms) * IG_RESULTS * 0.003 + 0.05, 2),
                timeout_s=SEARCH_TIMEOUT_S)
    return {t: [(r.get("username") or "").lower() for r in rows
                if (r.get("searchTerm") or "") == t and r.get("username")]
            for t in terms}


def check(token: str, accounts: list[Account], client: str, terms: list[str],
          *, place: str, local: bool, reuse: Optional[dict] = None,
          progress: Callable[[str], None] = print) -> Visibility:
    """`reuse` carries what competitor search already found — its Instagram
    search results and its Maps places — so nothing is searched twice."""
    reuse = reuse or {}
    v = Visibility(terms=terms or reuse.get("search_terms") or [])

    if reuse.get("ig_search"):
        v.instagram = reuse["ig_search"]
        v.terms = list(v.instagram)
    elif v.terms:
        try:
            v.instagram = search_instagram(token, v.terms)
            progress(f"Instagram search: checked {len(v.terms)} searches.")
        except Exception as e:
            v.notes.append(f"Instagram search failed: {str(e)[:160]}")
    else:
        v.notes.append("No search terms to check.")

    if not local:
        return v

    if reuse.get("maps_places"):
        groups: dict[str, list[dict]] = {}
        for r in reuse["maps_places"]:
            groups.setdefault(r.get("searchString") or "nearby", []).append(r)
        for t, rows in groups.items():
            rows.sort(key=lambda r: r.get("rank") or 999)
            v.maps[t] = [_place(i, r, accounts) for i, r in enumerate(rows, 1)]
        if reuse.get("client_place"):
            v.client_place = _place(0, reuse["client_place"], accounts)
            v.client_place.handle = client
    elif v.terms and place:
        # No competitor search ran: one Maps search, the first term only.
        try:
            t = v.terms[0]
            rows = _run(token, MAPS_ACTOR,
                        {"searchStringsArray": [t], "locationQuery": place,
                         "maxCrawledPlacesPerSearch": MAPS_RESULTS, "language": "en"},
                        cap_usd=round(MAPS_RESULTS * 0.005 + 0.1, 2))
            rows.sort(key=lambda r: r.get("rank") or 999)
            v.maps[t] = [_place(i, r, accounts) for i, r in enumerate(rows, 1)]
            progress("Google Maps: checked 1 search.")
        except Exception as e:
            v.notes.append(f"Google Maps search failed: {str(e)[:160]}")

    if v.client_place is None:
        for places in v.maps.values():
            for p in places:
                if p.handle.lower() == client.lower():
                    v.client_place = p
                    break
            if v.client_place:
                break
    return v


def rank_of(handle: str, results: list[str]) -> int:
    """1-based position, or 0 if not in the results."""
    h = handle.lower()
    return results.index(h) + 1 if h in results else 0
