"""Method 2: Instagram's own account search, driven by business + place.

Two query sets, kept apart:
  - "city": trade words + the city the user typed
  - "area": trade word + each neighbourhood named in the client's bio, the
            way a shopper would search for a shop near them

Cost: 6 queries x 15 results x $0.0027 ≈ $0.24.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import CLIENT, apify_run, clean, save  # noqa: E402

HERE = Path(__file__).resolve().parent
PER_QUERY = 15

place = CLIENT["place"].lower()
queries = {
    f"jewellers {place}": "city",
    f"jewellery {place}": "city",
    f"diamond jewellery {place}": "city",
    f"gold jewellery {place}": "city",
    # From the client's bio: "Avenue Road|Commercial Street|Malleshwaram"
    "jewellers malleshwaram": "area",
    "jewellers commercial street": "area",
}

raw: dict[str, list[dict]] = {}
for q in queries:
    raw[q] = apify_run("apify/instagram-scraper",
                       {"search": q, "searchType": "user",
                        "searchLimit": PER_QUERY, "resultsType": "details",
                        "resultsLimit": 1},
                       cap_usd=0.08, label=f"kw:{q}")
save(HERE / "raw.json", raw)

hits: dict[str, list[str]] = defaultdict(list)
best_rank: dict[str, int] = {}
for q, rows in raw.items():
    for i, r in enumerate(rows):
        h = clean(r.get("username"))
        if not h or h == CLIENT["handle"]:
            continue
        hits[h].append(q)
        best_rank[h] = min(best_rank.get(h, 99), i)

ranked = sorted(hits, key=lambda h: (-len(hits[h]), best_rank[h]))
cands = [{"handle": h, "why": "search: " + "; ".join(
            f"'{q}' ({queries[q]})" for q in hits[h])} for h in ranked]
save(HERE / "candidates.json", cands)

print(f"\n{len(ranked)} distinct accounts")
for q, rows in raw.items():
    print(f"  '{q}': {len(rows)} -> {[clean(r.get('username')) for r in rows][:8]}")
print("top 20:")
for c in cands[:20]:
    print(f"  @{c['handle']}: {c['why']}")
