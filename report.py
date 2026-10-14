#!/usr/bin/env python3
"""Turn a scan into an HTML report.

    python report.py --client davanam --scan            # fetch, then build
    python report.py --client davanam                   # build from the last scan
    python report.py --client davanam --open

Three sections, all built on `pipeline/scan.py`, whose numbers were checked
against the real profile grids. The version this replaces computed its own
figures and got them wrong — 16 posts where the account showed 18.

EVERY NUMBER HERE IS A COUNT

Likes, comments, posts, days. No rates, no percentages of followers, nothing a
reader has to decode. Dividing by followers was tried and thrown out: it turned
an 88-follower account into a market leader at 68% and buried a competitor
pulling 2,000 likes a reel.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from pipeline.scan import (  # noqa: E402
    Account,
    brand_name,
    by_day,
    caption_of,
    kind_of,
    growth_between,
    hashtags,
    load_snapshots,
    rhythm_of,
    save_snapshot,
    scan,
    timing_bands,
    url_of,
)

CSS = """
:root{
  --ink:#12261F;      /* temple green, the structural colour */
  --gold:#8A6B1F;
  --kempu:#9E2B25;
  --paper:#FAF8F3;
  --rule:#D8D2C4;
  --quiet:#5C6660;
  --good:#2E7D5B;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
     font:16px/1.55 Georgia,'Iowan Old Style','Times New Roman',serif;
     font-variant-numeric:tabular-nums}
.wrap{max-width:60rem;margin:0 auto;padding:0 2rem 6rem}
header{background:var(--ink);color:var(--paper);padding:3.5rem 0 3rem;
       margin-bottom:2.5rem}
