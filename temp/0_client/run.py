"""Client profile and recent posts — the input the methods share.

Also records `relatedProfiles` as the baseline: what the dashboard's current
"Find competitors" method (depth 1) would start from.

Cost: 1 profile + 30 posts ≈ $0.08.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import CLIENT, apify_run, clean, save  # noqa: E402

HERE = Path(__file__).resolve().parent
h = CLIENT["handle"]

prof = apify_run("apify/instagram-profile-scraper",
                 {"usernames": [h], "resultsLimit": 1}, 0.05, "client-profile")
posts = apify_run("apify/instagram-scraper",
                  {"directUrls": [f"https://www.instagram.com/{h}/"],
                   "resultsType": "posts", "resultsLimit": 30}, 0.15, "client-posts")

save(HERE / "profile.json", prof)
save(HERE / "posts.json", posts)

p = prof[0] if prof else {}
related = [clean(r.get("username")) for r in p.get("relatedProfiles") or []
           if r.get("username")]
save(HERE / "baseline_candidates.json",
     [{"handle": r, "why": "Instagram 'suggested for you'"} for r in related])

print(f"\n@{h}: {p.get('followersCount')} followers, "
      f"category={p.get('businessCategoryName')!r}")
print(f"bio: {p.get('biography')!r}")
print(f"external url: {p.get('externalUrl')}")
print(f"relatedProfiles: {len(related)} -> {related[:15]}")
print(f"posts fetched: {len(posts)}, oldest {posts[-1].get('timestamp') if posts else '-'}")
