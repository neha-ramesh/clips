"""Method 1: who else posts under the client's trade hashtags.

Two tag sources, kept apart so each can be judged:
  - "client": the client's own tags, filtered to ones naming the trade
  - "local":  tags built from business + city, which any client can have

An account found under several tags ranks above one found under one.

Cost: ~11 tags x 25 posts x $0.0026 ≈ $0.72.
"""

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import CLIENT, ROOT, apify_run, clean, load, save  # noqa: E402

from pipeline.scan import _is_branded  # noqa: E402

HERE = Path(__file__).resolve().parent
POSTS_PER_TAG = 25
CLIENT_TAGS = 8

TRADE = re.compile(r"jewel|diamond|gold|solitaire|silver|necklace|bridal")
# A bare trade word is a global firehose — #jewellery is tens of millions of
# posts from every country. Only compound tags are specific enough to use.
TOO_BROAD = {"jewellery", "jewelry", "diamond", "diamonds", "gold", "silver",
             "gifts", "festival", "lightweight"}

posts = load(ROOT / "0_client" / "posts.json")
used = Counter(t.lower() for p in posts for t in (p.get("hashtags") or []))

client_tags = [t for t, _ in used.most_common()
               if TRADE.search(t) and t not in TOO_BROAD
               and not _is_branded(t, [CLIENT["handle"]])][:CLIENT_TAGS]

place = CLIENT["place"].lower().replace(" ", "")
local_tags = [f"{place}jewellery", f"{place}jewellers", f"jewellersin{place}"]
local_tags = [t for t in local_tags if t not in client_tags]

tags = {t: "client" for t in client_tags} | {t: "local" for t in local_tags}
print("tags:", tags)

rows = apify_run("apify/instagram-hashtag-scraper",
                 {"hashtags": list(tags), "resultsType": "posts",
                  "resultsLimit": POSTS_PER_TAG},
                 cap_usd=1.0, label="hashtags")
save(HERE / "raw.json", rows)

# Which tag a row came from: the actor marks it in different fields depending
# on version, so fall back to the post's own hashtags.
def tags_of(r: dict) -> set[str]:
    src = (r.get("inputUrl") or r.get("query") or r.get("hashtag") or "").lower()
    hit = {t for t in tags if t in src}
    if hit:
        return hit
    own = {x.lower() for x in r.get("hashtags") or []}
    return {t for t in tags if t in own}

by_owner: dict[str, set[str]] = defaultdict(set)
post_count: Counter = Counter()
per_tag_owners: dict[str, set[str]] = defaultdict(set)
for r in rows:
    owner = clean(r.get("ownerUsername"))
    if not owner or owner == CLIENT["handle"]:
        continue
    for t in tags_of(r):
        by_owner[owner].add(t)
        per_tag_owners[t].add(owner)
    post_count[owner] += 1

ranked = sorted(by_owner, key=lambda h: (-len(by_owner[h]), -post_count[h]))
cands = [{"handle": h, "why": f"{post_count[h]} posts under "
          + ", ".join(f"#{t} ({tags[t]})" for t in sorted(by_owner[h]))}
         for h in ranked]
save(HERE / "candidates.json", cands)
save(HERE / "per_tag.json", {t: {"source": tags[t],
                                 "owners": sorted(per_tag_owners[t])}
                             for t in tags})

print(f"\n{len(rows)} posts, {len(ranked)} distinct accounts")
for t in tags:
    print(f"  #{t} ({tags[t]}): {len(per_tag_owners[t])} accounts")
print("top 20:")
for c in cands[:20]:
    print(f"  @{c['handle']}: {c['why']}")