header .wrap{padding-bottom:0}
h1{font-size:2.1rem;font-weight:normal;letter-spacing:-.01em;margin:0 0 .4rem}
.sub{color:#B9C4BC;font-size:.95rem;margin:0}
h2{font-size:1.35rem;font-weight:normal;margin:3rem 0 .4rem;padding-bottom:.4rem;
   border-bottom:1px solid var(--rule)}
.note{color:var(--quiet);font-size:.9rem;max-width:46rem;margin:.4rem 0 1.3rem}

/* Cards. A table made the reader work out that 8 likes on 48,000 followers was
   bad; a card says so, and the colour lands before any number is read. */
.cards{display:grid;gap:.9rem;margin:1.3rem 0}
.card{border:1px solid var(--rule);border-left:4px solid var(--rule);
      border-radius:3px;padding:1.1rem 1.3rem;background:#FCFBF7}
.card.good{border-left-color:var(--good);background:#F5FAF7}
.card.bad{border-left-color:var(--kempu);background:#FDF6F5}
.card.mine{border-color:var(--ink);border-left-color:var(--ink);
           background:#F1EFE8}
.chead{display:flex;justify-content:space-between;align-items:baseline;
       gap:1rem;flex-wrap:wrap}
.cname{font-size:1.05rem}
.card.mine .cname{font-weight:600}
.cnum{font-size:1.55rem;text-align:right;line-height:1.1}
.cnum em{display:block;font-size:.7rem;font-style:normal;color:var(--quiet)}
.cbar{height:5px;background:rgba(216,210,196,.55);border-radius:3px;margin:.7rem 0}
.cbar span{display:block;height:100%;border-radius:3px;background:var(--ink)}
.card.good .cbar span{background:var(--good)}
.card.bad .cbar span{background:var(--kempu)}
.cverdict{margin:.5rem 0 .8rem;font-size:.95rem}
.cmeta{font-size:.82rem;color:var(--quiet);text-align:right}

/* One line per kind: how much of the feed it is, and what it earns. Both facts
   on the same row is the point — the gap between them is the finding. */
.kinds{margin:.6rem 0 0}
.krow{display:flex;align-items:center;gap:.7rem;margin:.32rem 0;font-size:.83rem}
.kname{width:4.8rem;color:var(--quiet)}
.kshare{width:6.5rem;color:var(--quiet);font-size:.78rem}
.ktrack{flex:1;height:.75rem;background:rgba(216,210,196,.5)}
.ktrack span{display:block;height:100%}
.klikes{width:4rem;text-align:right}
.mismatch{margin:.7rem 0 0;font-size:.85rem;color:var(--gold)}
.cstats{display:flex;flex-wrap:wrap;gap:.4rem 1.2rem;font-size:.8rem;
        color:var(--quiet)}

/* Which kind wins, per account */
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(19rem,1fr));
       gap:1.5rem 2.4rem;margin:1.3rem 0}
.facct h3{font-size:.92rem;font-weight:normal;margin:0 0 .5rem;color:var(--quiet)}
.facct.mine h3{color:var(--ink);font-weight:600}
.fbar{display:flex;align-items:center;gap:.6rem;margin:.3rem 0;font-size:.8rem}
.fname{width:4.6rem;color:var(--quiet)}
.ftrack{flex:1;height:.75rem;background:rgba(216,210,196,.5)}
.ftrack span{display:block;height:100%}
.fval{width:3.6rem;text-align:right}
.fnote{margin:.5rem 0 0;font-size:.8rem;color:var(--quiet)}

/* Biggest day */
/* A row of cards rather than six stacked blocks. These are a set to browse,
   not a ranking to read down, and side by side they take a fifth of the height.
   Scroll-snap so a swipe lands on a card rather than between two. */
.bigdays{display:flex;gap:.9rem;margin:1.3rem 0 .3rem;overflow-x:auto;
         scroll-snap-type:x mandatory;padding-bottom:.6rem;
         scrollbar-width:thin}
.bigday{flex:0 0 20rem;scroll-snap-align:start;border:1px solid var(--rule);
        border-radius:4px;padding:1rem 1.1rem;background:#FCFBF7}
.bigday.mine{border-color:var(--ink);background:#F1EFE8}
.bdhead{display:flex;justify-content:space-between;align-items:baseline;
        gap:.6rem}
.bdwho{font-size:.9rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bigday.mine .bdwho{font-weight:600}
.bdday{font-size:.75rem;color:var(--gold);white-space:nowrap}
.bdbig{font-size:1.9rem;line-height:1.1;margin:.5rem 0 .1rem}
.bdbig em{display:block;font-size:.68rem;font-style:normal;color:var(--quiet);
          letter-spacing:.02em}
.bdsub{font-size:.8rem;color:var(--quiet);margin-bottom:.7rem;
       padding-bottom:.7rem;border-bottom:1px solid var(--rule)}
.bdlist{margin:0;padding:0;list-style:none;font-size:.82rem}
.bdlist li{margin:.45rem 0}
.bdlist a{color:inherit;text-decoration:none;display:block}
.bdlist a:hover .bdcap{color:var(--ink)}
.bdlist b{font-size:.95rem}
.bdk{color:var(--quiet);font-size:.72rem;margin-left:.35rem}
.bdcap{display:block;color:var(--quiet);line-height:1.35;margin-top:.1rem}
.scrollhint{font-size:.75rem;color:var(--quiet);margin:0 0 1.6rem}
@media print{.bigdays{overflow:visible;flex-wrap:wrap}
             .scrollhint{display:none}}

.hours{display:flex;gap:3px;margin:1.2rem 0 .4rem;align-items:flex-end}
.hours>div{flex:1;text-align:center;font-size:.72rem;color:var(--quiet)}
.hours .h{height:64px;display:flex;align-items:flex-end;margin-bottom:.4rem}
.hours .h span{width:100%;background:var(--ink);opacity:.8;min-height:2px;
               border-radius:2px 2px 0 0}
.hours b{color:var(--ink);font-weight:normal;font-size:.78rem}
.hours .thin .h span{opacity:.22;background:repeating-linear-gradient(
  45deg,var(--ink),var(--ink) 3px,transparent 3px,transparent 6px)}
.hours .thin{color:#9AA39D}
.hours .cav{font-size:.68rem;color:#9AA39D}
.hours .thin .cav{color:var(--kempu)}
.lonely{margin:1.4rem 0;padding:.9rem 1.1rem;background:#F5FAF7;
        border-left:3px solid var(--good);font-size:.93rem;max-width:46rem}
.verdict{margin:1rem 0 1.4rem;padding-left:1rem;border-left:3px solid var(--gold);
         font-size:.98rem;max-width:46rem}

table{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.9rem}
th{text-align:right;font-weight:normal;color:var(--quiet);font-size:.78rem;
   padding:0 0 .5rem;border-bottom:1px solid var(--rule)}
th:first-child{text-align:left}
td{padding:.55rem 0;border-bottom:1px solid rgba(216,210,196,.5);text-align:right}
td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
tr.dim td{color:#9AA39D}
tr.mine td{font-weight:600}

.part{margin:3.5rem 0 1.6rem;padding-top:1.6rem;border-top:2px solid var(--ink)}
.part span{font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;
           color:var(--gold)}
.part .ph{font-size:1.6rem;margin:.3rem 0 0;border:0;padding:0}

.patterns{max-width:47rem;padding-left:1.1rem}
.patterns li{margin:.9rem 0}
.patterns .ev{display:block;color:var(--quiet);font-size:.88rem;margin-top:.2rem}

.recs{display:grid;gap:1rem;margin:1.3rem 0}
.rec{display:grid;grid-template-columns:2rem 1fr;gap:1rem;border:1px solid
     var(--rule);border-radius:3px;padding:1.1rem 1.2rem;background:#FCFBF7}
.rnum{font-size:1.25rem;color:var(--gold);line-height:1}
.rec h3{font-size:1.02rem;font-weight:normal;margin:0 0 .3rem}
.rwhy{margin:0 0 .65rem;color:#33443C;font-size:.92rem}
.proof{background:#F1F6F2;border-left:3px solid var(--good);padding:.5rem .8rem;
       font-size:.87rem;border-radius:2px}
.proof.local{background:#FBF7EE;border-left-color:var(--gold)}
.plabel{display:block;font-size:.7rem;letter-spacing:.04em;color:var(--good);
        text-transform:uppercase;margin-bottom:.15rem}
.proof.local .plabel{color:var(--gold)}
.effort{margin-top:.45rem;font-size:.8rem;color:var(--quiet)}

/* What was supplied about the client, as against what was measured. */
.ctx{display:flex;flex-wrap:wrap;gap:.4rem 2.2rem;margin:0 0 2rem;
     padding:.9rem 1.1rem;background:#F2EFE7;border-radius:3px;
     font-size:.85rem}
.ctx div{display:flex;gap:.5rem}
.ctx dt{color:var(--quiet)}
.ctx dt::after{content:":"}
.ctx dd{margin:0}

footer{margin-top:4rem;padding-top:1.2rem;border-top:1px solid var(--rule);
       color:var(--quiet);font-size:.85rem}
@media print{header{background:none;color:var(--ink);
                    border-bottom:2px solid var(--ink)}
             .sub{color:var(--quiet)} body{font-size:11pt}}
@media (max-width:40rem){.wrap{padding:0 1.2rem 4rem}h1{font-size:1.6rem}}
"""


def esc(s: str) -> str:
    return html.escape(" ".join((s or "").split()))


def day_label(iso: str, month_fmt: str = "%B") -> str:
    """'3 September' without platform-specific format codes.

    strftime('%-d') is glibc only and raises on Windows; '%#d' is the Windows
    spelling. Building the string avoids caring which is running.
    """
    try:
        d = datetime.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d.day} {d.strftime(month_fmt)}"


# --------------------------------------------------------------------------- #
# 1. Who is actually being seen
# --------------------------------------------------------------------------- #

def _verdict(a: Account, best: float) -> tuple[str, str]:
    """One plain sentence about this account, and a colour.

    The "almost nobody sees this" test looks at the account's BEST kind of post,
    not its overall median. An account whose reels get 288 likes while its
    photos get 12 has a median of 14 and is not dead — it is posting the wrong
    things, which is a completely different problem and a much better one to
    have. Judging on the median called that account invisible while the same
    card showed a 288 sitting next to it.
    """
    mix = a.mix
    moving = mix.get("reel", 0) + mix.get("carousel", 0)
    # The best KIND's normal post — still a middle value, not a maximum. Naming
    # it a ceiling produced "nothing they post gets past 8 likes" for an account
    # whose best post got 68, which is simply false. A median says what a normal
    # post gets and nothing at all about the best one.
    best_kind_typical = max(a.likes_by_kind.values()) if a.likes_by_kind else 0

    if not a.posts:
        return "Posted nothing in this period.", "bad"

    if a.typical_likes >= best * 0.6:
        return (f"The one to beat. {moving * 100:.0f} out of every 100 posts "
                f"is a reel or a carousel.", "good")

    if best_kind_typical <= max(20, best * 0.03):
        return (f"Almost nobody sees this account. {a.followers:,} followers, "
                f"and a normal post gets {a.typical_likes:,.0f} likes. "
                f"{mix.get('photo', 0) * 100:.0f} out of every 100 posts is a "
                f"still photo.", "bad")

    # Their best kind works; the rest of the feed drags the middle down.
    if a.typical_likes <= best_kind_typical * 0.25:
        kinds = {"reel": "reels", "carousel": "carousels", "photo": "photos"}
        top = max(a.likes_by_kind, key=lambda k: a.likes_by_kind[k])
        return (f"Their {kinds[top]} work &mdash; a normal one gets "
                f"{best_kind_typical:,.0f} likes &mdash; but across the whole "
                f"feed a normal post gets only {a.typical_likes:,.0f}. The rest "
                f"is holding them back.", "")

    return "", ""


def section_seen(accounts: list[Account], client: str) -> str:
    """One block per account: how much of each kind they post, and what each
    kind earns them.

    This used to be two sections. The first gave a single "likes on a normal
    post" figure and the share of each format; the second gave likes per format
    on its own. But the single figure is just a blend of the three underneath
    it, and the format shares were printed twice — so a reader compared numbers
    that were saying the same thing in different words.

    Now each format gets one line carrying both facts: how much of the feed it
    is, and what it earns. Reading across shows whether an account is putting
    its effort into the thing that works. Abaran posting 62% reels while their
    carousels earn more is visible in a glance; across two sections it was not.
    """
    ok = [a for a in accounts if not a.error and a.posts]
    if not ok:
        return "<p class='note'>Nothing was fetched successfully.</p>"
    ok.sort(key=lambda a: a.typical_likes, reverse=True)
    best = ok[0].typical_likes or 1
    days = ok[0].days

    # One scale for every account, so the bars compare across the page and not
    # just within a card.
    peak = max((max(a.likes_by_kind.values()) for a in ok
                if a.likes_by_kind), default=1) or 1

    names = {"reel": "reels", "carousel": "carousels", "photo": "photos"}
    colours = {"reel": "var(--ink)", "carousel": "var(--gold)",
               "photo": "#C9C0AC"}

    cards = []
    for a in ok:
        line, cls = _verdict(a, best)
        mine = a.handle.lower() == (client or "").lower()
        mix = a.mix

        # Best-earning kind first. Whether that is also the kind they post most
        # is the question this section exists to answer.
        order = sorted(a.likes_by_kind.items(), key=lambda x: -x[1])
        lines = "".join(
            f'<div class="krow">'
            f'<span class="kname">{names[k]}</span>'
            f'<span class="kshare">{mix.get(k, 0) * 100:.0f}% of posts</span>'
            f'<span class="ktrack"><span style="width:'
            f'{max(1, v / peak * 100):.0f}%;background:{colours[k]}"></span></span>'
            f'<span class="klikes">{v:,.0f}</span>'
            f'</div>'
            for k, v in order
        )

        verdict = f'<p class="cverdict">{line}</p>' if line else ""
        best_k = order[0][0] if order else None
        most_k = max(mix, key=lambda k: mix[k]) if mix else None
        mismatch = ""
        if best_k and most_k and best_k != most_k and mix.get(most_k, 0) > .4:
            mismatch = (f'<p class="mismatch">Most of what they post is '
                        f'{names[most_k]}, but their {names[best_k]} earn more.</p>')

        cards.append(f"""
<div class="card {cls}{' mine' if mine else ''}">
  <div class="chead">
    <span class="cname">@{esc(a.handle)}{' &mdash; your client' if mine else ''}</span>
    <span class="cmeta">{a.followers:,} followers &nbsp;&middot;&nbsp;
      {a.typical_comments:,.0f} comments on a normal post &nbsp;&middot;&nbsp;
      best post {a.best_likes:,}</span>
  </div>
  {verdict}
  <div class="kinds">{lines}</div>
  {mismatch}
</div>""")

    return f"""
<div class="part"><span>Part one</span>
  <h2 class="ph">What the competition is doing</h2></div>
<h2>What they post, and what it earns them</h2>
<p class="note">The same <strong>{days} days</strong> for every account. Likes
on a <em>normal</em> post of each kind &mdash; the middle one, so half did
better and half did worse.</p>
<div class="cards">{''.join(cards)}</div>
"""


# --------------------------------------------------------------------------- #
# 3. Each competitor's biggest day
# --------------------------------------------------------------------------- #

def section_big_days(accounts: list[Account], client: str,
                     max_posts: int = 3) -> str:
    """Their best day, and the actual posts on it.

    An earlier version showed one account's daily totals and called it a
    festival ramp. Nothing in the data says a date is a festival, so that was a
    guess presented as a fact. This says only what is verifiable and lets the
    reader notice for themselves that the good days are Janmashtami and
    Varamahalakshmi.
    """
    blocks = []
    for a in sorted(accounts, key=lambda x: -x.typical_likes):
        if a.error or len(a.posts) < 3:
            continue
        days = by_day(a.posts)
        if len(days) < 2:
            continue

        def total(d: str) -> int:
            return sum(max(0, int(p.get("likesCount") or 0))
                       + int(p.get("commentsCount") or 0) for p in days[d])

        best = max(days, key=total)
        rest = [d for d in days if d != best]
        normal = sorted(total(d) for d in rest)[len(rest) // 2] if rest else 0

        posts = sorted(days[best],
                       key=lambda p: -int(p.get("likesCount") or 0))[:max_posts]
        items = "".join(
            f'<li><a href="{esc(url_of(p))}">'
            f'<b>{max(0, int(p.get("likesCount") or 0)):,}</b> '
            f'<span class="bdk">{kind_of(p)}</span>'
            f'<span class="bdcap">{esc(caption_of(p))[:64]}'
            f'{"&hellip;" if len(caption_of(p)) > 64 else ""}</span></a></li>'
            for p in posts
        )
        # "1 times a normal day" reads as a bug. Below 1.5x there is nothing
        # to say — their best day was an ordinary one.
        ratio = total(best) / normal if normal else 0
        mult = f" &mdash; {ratio:.0f}&times; a normal day" if ratio >= 1.5 else ""
        mine = a.handle.lower() == (client or "").lower()

        blocks.append(f"""
<div class="bigday{' mine' if mine else ''}">
  <div class="bdhead">
    <span class="bdwho">@{esc(a.handle)}</span>
    <span class="bdday">{day_label(best)}</span>
  </div>
  <div class="bdbig">{total(best):,}<em>likes and comments</em></div>
  <div class="bdsub">{len(days[best])} post{'s' if len(days[best]) != 1 else ''}
     in one day{mult}</div>
  <ul class="bdlist">{items}</ul>
</div>""")

    if not blocks:
        return ""
    return f"""
<h2>Each competitor's biggest day, and exactly what they posted</h2>
<p class="note">Their best day, and what went up on it.</p>
<div class="bigdays">{''.join(blocks)}</div>
<p class="scrollhint">Scroll sideways for the rest &rarr;</p>
"""


# --------------------------------------------------------------------------- #
# 4. What time the good posts went out
# --------------------------------------------------------------------------- #

def section_timing(accounts: list[Account]) -> str:
    """Time of day, in as few words as possible.

    Two things went wrong in the version before this.

    The chart plotted every band, so the tallest bar was a band with nine posts
    from one account, while the sentence underneath named a different band as
    the winner. A reader who looks at the picture and not the paragraph — which
    is most of them — got the opposite of the finding. Only bands with enough
    behind them are plotted now.

    And the interesting thing was buried in a grey table row: one account posts
    at an hour nobody else does, and that account is also the biggest. That is
    worth saying out loud as something to test, rather than hiding as a
    footnote.
    """
    bands = timing_bands(accounts)
    if not bands:
        return ""

    good = [b for b in bands if b.trusted]
    if not good:
        return """
<h2>What time to post</h2>
<p class="note">Not enough posts yet to say.</p>
"""

    best = max(good, key=lambda b: b.vs_usual)
    worst = min(good, key=lambda b: b.vs_usual)
    real = best.vs_usual >= 1.2 and best.vs_usual / max(worst.vs_usual, .01) >= 1.5

    if real:
        headline = (f"<strong>{best.label.capitalize()} works best</strong> "
                    f"&mdash; {best.vs_usual:.1f}&times; a normal post. "
                    f"{worst.label.capitalize()} is worst.")
    else:
        headline = "<strong>The hour does not seem to matter.</strong>"

    # Every part of the day is plotted, including the ones not solid enough to
    # draw a conclusion from — leaving a band off the chart hides that anything
    # happens at that hour at all.
    #
    # The earlier mistake was different: an unverified band was drawn exactly
    # like the rest, so the tallest bar on the page was nine posts from one
    # account while the sentence named a different winner. Marking it on the bar
    # fixes that without hiding it.
    chart = ""
    if len(bands) >= 2:
        peak = max(b.vs_usual for b in bands) or 1
        bars = []
        for b in bands:
            h = max(3, int(b.vs_usual / peak * 62))
            if b.trusted:
                caveat = f"{b.posts} posts"
                cls = ""
            elif b.accounts == 1:
                caveat = f"only @{esc(b.who[0])[:14]}"
                cls = ' class="thin"'
            else:
                caveat = f"only {b.posts} posts"
                cls = ' class="thin"'
            bars.append(
                f'<div{cls}><div class="h"><span style="height:{h}px"></span>'
                f'</div><b>{b.label}</b><br>{b.span}<br>{b.vs_usual:.1f}&times;'
                f'<br><span class="cav">{caveat}</span></div>'
            )
        chart = f'<div class="hours">{"".join(bars)}</div>'
        chart += ('<p class="note">Indian time. 1.0&times; is a normal post for '
                  'that account. Faded bars are one account only, or too few '
                  'posts.</p>')

    # The observation worth making: an hour only one account is trying, when
    # that account is the strongest one here.
    lonely = ""
    # The most substantial solo band, not merely the earliest in the day.
    solo = sorted([b for b in bands if b.accounts == 1 and b.posts >= 3],
                  key=lambda b: -b.posts)
    if solo:
        top = max((a for a in accounts if not a.error and a.posts),
                  key=lambda a: a.typical_likes, default=None)
        for b in solo:
            owner = b.who[0]
            if top and owner.lower() == top.handle.lower():
                lonely = (
                    f'<p class="lonely"><strong>Worth a test.</strong> '
                    f'@{esc(owner)} is the only account posting in the '
                    f'{b.label}, and the one getting the most attention. '
                    f'{b.posts} posts is too few to prove the hour is why, but '
                    f'nobody else is trying it.</p>')
                break
        else:
            b = solo[0]
            lonely = (f'<p class="lonely">@{esc(b.who[0])} is the only account '
                      f'posting in the {b.label}. Too few posts to say whether '
                      f'that helps them.</p>')

    return f"""
<h2>What time to post</h2>
<p class="verdict">{headline}</p>
{chart}
{lonely}
"""


# --------------------------------------------------------------------------- #
# 5. How often they post
# --------------------------------------------------------------------------- #

def section_rhythm(accounts: list[Account], client: str) -> str:
    rows = []
    for a in accounts:
        if a.error:
            continue
        r = rhythm_of(a)
        if r:
            rows.append((a, r))
    if not rows:
        return ""
    rows.sort(key=lambda x: x[1].usual_gap_days)

    def fmt(d: float) -> str:
        """A gap, said the way a person would.

        Rounding hours to whole numbers produced "0 hours" for accounts that
        post several times an hour, and "1 hours" for the rest.
        """
        h = d * 24
        if h < 1:
            return "minutes apart"
        if round(h) == 1:
            return "about an hour"
        if d < 1:
            return f"{h:.0f} hours"
        if d < 2:
            return "about a day"
        return f"{d:.1f} days"

    def count_cell(a, r) -> str:
        """Posts, with the two things that qualify the number.

        This lives here rather than on the cards above. A card answers who is
        being seen, which is about likes; how much someone posts belongs beside
        the gaps that give it meaning. Having it in both places asked the reader
        to compare two numbers saying the same thing.
        """
        # The window, not the account's own first-to-last span. Showing
        # "6 in 20 days" beside "32 in 24 days" made two counts look comparable
        # when they covered different stretches — and the window really is the
        # same 30 days for everyone, which is the whole point of fixing it.
        txt = f"{r.posts} in {a.days} days"
        if a.truncated:
            txt = "at least " + txt
        if a.hidden:
            txt += f'<br><span class="cav">{a.hidden} hide their likes</span>'
        return txt

    body = "".join(
        f"<tr{' class="mine"' if a.handle.lower() == (client or '').lower() else ''}>"
        f"<td>@{esc(a.handle)}</td><td>{fmt(r.usual_gap_days)}</td>"
        f"<td>{fmt(r.longest_gap_days)}</td>"
        f"<td>{count_cell(a, r)}</td></tr>"
        for a, r in rows
    )
    return f"""
<h2>How often they post, and when they go quiet</h2>
<p class="note"><strong>Usual gap</strong> is the time between posts, most of
the time. <strong>Longest silence</strong> is the biggest stretch with nothing
at all.</p>
<table><thead><tr><th>Account</th><th>Usual gap</th><th>Longest silence</th>
<th>Posts</th></tr></thead><tbody>{body}</tbody></table>
"""


# --------------------------------------------------------------------------- #
# 6. Follower growth
# --------------------------------------------------------------------------- #

def section_growth(out_dir: Path, client: str) -> str:
    """Follower change between the first and latest stored scan.

    Only exists for weeks the scan ran. Instagram keeps no history you can ask
    for, so this is built from what was written down at the time.
    """
    rows = growth_between(out_dir, client)
    if not rows:
        return """
<h2>Follower growth</h2>
<p class="note">Needs a second scan. Run this weekly and the comparison
appears here.</p>
"""

    period = rows[0]
    real = [g for g in rows if g.meaningful]

    body = "".join(
        f'<tr class="{"mine" if g.handle.lower() == (client or "").lower() else ""}'
        f'{" dim" if not g.meaningful else ""}">'
        f"<td>@{esc(g.handle)}</td><td>{g.was:,}</td><td>{g.now:,}</td>"
        f"<td>{g.change:+,}</td>"
        f"<td>{'' if not g.meaningful else f'{g.pct:+.1f}%'}</td>"
        f"<td>{'' if g.meaningful else 'flat'}</td></tr>"
        for g in rows
    )

    if real:
        up = [g for g in real if g.change > 0]
        down = [g for g in real if g.change < 0]
        bits = []
        if up:
            b = max(up, key=lambda g: g.pct)
            bits.append(f"@{esc(b.handle)} grew fastest, "
                        f"{b.change:+,} followers")
        if down:
            w = min(down, key=lambda g: g.pct)
            bits.append(f"@{esc(w.handle)} lost {abs(w.change):,}")
        summary = f'<p class="verdict">{". ".join(bits)}.</p>' if bits else ""
    else:
        summary = ('<p class="verdict">Nobody moved much. Every change here is '
                   'small enough to be Instagram\'s own count wobbling rather '
                   'than real growth.</p>')

    return f"""
<h2>Follower growth</h2>
<p class="note">{day_label(period.from_date)} to {day_label(period.to_date)},
{period.days} days. Changes under 0.15% are marked flat &mdash; that is inside
Instagram's own wobble.</p>
{summary}
<table><thead><tr><th>Account</th><th>Was</th><th>Now</th><th>Change</th>
<th>&nbsp;</th><th>&nbsp;</th></tr></thead><tbody>{body}</tbody></table>
"""


# --------------------------------------------------------------------------- #
# 7. Hashtags
# --------------------------------------------------------------------------- #

def section_hashtags(accounts: list[Account], client: str = "",
                     top: int = 12) -> str:
    """Which tags are worth copying, and which are somebody else's.

    Ranking tags by likes alone puts a competitor's own brand tag at the top,
    because their brand tag sits on their best posts. Using it would tag a
    competitor. And a festival tag looks unbeatable in the week of the festival
    and does nothing the rest of the year.

    So the tags are split by what they are, not by how they scored.
    """
    tags = hashtags(accounts)
    if not tags:
        return ""

    usable = [t for t in tags
              if not t.branded and not t.seasonal and t.accounts >= 2][:top]
    seasonal = [t for t in tags if t.seasonal and not t.branded][:6]

    out = ["<h2>Hashtags worth using</h2>"]

    if usable:
        rows = "".join(
            f"<tr><td>#{esc(t.label)}</td><td>{t.posts}</td>"
            f"<td>{t.accounts}</td><td>{t.typical_likes:,.0f}</td></tr>"
            for t in usable
        )
        out.append('<p class="note">More than one account uses these, all month.</p>')
        out.append('<table><thead><tr><th>Tag</th><th>Posts</th>'
                   '<th>Accounts</th><th>Likes on a normal post carrying it</th>'
                   '</tr></thead><tbody>' + rows + "</tbody></table>")
    else:
        out.append('<p class="note">No tag is shared across accounts. Nothing to copy.</p>')

    if seasonal:
        names = ", ".join(f"#{esc(t.label)}" for t in seasonal)
        best = max(seasonal, key=lambda t: t.typical_likes)
        out.append("<h2>Only around the date</h2>")
        out.append(
            f'<p class="note">{names} &mdash; every post carrying these went up '
            f'inside a few days of each other, which is what a festival tag '
            f'looks like. #{esc(best.label)} sat on posts getting '
            f'{best.typical_likes:,.0f} likes, but that was the week of the '
            f'festival. Using them now would reach nobody; using them on the '
            f'day is worth doing.</p>')

    # Branded tags. This was a "do not use these" list, which told the reader
    # something obvious and read as a telling-off. The interesting thing about a
    # competitor running #celebratewithabaran is not that you cannot copy it —
    # it is that they built one at all.
    #
    # It was passed to the ideas step for a while and got crowded out among ten
    # other suggestions. Computed here instead, so it always appears: the
    # observation is arithmetic, and only the client's own name has to be
    # filled in.
    branded = [t for t in tags if t.branded]
    if branded:
        by_owner: dict[str, list] = {}
        for t in branded:
            by_owner.setdefault(t.who[0], []).append(t)
        # The account running the most of them, with the biggest numbers.
        owner, theirs = max(by_owner.items(),
                            key=lambda kv: (len(kv[1]),
                                            max(t.typical_likes for t in kv[1])))
        theirs = sorted(theirs, key=lambda t: -t.typical_likes)[:4]
        best = theirs[0]
        names = ", ".join(f"#{esc(t.label)}" for t in theirs)
        name = brand_name(client) or "yourbrand"

        out.append("<h2>They have built their own tag. You could too.</h2>")
        out.append(
            f'<p class="note">@{esc(owner)} runs {names}. Not for being found '
            f'&mdash; for collecting their work in one place. '
            f'#{esc(best.label)} sits on {best.posts} posts where a normal one '
            f'gets {best.typical_likes:,.0f} likes.</p>')
        out.append(
            f'<div class="proof local"><span class="plabel">Worth doing</span>'
            f'Build one. <strong>#celebratewith{esc(name)}</strong>, on every '
            f'post, with a reason to use it back &mdash; a giveaway, customer '
            f'photos, a festival series.</div>')

    return "".join(out)


# --------------------------------------------------------------------------- #
# 8. What the posts show, and what to make
# --------------------------------------------------------------------------- #

def section_patterns(ideas) -> str:
    if not ideas or not ideas.patterns:
        return ""
    items = "".join(
        f'<li><strong>{esc(p.what)}</strong>'
        f'<span class="ev">{esc(p.evidence)}</span></li>'
        for p in ideas.patterns
    )
    return f"""
<div class="part"><span>Part two</span>
  <h2 class="ph">What the winners have in common</h2></div>
<p class="note">From the posts that beat an account's own normal, against the
ones that fell short.</p>
<ul class="patterns">{items}</ul>
"""


def section_ideas(ideas) -> str:
    if not ideas or not ideas.ideas:
        return """
<div class="part"><span>Part three</span>
  <h2 class="ph">What to make</h2></div>
<p class="note">Needs an LLM key. Set <code>ANTHROPIC_API_KEY</code>.</p>
"""

    def strength(i) -> int:
        """The biggest number in the proof, for ordering.

        Eight ideas at equal weight tells a reader nothing about where to
        start. Leading with the one carrying 14,572 likes behind it, rather
        than whichever the model happened to write first, is the difference
        between a list and a recommendation.
        """
        nums = [int(n.replace(",", ""))
                for n in re.findall(r"[\d,]+", i.proof_number or "")
                if n.replace(",", "").isdigit()]
        return max(nums) if nums else 0

    proven = sorted([i for i in ideas.ideas if not i.local],
                    key=strength, reverse=True)
    local = [i for i in ideas.ideas if i.local]

    def card(i, n: int) -> str:
        proof = ""
        if i.proof_account and i.proof_number:
            proof = (f'<div class="proof"><span class="plabel">Worked for '
                     f'@{esc(i.proof_account)}</span>{esc(i.proof_number)}</div>')
        elif i.local:
            proof = ('<div class="proof local"><span class="plabel">Not from '
                     'the data</span>A local idea &mdash; nobody in this set has '
                     'tried it, so there is nothing to measure it against.</div>')
        effort = f'<div class="effort">{esc(i.effort)}</div>' if i.effort else ""
        return f"""
<div class="rec">
  <div class="rnum">{n}</div>
  <div>
    <h3>{esc(i.idea)}</h3>
    <p class="rwhy">{esc(i.goal)}</p>
    {proof}{effort}
  </div>
</div>"""

    out = [f'<div class="part"><span>Part three</span>'
           f'<h2 class="ph">What to make</h2></div>']
    if proven:
        out.append('<p class="note">Strongest evidence first. Start with '
                   'number one.</p>')
        out.append('<div class="recs">'
                   + "".join(card(i, n) for n, i in enumerate(proven, 1))
                   + "</div>")
    if local:
        out.append('<h2>Worth trying, but untested here</h2>')
        out.append('<p class="note">From knowing the place, not the posts. '
                   'Nobody in this set has tried them.</p>')
        out.append('<div class="recs">'
                   + "".join(card(i, n) for n, i in enumerate(local, len(proven) + 1))
                   + "</div>")
    return "".join(out)


# --------------------------------------------------------------------------- #

def build(accounts: list[Account], client: str, stamp: str,
          out_dir: Optional[Path] = None, ideas=None,
          context: Optional[dict] = None) -> str:
    ok = [a for a in accounts if not a.error]
    posts = sum(a.post_count for a in ok)
    pretty = client.replace("_", " ").replace("-", " ").title()
    try:
        d = datetime.strptime(stamp, "%Y%m%d")
        shown = f"{d.day} {d.strftime('%B %Y')}"
    except ValueError:
        shown = stamp

    # What the reader needs to know was fed in. The ideas below lean on the
    # business, the city and the language, none of which come from the data —
    # so saying what was supplied lets someone judge whether the ideas were
    # working from the right picture, and spot a blank field as the reason an
    # idea reads generic.
    ctx = ""
    if context and any(context.values()):
        rows = "".join(
            f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>"
            for k, v in context.items() if v
        )
        ctx = f'<dl class="ctx">{rows}</dl>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Competitors &mdash; {esc(pretty)}</title>
<style>{CSS}</style></head><body>
<header><div class="wrap">
  <h1>What the competition is getting away with</h1>
  <p class="sub">{esc(pretty)} &nbsp;&middot;&nbsp; {shown}
     &nbsp;&middot;&nbsp; {len(ok)} accounts, {posts} posts</p>
</div></header>
<div class="wrap">
{ctx}
{section_seen(accounts, client)}
{section_big_days(accounts, client)}
{section_timing(accounts)}
{section_rhythm(accounts, client)}
{section_growth(out_dir, client) if out_dir else ""}
{section_hashtags(accounts, client)}
{section_patterns(ideas)}
{section_ideas(ideas)}
<footer>Public Instagram data, read {shown}. &ldquo;A normal post&rdquo; is the
middle one &mdash; half did better, half did worse. Posts hiding their like
count are counted but left out of the like figures.</footer>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True,
                    help="the client's handle; also names the files")
    ap.add_argument("--against", nargs="*", default=[],
                    help="competitor handles. Omit to reuse the last scan.")
    ap.add_argument("--scan", action="store_true", help="fetch fresh data")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=40,
                    help="posts fetched per account; Apify bills per result")
    ap.add_argument("--dir", default=os.getenv("COMPETITOR_DIR",
                                               "data/competitors"))
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--no-ideas", action="store_true",
                    help="skip the written patterns and content ideas")
    ap.add_argument("--business", default="",
                    help="what the client sells, one line")
    ap.add_argument("--place", default="",
                    help="where their customers are, e.g. 'Bangalore'")
    ap.add_argument("--language", default="",
                    help="the language their audience uses, e.g. 'Kannada'")
    ap.add_argument("--notes", default="",
                    help="anything else worth knowing for the ideas")
    args = ap.parse_args()

    out_dir = Path(args.dir)

    if args.scan or args.against:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        handles = [args.client] + list(args.against)
        accounts = scan(os.getenv("APIFY_TOKEN", ""), handles,
                        days=args.days, limit=args.limit)
        path = save_snapshot(accounts, out_dir, args.client)
        print(f"  saved {path}")
        stamp = path.stem.rsplit("_", 1)[-1]
    else:
        snaps = load_snapshots(out_dir, args.client)
        if not snaps:
            print(f"No scan for '{args.client}'. Run with --scan and --against.",
                  file=sys.stderr)
            return 1
        stamp, accounts = snaps[-1]
        print(f"  using the scan from {stamp}")

    ideas = None
    if not args.no_ideas:
        from pipeline.ideas import suggest
        print("  reading the winners and losers...")
        ideas = suggest(accounts, args.client, business=args.business,
                        place=args.place, language=args.language,
                        notes=args.notes)

    path = out_dir / f"{args.client}_report_{stamp}.html"
    path.write_text(
        build(accounts, args.client, stamp, out_dir, ideas, {
            "Business": args.business,
            "Customers in": args.place,
            "Audience language": args.language,
            "Notes": args.notes,
        }),
        encoding="utf-8")
    print(f"  wrote {path}")
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())