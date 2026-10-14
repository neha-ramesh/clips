#!/usr/bin/env python3
"""Posting gaps and time of day. Shows its working so it can be checked by eye.

    python check_timing.py                     # reads the latest saved scan
    python check_timing.py --scan davanam_jewellers abarantimelessjewellery
    python check_timing.py --file data/competitors/x_scan_20260909.json

WHY THIS IS SEPARATE

Two numbers in the report could not be verified: a "usual gap" between posts,
and a best time of day. Both were computed inside a larger function on a
truncated sample, and one of them measured gaps on a post list that had already
had some posts removed for an unrelated reason — which stretches every gap
around a missing post.

So this recomputes both from scratch, on their own, and prints every
intermediate value. Each consecutive pair of posts with the gap between them;
every post with the hour it went up and the band it landed in. If a summary
number looks wrong, the rows above it show why.

Reads a saved scan by default, so checking costs nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timedelta(hours=5, minutes=30)

# Named so a reader knows what "12-15" means without working it out.
BANDS = [
    (5, 9, "early morning"),
    (9, 12, "late morning"),
    (12, 15, "afternoon"),
    (15, 19, "evening"),
    (19, 24, "night"),
    (0, 5, "small hours"),
]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def load_scan(path: Path) -> list[dict]:
    """A saved scan: [{handle, posts: [...]}, ...]."""
    return json.loads(path.read_text(encoding="utf-8"))


def latest_scan(folder: Path) -> Path | None:
    files = sorted(folder.glob("*_scan_*.json"))
    return files[-1] if files else None


def fetch_live(handles: list[str], limit: int, days: int) -> list[dict]:
    """Fetch fresh, using the verified scan module."""
    sys.path.insert(0, str(Path(__file__).parent))
    from pipeline.scan import scan

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    accounts = scan(os.getenv("APIFY_TOKEN", ""), handles, days=days, limit=limit)
    return [a.model_dump() for a in accounts]


# --------------------------------------------------------------------------- #
# Times
# --------------------------------------------------------------------------- #

def parse_time(raw: str):
    if not raw:
        return None
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def post_times(posts: list[dict]) -> list[datetime]:
    """Every post's publish time, oldest first.

    EVERY post, including ones whose like count is hidden. A post happened
    whether or not its likes are readable, and dropping it here would make the
    gap on either side of it look like one long silence.
    """
    times = [t for t in (parse_time(p.get("timestamp", "")) for p in posts) if t]
    times.sort()
    return times


def gaps_between(times: list[datetime]) -> list[float]:
    """Days between each post and the next."""
    return [(b - a).total_seconds() / 86400 for a, b in zip(times, times[1:])]


def ist_hour(t: datetime) -> int:
    return (t + IST).hour


def band_of(hour: int) -> str:
    for lo, hi, label in BANDS:
        if lo <= hour < hi:
            return label
    return "small hours"


# --------------------------------------------------------------------------- #
# Reporting, with the working shown
# --------------------------------------------------------------------------- #

def show_gaps(handle: str, posts: list[dict], quiet: bool) -> None:
    times = post_times(posts)
    if len(times) < 2:
        print(f"\n@{handle}: fewer than two posts, nothing to measure")
        return

    gaps = gaps_between(times)

    print(f"\n@{handle}  —  {len(times)} posts")
    if not quiet:
        print(f"  {'posted':<18}{'next post':<18}{'gap':>12}")
        print("  " + "-" * 48)
        for (a, b), g in zip(zip(times, times[1:]), gaps):
            g_str = f"{g * 24:.0f} hours" if g < 1 else f"{g:.1f} days"
            print(f"  {(a + IST).strftime('%d %b %H:%M'):<18}"
                  f"{(b + IST).strftime('%d %b %H:%M'):<18}{g_str:>12}")
        print("  " + "-" * 48)

    med = statistics.median(gaps)
    worst = max(gaps)
    when_worst = times[gaps.index(worst)]

    def fmt(d: float) -> str:
        if d < 1:
            return f"{d * 24:.0f} hours"
        if d < 2:
            return "about a day"
        return f"{d:.1f} days"

    print(f"  usual gap        : {fmt(med)}   (the middle of "
          f"{len(gaps)} gaps)")
    print(f"  longest silence  : {fmt(worst)}   (after "
          f"{(when_worst + IST).strftime('%d %b')})")
    print(f"  first to last    : {(times[-1] - times[0]).days} days")


def show_hours(accounts: list[dict], quiet: bool) -> None:
    rows = []
    for a in accounts:
        for p in a.get("posts", []):
            t = parse_time(p.get("timestamp", ""))
            likes = int(p.get("likesCount") or 0)
            if t and likes >= 0:      # hidden likes cannot be averaged
                rows.append((a.get("handle", "?"), t, ist_hour(t), likes))

    if not rows:
        print("\nNo posts with readable like counts.")
        return

    rows.sort(key=lambda r: r[1])
    handles = sorted({r[0] for r in rows})

    print(f"\n\nTIME OF DAY  —  {len(rows)} posts from {len(handles)} accounts")
    print(f"  {', '.join('@' + h for h in handles)}")
    print("  (posts with hidden like counts are left out, since they cannot be "
          "averaged)")

    if not quiet:
        print(f"\n  {'account':<26}{'posted (IST)':<18}{'band':<16}{'likes':>8}")
        print("  " + "-" * 68)
        for handle, t, hour, likes in rows:
            print(f"  {handle[:25]:<26}{(t + IST).strftime('%d %b %H:%M'):<18}"
                  f"{band_of(hour):<16}{likes:>8,}")
        print("  " + "-" * 68)

    order = [label for _, _, label in BANDS]

    # Pooling every account's likes into one band is the trap. Abaran gets
    # thousands a post and Davanam gets four, so a band's number mostly reports
    # WHICH ACCOUNT posted in it, not what hour did. A table showing "night:
    # 2,916 likes" next to "late morning: 14" is really saying "Abaran posts at
    # night", which is not a finding anyone can act on.
    grouped = defaultdict(list)
    who = defaultdict(set)
    for handle, _, hour, likes in rows:
        b = band_of(hour)
        grouped[b].append(likes)
        who[b].add(handle)

    print(f"\n  RAW, EVERY ACCOUNT POOLED TOGETHER")
    print(f"  {'band':<16}{'posts':>7}{'normal post':>14}{'accounts':>10}")
    print("  " + "-" * 47)
    for label in order:
        v = grouped.get(label)
        if not v:
            continue
        n_acc = len(who[label])
        warn = "  <- one account only" if n_acc == 1 else ""
        print(f"  {label:<16}{len(v):>7}{statistics.median(v):>13,.0f}"
              f"{n_acc:>10}{warn}")
    print("  A band fed by one account tells you when that account posts, "
          "nothing more.")

    # The comparable version: each post against its OWN account's usual. A post
    # at twice its account's norm counts the same whether the account gets
    # 4 likes or 4,000, which is the only way six accounts of wildly different
    # size can be put on one scale.
    usual: dict[str, float] = {}
    for handle in {r[0] for r in rows}:
        mine = [r[3] for r in rows if r[0] == handle]
        if mine:
            usual[handle] = statistics.median(mine) or 1

    rel = defaultdict(list)
    for handle, _, hour, likes in rows:
        rel[band_of(hour)].append(likes / usual[handle])

    print(f"\n  COMPARED AGAINST EACH ACCOUNT'S OWN USUAL")
    print(f"  {'band':<16}{'posts':>7}{'accounts':>10}{'vs their usual':>17}")
    print("  " + "-" * 51)
    trusted = []
    for label in order:
        v = rel.get(label)
        if not v:
            continue
        med = statistics.median(v)
        n_acc = len(who[label])
        mark = ""
        if len(v) < 5:
            mark = "   too few posts"
        elif n_acc < 2:
            mark = "   one account only"
        else:
            trusted.append((label, med, len(v), n_acc))
        print(f"  {label:<16}{len(v):>7}{n_acc:>10}{med:>16.2f}x{mark}")

    print("\n  1.00x means a normal post for that account. Above 1 means posts "
          "at that\n  hour beat their own account's usual.")

    print()
    if not trusted:
        print("  Nothing here is worth acting on yet. Every band either has "
              "under five\n  posts or comes from a single account. Collect a "
              "few more weeks.")
        return

    best = max(trusted, key=lambda x: x[1])
    worst = min(trusted, key=lambda x: x[1])
    if best[1] < 1.2 or best[1] / max(worst[1], 0.01) < 1.5:
        print(f"  No real time-of-day effect. The best band ({best[0]}, "
              f"{best[1]:.2f}x) is not\n  meaningfully ahead of the worst "
              f"({worst[0]}, {worst[1]:.2f}x). Post when it suits you.")
    else:
        print(f"  {best[0].capitalize()} is the best band: {best[1]:.2f}x an "
              f"account's usual, across\n  {best[3]} accounts and {best[2]} "
              f"posts. Worst is {worst[0]} at {worst[1]:.2f}x.")

    skipped = [l for l in order if l in rel
               and (len(rel[l]) < 5 or len(who[l]) < 2)]
    if skipped:
        print(f"  Left out: {', '.join(skipped)} — too few posts, or all from "
              f"one account.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, help="a saved scan JSON")
    ap.add_argument("--dir", default=os.getenv("COMPETITOR_DIR",
                                               "data/competitors"))
    ap.add_argument("--scan", nargs="*", metavar="HANDLE",
                    help="fetch fresh instead of reading a file (costs credits)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--quiet", action="store_true",
                    help="summaries only, without the rows they came from")
    args = ap.parse_args()

    if args.scan:
        accounts = fetch_live(args.scan, args.limit, args.days)
    else:
        path = args.file or latest_scan(Path(args.dir))
        if not path or not Path(path).exists():
            print(f"No scan found in {args.dir}. Run report.py --scan first, "
                  f"or pass --scan with handles.", file=sys.stderr)
            return 1
        print(f"reading {path}")
        accounts = load_scan(Path(path))

    print("\n" + "=" * 70)
    print("HOW OFTEN THEY POST")
    print("=" * 70)
    print("Gap = time from one post to the next. Every post counts, including "
          "ones\nwith hidden like counts — a post happened either way, and "
          "leaving it out\nwould merge the gaps on both sides into one false "
          "silence.")
    for a in accounts:
        if a.get("error"):
            print(f"\n@{a.get('handle')}: {a['error'][:80]}")
            continue
        show_gaps(a.get("handle", "?"), a.get("posts", []), args.quiet)

    print("\n" + "=" * 70)
    show_hours([a for a in accounts if not a.get("error")], args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())