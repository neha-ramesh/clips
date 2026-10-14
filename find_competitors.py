#!/usr/bin/env python3
"""Find who a client's competitors might be.

    python find_competitors.py davanam_jewellers --check
    python find_competitors.py davanam_jewellers --min 5000 --max 200000

A thin command line over `pipeline/discover.py`, which the Streamlit app uses
too — so a change to how suggestions are found happens in one place.

Run --check first. It is one billed result, and it tells you whether Instagram
returns suggestions for that account at all. It does not for every profile,
often not for smaller ones, and no amount of further spending fixes that.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipeline.discover import DiscoveryError, check, suggest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("client")
    ap.add_argument("--depth", type=int, default=2, choices=(1, 2),
                    help="1 = only who Instagram suggests beside the client. "
                         "2 = also who those accounts suggest.")
    ap.add_argument("--min", type=int, default=0,
                    help="ignore accounts below this many followers")
    ap.add_argument("--max", type=int, default=0,
                    help="ignore accounts above this many followers")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--check", action="store_true",
                    help="one lookup, to see whether suggestions exist at all")
    args = ap.parse_args()

    token = os.getenv("APIFY_TOKEN", "")
    if not token:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            token = os.getenv("APIFY_TOKEN", "")
        except ImportError:
            pass
    if not token:
        print("Set APIFY_TOKEN in .env or the environment.", file=sys.stderr)
        return 1

    seed = args.client.strip().lstrip("@")

    if args.check:
        print(f"looking up @{seed} — one billed result\n")
        followers, rel = check(token, seed)
        if not followers and not rel:
            print("Nothing came back. Check the handle.")
            return 1
        print(f"@{seed}  {followers:,} followers")
        print(f"  suggestions returned: {len(rel)}")
        if rel:
            print("  " + ", ".join("@" + h for h in rel[:10]))
            print("\nThis works. Run without --check to build a list.")
        else:
            reason = ("The account may be too small for Instagram to have "
                      "confident neighbours — but at this size that is "
                      "unlikely." if followers >= 5000 else
                      "Small accounts often have no suggestions — "
                      "Instagram's algorithm needs enough of an audience "
                      "to have neighbours to point at.")
            print(f"\nInstagram returned no suggestions for @{seed}.\n"
                  f"{reason}\n"
                  f"\nOther common reasons, in order of how often they turn "
                  f"out to be the real one:\n"
                  f"  - The owner has switched off 'Show suggested accounts "
                  f"on profile' in Instagram's privacy settings. Neither "
                  f"Apify nor any scraper can override that.\n"
                  f"  - The profile is private.\n"
                  f"\nWorkaround, which always works: start from a "
                  f"competitor the client can name off the top of their "
                  f"head, and use who Instagram suggests around THAT "
                  f"account:\n"
                  f"  python find_competitors.py THEIR_COMPETITOR")
        return 0

    print(f"finding accounts near @{seed}, depth {args.depth}")
    try:
        rows = suggest(token, seed, depth=args.depth, min_followers=args.min,
                       max_followers=args.max, top=args.top)
    except DiscoveryError as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        msg = str(e)
        if "hard limit" in msg or "usage" in msg.lower():
            print("Apify's monthly credit is spent.", file=sys.stderr)
        else:
            print(f"Failed: {e}", file=sys.stderr)
        return 1

    if not rows:
        print(f"\nInstagram returned no suggestions for @{seed}. Common "
              f"causes are a small audience, the account owner opting out "
              f"of 'suggested accounts on profile', or a private profile.\n"
              f"Workaround: start from a competitor the client can name "
              f"instead — Instagram will suggest similar accounts around "
              f"a competitor even when it suggests none around the "
              f"client:\n"
              f"  python find_competitors.py THEIR_COMPETITOR")
        return 0

    print(f"\n  {'account':<34}{'followers':>11}{'posts':>9}")
    print("  " + "-" * 54)
    for c in rows:
        print(f"  @{c.handle:<33}{c.followers:>11,}{c.posts:>9,}")

    print("\nPick from these yourself. Instagram is saying these accounts share "
          "an\naudience, which is a good start and not the same as being worth "
          "watching\n— an account can have fifty thousand followers and be "
          "effectively dead.")
    print("\nTo scan the ones you want:")
    print(f"  python report.py --client {seed} --against "
          + " ".join(c.handle for c in rows[:5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())