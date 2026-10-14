#!/usr/bin/env python3
"""Show what fields Apify actually returned, so a missing value can be found
rather than guessed at.

    python inspect_scan.py data/competitors/davanam_jewellers_scan_20260909.json
"""
import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    files = sorted(Path("data/competitors").glob("*_scan_*.json"))
    if not files:
        print("Give a scan file, or run report.py --scan first.")
        sys.exit(1)
    path = files[-1]
else:
    path = Path(sys.argv[1])

rows = json.loads(path.read_text(encoding="utf-8"))
print(f"{path}\n")

for acct in rows:
    posts = acct.get("posts") or []
    print(f"@{acct.get('handle')}  followers stored: {acct.get('followers')}")
    if not posts:
        print("  no posts\n")
        continue

    p = posts[0]
    # Anything that looks like it could carry a follower count.
    hits = {k: v for k, v in p.items()
            if "follow" in k.lower() or k in ("owner", "parentData", "latestPosts")}
    print(f"  keys on a post ({len(p)}): {', '.join(sorted(p)[:18])}…")
    print(f"  follower-ish keys: {hits if hits else 'none'}")
    print()