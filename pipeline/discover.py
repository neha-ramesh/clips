"""Suggest who a client's competitors might be.

WHAT THE SIGNAL IS

Instagram's own "Suggested for you" row, which Apify exposes as
`relatedProfiles`. It is built on who follows whom, so it captures what a
business actually does without anyone parsing a bio — an account whose audience
overlaps a jeweller's is a jeweller, whatever its bio claims.

WHAT WAS TRIED AND LEFT OUT

Geography from bios: most accounts do not state a city and the ones that do
often list three. Language from captions: accounts here post in English with
Kannada festival names, so almost everything reads as mixed. Both would have
produced a number that looks precise and is not.

Category was in an earlier version and removed. Instagram's own labels are
whatever the account owner picked — a jeweller filed under "Entrepreneur",
another under "Personal Goods & General Merchandise", several under nothing at
all. Showing them implied a classification that does not exist.

IT SUGGESTS, IT DOES NOT CHOOSE

Two accounts in a real set had fifty thousand followers and were effectively
dead. Useful as a warning, useless as a benchmark, and no similarity model
would know the difference. The list is for a person to pick from.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from pydantic import BaseModel

PROFILE_ACTOR = "apify/instagram-profile-scraper"


class DiscoveryError(RuntimeError):
    pass


class Candidate(BaseModel):
    handle: str
    followers: int = 0
    posts: int = 0
    bio: str = ""
    votes: int = 1          # how many accounts suggested it


def get_profiles(client, handles: list[str]) -> list[dict]:
    """Profiles for a set of handles. One run, one billed result each."""
    run = client.actor(PROFILE_ACTOR).call(
        run_input={"usernames": handles, "resultsLimit": 1})
    if run is None:
        return []
    ds = (run.get("defaultDatasetId") if isinstance(run, dict)
          else getattr(run, "default_dataset_id", None))
    if not ds:
        return []
    listed = client.dataset(ds).list_items()
    rows = listed.items if hasattr(listed, "items") else listed.get("items", [])
    return [r for r in rows if isinstance(r, dict)]


def related_of(profile: dict) -> list[dict]:
    """The accounts Instagram suggests alongside this one."""
    for key in ("relatedProfiles", "related_profiles", "similarAccounts"):
        v = profile.get(key)
        if isinstance(v, list) and v:
            return [r for r in v if isinstance(r, dict)]
    return []


def handle_of(row: dict) -> str:
    return (row.get("username") or row.get("handle") or "").lower()


def bio_of(profile: dict) -> str:
    return " ".join((profile.get("biography") or "").split())[:80]


def suggest(
    token: str,
    seed: str,
    *,
    depth: int = 2,
    min_followers: int = 0,
    max_followers: int = 0,
    top: int = 15,
    verbose: bool = True,
) -> list[Candidate]:
    """Accounts that share an audience with `seed`.

    depth 1 is who Instagram suggests beside the client. depth 2 adds who those
    accounts suggest, which reaches businesses the client is not directly
    similar to but sits in the same trade as — and counts how often each name
    recurs, since an account four competitors resemble is more obviously in the
    market than one only a single account does.
    """
    try:
        from apify_client import ApifyClient
    except ImportError as e:
        raise DiscoveryError("Run: pip install apify-client") from e
    if not token:
        raise DiscoveryError("APIFY_TOKEN is not set")

    client = ApifyClient(token)
    seed = seed.strip().lstrip("@").lower()

    profiles = get_profiles(client, [seed])
    if not profiles:
        raise DiscoveryError(f"No profile came back for @{seed}")

    seen: dict[str, dict] = {seed: profiles[0]}
    votes: Counter = Counter()

    frontier = [r for r in related_of(profiles[0]) if handle_of(r)]
    for r in frontier:
        votes[handle_of(r)] += 1
    if verbose:
        print(f"  @{seed} suggests {len(frontier)} accounts")

    if not frontier:
        return []

    if depth >= 2:
        names = [handle_of(r) for r in frontier][:12]
        if verbose:
            print(f"  looking at who those {len(names)} suggest in turn...")
        for prof in get_profiles(client, names):
            h = handle_of(prof)
            if h:
                seen[h] = prof
            for r in related_of(prof):
                rh = handle_of(r)
                if rh and rh != seed:
                    votes[rh] += 1

    votes.pop(seed, None)
    if not votes:
        return []

    # Look the candidates up properly, so follower counts are real rather than
    # whatever the suggestion row happened to carry.
    missing = [h for h, _ in votes.most_common(top * 2) if h not in seen]
    if missing:
        if verbose:
            print(f"  looking up {len(missing)} candidates...")
        for prof in get_profiles(client, missing[:top * 2]):
            h = handle_of(prof)
            if h:
                seen[h] = prof

    out: list[Candidate] = []
    for h, n in votes.most_common():
        p = seen.get(h)
        if not p:
            continue
        f = int(p.get("followersCount") or 0)
        if min_followers and f < min_followers:
            continue
        if max_followers and f > max_followers:
            continue
        out.append(Candidate(handle=h, followers=f,
                             posts=int(p.get("postsCount") or 0),
                             bio=bio_of(p), votes=n))
        if len(out) >= top:
            break
    return out


def check(token: str, seed: str) -> tuple[int, list[str]]:
    """One lookup: does this account have suggestions at all?

    Instagram does not return them for every profile, and account size is
    only one of the reasons. See `check_details` for the rest.
    """
    d = check_details(token, seed)
    return d["followers"], d["related"]


def check_details(token: str, seed: str) -> dict:
    """The same lookup, with enough of the raw profile to diagnose an empty
    result. Callers can tell "Instagram returned nothing" apart from "the
    profile came back rich but relatedProfiles was missing", which have
    different causes and different workarounds.

    Instagram's relatedProfiles can be empty for four reasons the caller
    should be able to distinguish:

      1. The account is small enough that Instagram's own algorithm has no
         confident neighbours for it. Real, and common under ~1000 followers.
      2. The owner has switched off "Show suggested accounts on profile" in
         Instagram's privacy settings. Neither Apify nor anyone else can
         override this, and it fires regardless of follower count — a 60k
         account with the toggle off returns exactly what a 60-follower
         account with no signal returns.
      3. The profile is private, in which case nothing about it comes back
         at all beyond the header fields.
      4. The Apify actor did not include the field. Rare with
         instagram-profile-scraper, but worth being able to see.

    The tuple form used to conflate all four into "the account is too
    small", which was wrong for cases 2, 3 and 4 and unhelpful for the
    caller.
    """
    from apify_client import ApifyClient

    profiles = get_profiles(ApifyClient(token), [seed.strip().lstrip("@")])
    if not profiles:
        return {"found": False, "followers": 0, "related": [],
                "private": False, "verified": False, "posts": 0,
                "bio": "", "category": "", "keys": []}
    p = profiles[0]
    return {
        "found": True,
        "followers": int(p.get("followersCount") or 0),
        "related": [handle_of(r) for r in related_of(p) if handle_of(r)],
        "private": bool(p.get("private")),
        "verified": bool(p.get("verified")),
        "posts": int(p.get("postsCount") or 0),
        "bio": bio_of(p),
        "category": p.get("businessCategoryName") or p.get("category") or "",
        # Sorted so a diagnostic panel shows them stably. Useful when the
        # profile came back but relatedProfiles simply is not among the keys
        # — that is a different failure from Instagram returning [].
        "keys": sorted(p.keys()),
    }