"""Method 3: Google Maps businesses, then their Instagram from their website.

Two searches, kept apart:
  - "city": the trade across the whole city
  - "area": the trade near one of the client's stores

Instagram handles come from three places, in order:
  1. the actor's contact add-on, which reads the business website ($0.002/place)
  2. the Maps "website" field itself, which is often an instagram.com link
  3. fetching the website ourselves and looking for an instagram.com link

The actor's dedicated social-media add-on is NOT used: it is $0.10 a profile.

Cost: 60 places x ($0.004 + $0.002) ≈ $0.36.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import CLIENT, apify_run, clean, save  # noqa: E402

HERE = Path(__file__).resolve().parent

searches = {
    "city": ("jewellery store", f"{CLIENT['place']}, India", 40),
    "area": ("jewellery store", f"Malleshwaram, {CLIENT['place']}, India", 20),
}

IG = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})", re.I)
NOT_A_HANDLE = {"p", "reel", "reels", "explore", "stories", "accounts", "tv",
                "direct", "about", "developer", "legal", "instagram", "share"}


def handles_in(text: str) -> list[str]:
    out = []
    for m in IG.findall(text or ""):
        h = clean(m).rstrip(".")
        if h and h not in NOT_A_HANDLE and h not in out:
            out.append(h)
    return out


def from_site(url: str) -> list[str]:
    try:
        r = requests.get(url, timeout=12, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        return handles_in(r.text)
    except Exception:
        return []


raw = {}
for key, (term, where, n) in searches.items():
    raw[key] = apify_run("compass/crawler-google-places",
                         {"searchStringsArray": [term], "locationQuery": where,
                          "maxCrawledPlacesPerSearch": n, "language": "en",
                          "scrapeContacts": True},
                         cap_usd=0.5, label=f"maps:{key}")
save(HERE / "raw.json", raw)

places = []
for key, rows in raw.items():
    for rank, p in enumerate(rows):
        site = p.get("website") or ""
        via, found = "", []
        if p.get("instagrams"):
            via, found = "contact add-on", handles_in(" ".join(p["instagrams"]))
        if not found and "instagram.com" in site:
            via, found = "maps website field", handles_in(site)
        if not found and site:
            via, found = "fetched website", from_site(site)
        places.append({"search": key, "rank": rank, "title": p.get("title"),
                       "category": p.get("categoryName"),
                       "address": p.get("address"), "reviews": p.get("reviewsCount"),
                       "website": site, "instagram": found, "via": via or "none"})
save(HERE / "places.json", places)

who: dict[str, list[dict]] = defaultdict(list)
for pl in places:
    # The first handle on a page is nearly always the business's own; later ones
    # are usually brands it stocks or a web designer's credit.
    if pl["instagram"]:
        h = pl["instagram"][0]
        if h != CLIENT["handle"]:
            who[h].append(pl)

ranked = sorted(who, key=lambda h: (-len(who[h]), min(p["rank"] for p in who[h])))
cands = [{"handle": h, "why": f"Maps ({', '.join(sorted({p['search'] for p in who[h]}))}): "
          + "; ".join(f"{p['title']} via {p['via']}" for p in who[h][:3])}
         for h in ranked]
save(HERE / "candidates.json", cands)

n = len(places)
with_site = sum(1 for p in places if p["website"])
with_ig = sum(1 for p in places if p["instagram"])
print(f"\n{n} places, {with_site} with a website, {with_ig} with an Instagram handle")
for via in ("contact add-on", "maps website field", "fetched website", "none"):
    print(f"  via {via}: {sum(1 for p in places if p['via'] == via)}")
print(f"{len(ranked)} distinct handles")
for c in cands[:25]:
    print(f"  @{c['handle']}: {c['why']}")
