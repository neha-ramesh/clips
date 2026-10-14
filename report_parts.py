"""The report sections added for the full audit. `report.py` assembles them.

Same rules as report.py: every number is a count, said the way a person would
say it; anything read by a model is labelled as such; a section with nothing
behind it is left out rather than padded.

The order follows the hand-written audits, which clients understood: the
business, where it stands today, whether anyone can find it, what the
competition does (and each competitor up close), Facebook and ads, then what to
make, the month's plan, how Conra AI helps, and the notes from the call.
"""

from __future__ import annotations

import html
import statistics
from datetime import datetime

from pipeline.habits import checklist
from pipeline.media import data_uri, has_thumb, post_key
from pipeline.offer import CONTACT
from pipeline.scan import Account, caption_of, kind_of, rhythm_of, url_of
from pipeline.visibility import rank_of
from pipeline.visual import FORMATS, by_format, graphic_reels

CSS = """
.thumbs{display:grid;grid-template-columns:repeat(auto-fill,minmax(8.5rem,1fr));
        gap:.7rem;margin:1rem 0 1.4rem}
.thumb{margin:0;font-size:.75rem;color:var(--quiet);line-height:1.3}
.thumb a{color:inherit;text-decoration:none}
.thumb img,.thumb .noimg{width:100%;aspect-ratio:4/5;object-fit:cover;
        border-radius:3px;border:1px solid var(--rule);display:block;
        background:#EEEAE0}
.thumb .noimg{display:flex;align-items:center;justify-content:center;
        font-size:.7rem;color:#9AA39D}
.thumb b{color:var(--ink);font-size:.85rem}
.thumb .fmt{display:block;color:var(--gold)}
.stats{display:flex;flex-wrap:wrap;gap:1rem 2.4rem;margin:1rem 0 1.2rem}
.stat{font-size:.8rem;color:var(--quiet)}
.stat b{display:block;font-size:1.6rem;font-weight:normal;color:var(--ink);
        line-height:1.1}
.ok{color:var(--good)} .no{color:var(--kempu)} .unk{color:#9AA39D}
.brief td:first-child{color:var(--quiet);width:13rem;vertical-align:top}
.brief td{text-align:left}
.lead{font-size:1.05rem;max-width:46rem;margin:.8rem 0 1.2rem}
.tears{display:grid;gap:1.2rem;margin:1.3rem 0}
.tear{border:1px solid var(--rule);border-radius:4px;padding:1.1rem 1.3rem;
      background:#FCFBF7}
.tear h3{font-size:1.05rem;font-weight:normal;margin:0}
.tear .ratio{font-size:.82rem;color:var(--gold);margin:.2rem 0 .6rem}
.tear dl{margin:.6rem 0 0;font-size:.9rem}
.tear dt{font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;
         color:var(--quiet);margin-top:.6rem}
.tear dd{margin:.1rem 0 0}
.tear .take{margin-top:.8rem;padding:.5rem .8rem;background:#F1F6F2;
            border-left:3px solid var(--good);font-size:.9rem}
.tear .thumbs{grid-template-columns:repeat(auto-fill,minmax(7rem,1fr))}
.quote{font-style:italic;color:#33443C}
.chips{display:flex;flex-wrap:wrap;gap:.35rem .5rem;margin:.4rem 0 1rem}
.chips span{border:1px solid var(--rule);border-radius:999px;padding:.12rem .6rem;
            font-size:.82rem;background:#FCFBF7}
.fits{display:grid;gap:.9rem;margin:1.2rem 0}
.fit{border:1px solid var(--rule);border-left:4px solid var(--gold);
     border-radius:3px;padding:.9rem 1.1rem;background:#FCFBF7}
.fit .ffind{font-size:.85rem;color:var(--quiet)}
.fit .ffeat{font-size:1rem;margin:.2rem 0}
.cta{margin:1.4rem 0;padding:1rem 1.2rem;background:var(--ink);color:var(--paper);
     border-radius:4px}
.cta a{color:#F3E3B5}
.notes{white-space:pre-wrap;background:#F2EFE7;padding:1rem 1.2rem;
       border-radius:3px;font-size:.92rem;max-width:46rem}
.exp{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;
     color:var(--kempu);margin-left:.5rem}
"""


def esc(s) -> str:
    return html.escape(" ".join(str(s or "").split()))


def _day(iso: str) -> str:
    try:
        d = datetime.fromisoformat((iso or "")[:10])
    except ValueError:
        return iso or ""
    return f"{d.day} {d.strftime('%b')}"


def _is(a: Account, client: str) -> bool:
    return a.handle.lower() == (client or "").lower()


def _likes(p: dict) -> str:
    n = int(p.get("likesCount") or 0)
    return "likes hidden" if n < 0 else f"{n:,} likes"


def _thumb(out_dir, p: dict, look=None, note: str = "") -> str:
    tag = look.posts.get(post_key(p)) if look else None
    fmt = f'<span class="fmt">{esc(FORMATS[tag.format])}</span>' if tag else ""
    src = data_uri(out_dir, p) if out_dir and has_thumb(out_dir, p) else ""
    img = (f'<img src="{src}" alt="{esc(caption_of(p)[:80])}" loading="lazy">'
           if src else '<span class="noimg">no image saved</span>')
    secs = p.get("videoDuration")
    kind = kind_of(p) + (f" · {float(secs):.0f}s" if secs else "")
    return (f'<figure class="thumb"><a href="{esc(url_of(p))}">{img}</a>'
            f'<figcaption><b>{_likes(p)}</b> · {kind} · {_day(p.get("timestamp", ""))}'
            f'{fmt}{(" " + esc(note)) if note else ""}</figcaption></figure>')


def _any_thumb(out_dir, posts: list[dict]) -> bool:
    return bool(out_dir) and any(has_thumb(out_dir, p) for p in posts)


def _part(label: str, title: str) -> str:
    return (f'<div class="part"><span>{esc(label)}</span>'
            f'<h2 class="ph">{esc(title)}</h2></div>')


# --------------------------------------------------------------------------- #
# The business
# --------------------------------------------------------------------------- #

def section_brief(brief) -> str:
    if brief is None or not brief.rows():
        return ""
    rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>"
                   for k, v in brief.rows())
    vol = ""
    if brief.images_per_month or brief.reels_per_month:
        vol = (f"<tr><td>Agreed volume</td><td>{brief.images_per_month} images "
               f"and {brief.reels_per_month} reels a month</td></tr>")
    return (_part("Where things stand", "The business")
            + f'<table class="brief"><tbody>{rows}{vol}</tbody></table>')


# --------------------------------------------------------------------------- #
# Where the client stands today
# --------------------------------------------------------------------------- #

def section_now(accounts: list[Account], client: str, extras, out_dir) -> str:
    me = next((a for a in accounts if _is(a, client) and not a.error), None)
    if me is None:
        return ""
    look = extras.looks.get(me.handle.lower()) if extras else None
    fb = extras.fb_pages.get(me.handle.lower()) if extras else None
    habits = extras.habits(accounts).get(me.handle.lower()) if extras else None

    stats = [f'<div class="stat"><b>{me.followers:,}</b>Instagram followers</div>']
    if fb and fb.followers:
        stats.append(f'<div class="stat"><b>{fb.followers:,}</b>Facebook followers</div>')
    stats.append(f'<div class="stat"><b>{me.post_count}</b>Instagram posts in '
                 f'{me.days} days</div>')
    stats.append(f'<div class="stat"><b>{me.typical_likes:,.0f}</b>likes on a '
                 f'normal post</div>')
    stats.append(f'<div class="stat"><b>{me.best_likes:,}</b>likes on the best</div>')

    lead = ""
    if me.posts and me.followers:
        lead = (f'<p class="lead">A normal post gets <strong>{me.typical_likes:,.0f} '
                f'likes</strong>, from <strong>{me.followers:,} followers</strong>.')
        r = rhythm_of(me)
        if r and r.longest_gap_days >= 7:
            lead += f" The longest stretch with no post was {r.longest_gap_days:.0f} days."
        lead += "</p>"
    elif not me.posts:
        lead = f'<p class="lead">Nothing was posted in the last {me.days} days.</p>'

    recent = sorted(me.posts, key=lambda p: p.get("timestamp") or "", reverse=True)[:8]
    strip = ""
    if recent and _any_thumb(out_dir, recent):
        strip = ('<h2>The latest posts</h2><div class="thumbs">'
                 + "".join(_thumb(out_dir, p, look) for p in recent) + "</div>")
    elif recent:
        rows = "".join(f"<tr><td><a href='{esc(url_of(p))}'>{_day(p.get('timestamp', ''))}"
                       f"</a></td><td>{kind_of(p)}</td><td>{_likes(p)}</td></tr>"
                       for p in recent)
        strip = ("<h2>The latest posts</h2><table><thead><tr><th>Posted</th>"
                 "<th>Kind</th><th>Likes</th></tr></thead><tbody>" + rows
                 + "</tbody></table>")

    check = ""
    if habits:
        items = checklist(habits)
        if items:
            rows = "".join(
                f"<tr><td>{esc(name)}</td><td class='"
                f"{'ok' if ok else 'no' if ok is False else 'unk'}'>"
                f"{'Yes' if ok else 'Needs fixing' if ok is False else 'Unknown'}"
                f"</td><td>{esc(detail)}</td></tr>" for name, ok, detail in items)
            check = ("<h2>The profile, checked</h2><table><thead><tr><th>Item</th>"
                     "<th>&nbsp;</th><th>&nbsp;</th></tr></thead><tbody>"
                     + rows + "</tbody></table>")

    dm = ""
    c = extras.comments.get(me.handle.lower()) if extras else None
    if c and c.owner_replies:
        dm = (f'<p class="note">They replied to comments {c.owner_replies} times in '
              f'the sample read, {c.redirects} of them pointing the person to DM or '
              f'WhatsApp.</p>')

    return ("<h2>Where you stand today</h2>"
            + f'<div class="stats">{"".join(stats)}</div>{lead}{strip}{check}{dm}')


# --------------------------------------------------------------------------- #
# Can people find you
# --------------------------------------------------------------------------- #

def section_visibility(accounts: list[Account], client: str, extras) -> str:
    v = extras.visibility if extras else None
    habits = extras.habits(accounts) if extras else {}
    known = {a.handle.lower() for a in accounts}
    out = []

    if v and v.instagram:
        out.append("<h2>Can people find you on Instagram?</h2>")
        out.append('<p class="note">What Instagram\'s search returned for the '
                   'searches a customer would type. Results vary with who is '
                   'searching and where, so read this as "shows up near the top '
                   'or not", not an exact position.</p>')
        for term, handles in v.instagram.items():
            r = rank_of(client, handles)
            verdict = (f"you are <strong>#{r}</strong>" if r else
                       "<strong class='no'>you are not in the results</strong>")
            items = "".join(
                f"<li{' class=mine' if h == client.lower() else ''}>@{esc(h)}"
                f"{' &larr; you' if h == client.lower() else ' (a competitor here)' if h in known else ''}"
                f"</li>" for h in handles[:8])
            out.append(f'<p class="verdict">&ldquo;{esc(term)}&rdquo; &mdash; '
                       f'{verdict}.</p><ol class="note">{items}</ol>')

    if v and v.maps:
        out.append("<h2>And on Google Maps?</h2>")
        if v.client_place:
            cp = v.client_place
            reviews = [p.reviews for ps in v.maps.values() for p in ps[:10] if p.reviews]
            mid = statistics.median(reviews) if reviews else 0
            out.append(f'<p class="lead">Your listing: <strong>{cp.rating:.1f} stars '
                       f'from {cp.reviews:,} reviews</strong>. The places Google shows '
                       f'first have a middle of {mid:,.0f} reviews.</p>')
        else:
            out.append('<p class="lead no">Your Google listing did not come up at '
                       'all.</p>')
        for term, places in v.maps.items():
            rows = "".join(
                f"<tr{' class=mine' if p.handle.lower() == client.lower() else ''}>"
                f"<td>{p.rank}. {esc(p.title)}"
                f"{' &larr; you' if p.handle.lower() == client.lower() else ''}</td>"
                f"<td>{p.rating:.1f}</td><td>{p.reviews:,}</td></tr>"
                for p in places[:8])
            out.append(f'<p class="verdict">&ldquo;{esc(term)}&rdquo;</p>'
                       '<table><thead><tr><th>Place</th><th>Stars</th>'
                       f'<th>Reviews</th></tr></thead><tbody>{rows}</tbody></table>')

    if habits:
        rows = []
        for a in accounts:
            h = habits.get(a.handle.lower())
            if not h or not h.posts:
                continue
            langs = ", ".join(h.languages) or "&mdash;"
            rows.append(
                f"<tr{' class=mine' if _is(a, client) else ''}><td>@{esc(a.handle)}</td>"
                f"<td>{h.with_location} of {h.posts}</td>"
                f"<td>{h.with_hashtags} of {h.posts}</td><td>{esc(langs)}</td>"
                f"<td>{f'{h.reel_seconds:.0f}s' if h.reels else '&mdash;'}</td>"
                f"<td>{h.highlights if h.highlights is not None else '&mdash;'}</td></tr>")
        if rows:
            out.append("<h2>The small things that get a post found</h2>"
                       '<p class="note">Location tags and hashtags are how a post '
                       'reaches people who do not follow the account yet. '
                       'Languages are read from the script of the captions.</p>'
                       "<table><thead><tr><th>Account</th><th>Location tag</th>"
                       "<th>Hashtags</th><th>Caption languages</th><th>Typical reel</th>"
                       "<th>Highlights</th></tr></thead><tbody>"
                       + "".join(rows) + "</tbody></table>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# What kind of post earns what
# --------------------------------------------------------------------------- #

def section_formats(accounts: list[Account], client: str, extras) -> str:
    if not extras or not extras.looks:
        return ""
    peak = 1.0
    per = []
    for a in sorted(accounts, key=lambda x: -x.typical_likes):
        look = extras.looks.get(a.handle.lower())
        if a.error or not look or not look.posts:
            continue
        rows = by_format(a, look)
        if rows:
            peak = max(peak, max(r.typical_likes for r in rows))
            per.append((a, look, rows))
    if not per:
        return ""
    blocks = []
    for a, look, rows in per:
        bars = "".join(
            f'<div class="fbar"><span class="fname" style="width:12rem">'
            f'{esc(FORMATS[r.format])}</span><span class="ftrack"><span style="width:'
            f'{max(1, r.typical_likes / peak * 100):.0f}%;background:var(--ink)">'
            f'</span></span><span class="fval">{r.typical_likes:,.0f}</span>'
            f'<span class="fval" style="width:4.5rem;color:var(--quiet)">'
            f'{r.posts} post{"s" if r.posts != 1 else ""}</span></div>' for r in rows)
        g = graphic_reels(a, look)
        notes = []
        if g:
            notes.append(f"{g} reel{'s' if g != 1 else ''} with a poster or product "
                         "cover &mdash; likely a still image set to music")
        if look.presenter:
            notes.append(f"Recurring face: {esc(look.presenter)}")
        ai = sum(1 for t in look.posts.values() if t.ai_look)
        if ai:
            notes.append(f"{ai} post{'s' if ai != 1 else ''} look AI-generated")
        note = f'<p class="fnote">{" &middot; ".join(notes)}</p>' if notes else ""
        blocks.append(f'<div class="facct{" mine" if _is(a, client) else ""}">'
                      f'<h3>@{esc(a.handle)}</h3>{bars}{note}</div>')
    return ("<h2>What kind of post earns what</h2>"
            '<p class="note">Each post\'s image was read and sorted by what it '
            'shows. Likes on a <em>normal</em> post of each kind. Reels are '
            'judged by their cover.</p>'
            f'<div class="fgrid">{"".join(blocks)}</div>')


# --------------------------------------------------------------------------- #
# Each competitor up close
# --------------------------------------------------------------------------- #

def section_teardowns(accounts: list[Account], client: str, extras, ideas,
                      out_dir) -> str:
    cards = teardown_cards(accounts, client, extras, ideas, out_dir)
    if not cards:
        return ""
    return ("<h2>Each competitor, up close</h2>"
            '<p class="note">Their two best posts and their weakest, and what '
            'they show.</p>' + f'<div class="tears">{"".join(c for _, c in cards)}</div>')


def teardown_cards(accounts: list[Account], client: str, extras, ideas,
                   out_dir) -> list[tuple[str, str]]:
    """(handle, card) for each competitor, strongest first."""
    me = next((a for a in accounts if _is(a, client) and not a.error), None)
    written = {t.handle.lower(): t for t in getattr(ideas, "teardowns", []) or []}
    cards = []
    for a in sorted(accounts, key=lambda x: -x.typical_likes):
        if a.error or _is(a, client) or not a.posts:
            continue
        look = extras.looks.get(a.handle.lower()) if extras else None
        ratio = ""
        if me and me.post_count and me.followers:
            ratio = (f"{a.post_count / me.post_count:.1f}&times; your posts, "
                     f"{a.followers / me.followers:.1f}&times; your followers")
        scored = sorted([p for p in a.posts if int(p.get("likesCount") or 0) >= 0],
                        key=lambda p: -int(p.get("likesCount") or 0))
        shown = scored[:2] + (scored[-1:] if len(scored) > 3 else [])
        thumbs = ""
        if _any_thumb(out_dir, shown):
            thumbs = "".join(_thumb(out_dir, p, look, "· their weakest" if i == 2 else "")
                             for i, p in enumerate(shown))
        t = written.get(a.handle.lower())
        if not t and not thumbs:
            continue
        body = ""
        if t:
            body = "<dl>" + "".join(
                f"<dt>{label}</dt><dd>{esc(val)}</dd>"
                for label, val in (("What works", t.works), ("What falls flat", t.doesnt),
                                   ("How they post", t.habits)) if val) + "</dl>"
            if t.takeaway:
                body += f'<div class="take"><strong>Take from them:</strong> {esc(t.takeaway)}</div>'
        c = extras.comments.get(a.handle.lower()) if extras else None
        if c and c.read:
            quotes = " ".join(f'<span class="quote">&ldquo;{esc(e.get("text"))}&rdquo;</span>'
                              for e in c.examples[:2])
            body += (f'<p class="note"><strong>The comments:</strong> {esc(c.read)} '
                     f'{quotes}</p>')
        cards.append((a.handle, f'<div class="tear"><h3>@{esc(a.handle)} &nbsp;'
                     f'<span class="note">{a.followers:,} followers &middot; '
                     f'{a.post_count} posts in {a.days} days &middot; normal post '
                     f'{a.typical_likes:,.0f} likes</span></h3>'
                     f'{f"<p class=ratio>{ratio}</p>" if ratio else ""}'
                     f'<div class="thumbs">{thumbs}</div>{body}</div>'))
    return cards


# --------------------------------------------------------------------------- #
# Facebook and ads
# --------------------------------------------------------------------------- #

def section_facebook(accounts: list[Account], client: str, extras) -> str:
    if not extras or not (extras.fb_pages or extras.fb_missing):
        return ""
    rows = []
    for a in accounts:
        p = extras.fb_pages.get(a.handle.lower())
        if not p:
            continue
        if p.error and not p.followers and not p.posts:
            rows.append(f"<tr class='dim'><td>@{esc(a.handle)}</td>"
                        f"<td colspan=6>could not be read: {esc(p.error)[:90]}</td></tr>")
            continue
        if not p.detail:
            rows.append(
                f"<tr{' class=mine' if _is(a, client) else ''}>"
                f"<td><a href='{esc(p.url)}'>@{esc(a.handle)}</a></td>"
                f"<td>{p.followers:,}</td><td colspan=5 class='unk'>followers "
                f"only &mdash; posts read for you and the top two</td></tr>")
            continue
        best = p.best or {}
        best_txt = (f"<a href='{esc(best.get('url'))}'>{int(best.get('likes') or 0):,}</a>"
                    if best else "&mdash;")
        rows.append(
            f"<tr{' class=mine' if _is(a, client) else ''}>"
            f"<td><a href='{esc(p.url)}'>@{esc(a.handle)}</a></td>"
            f"<td>{p.followers:,}</td><td>{p.posts}"
            f"{f' ({p.videos} videos)' if p.videos else ''}</td>"
            f"<td>{p.typical_likes:,.0f}</td><td>{p.typical_comments:,.0f}</td>"
            f"<td>{p.typical_shares:,.0f}</td><td>{best_txt}</td></tr>")
    missing = ""
    if extras.fb_missing:
        missing = ('<p class="note">No Facebook page found for '
                   + ", ".join(f"@{esc(h)}" for h in extras.fb_missing)
                   + ". Type the page address in the dashboard to include it.</p>")
    if not rows:
        return "<h2>Facebook</h2>" + missing
    return ("<h2>Facebook</h2>"
            '<p class="note">Recent posts (up to 6) for you and the two strongest '
            'competitors; followers for everyone. Reactions, comments and shares on a normal post.</p>'
            "<table><thead><tr><th>Page</th><th>Followers</th><th>Posts</th>"
            "<th>Reactions</th><th>Comments</th><th>Shares</th><th>Best post</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>" + missing)


def section_ads(accounts: list[Account], client: str, extras) -> str:
    if not extras or not extras.fb_ads:
        return ""
    blocks = []
    for a in accounts:
        ad = extras.fb_ads.get(a.handle.lower())
        if not ad:
            continue
        if ad.error:
            blocks.append(f"<p class='note'>@{esc(a.handle)}: could not be read "
                          f"({esc(ad.error)[:90]}).</p>")
            continue
        if not ad.active:
            blocks.append(f"<p>@{esc(a.handle)} &mdash; no active ads.</p>")
            continue
        n = f"at least {ad.active}" if ad.capped else str(ad.active)
        items = []
        for s in ad.samples:
            line = f"<span class='quote'>&ldquo;{esc(s.get('text'))[:200]}&rdquo;</span>"
            if s.get("cta"):
                line += f" &middot; button: {esc(s['cta'])}"
            if s.get("started"):
                line += f" &middot; running since {_day(s['started'])}"
            items.append(f"<li>{line}</li>")
        samples = "".join(items)
        blocks.append(f"<p{' class=mine' if _is(a, client) else ''}><strong>@{esc(a.handle)}"
                      f"</strong> &mdash; {n} active ad{'s' if ad.active != 1 else ''}"
                      f"</p><ul class='note'>{samples}</ul>")
    if not blocks:
        return ""
    return ('<h2>Who is running ads<span class="exp">experimental</span></h2>'
            '<p class="note">From Meta\'s public Ad Library: ads running now on '
            'Facebook and Instagram. Spend and results are not public.</p>'
            + "".join(blocks))


# --------------------------------------------------------------------------- #
# The month's plan
# --------------------------------------------------------------------------- #

def section_plan(ideas) -> str:
    plan = getattr(ideas, "plan", None)
    if not plan:
        return ""
    out = ["<h2>The month, planned</h2>"]
    if plan.cadence:
        out.append(f'<p class="verdict">{esc(plan.cadence)}</p>')
    if plan.calendar:
        rows = "".join(
            f"<tr><td>Week {w.week}</td><td>{'<br>'.join(esc(x) for x in w.reels) or '&mdash;'}"
            f"</td><td>{'<br>'.join(esc(x) for x in w.images) or '&mdash;'}</td></tr>"
            for w in plan.calendar)
        out.append("<table><thead><tr><th>Week</th><th>Reels</th><th>Images &amp; "
                   "carousels</th></tr></thead><tbody>" + rows + "</tbody></table>")

    def chips(title: str, items: list[str]) -> str:
        if not items:
            return ""
        return (f'<p class="note"><strong>{esc(title)}</strong></p><div class="chips">'
                + "".join(f"<span>{esc(i)}</span>" for i in items) + "</div>")

    tags = (chips("Local — how people search for you", plan.hashtags_local)
            + chips("What you sell", plan.hashtags_service)
            + chips("Broad reach", plan.hashtags_broad)
            + chips("Location tags", plan.geotags))
    if tags:
        out.append("<h2>Hashtags and location tags</h2>"
                   '<p class="note">8 to 15 a post, mixed from the three groups. '
                   'Tag a location on every post.</p>' + tags)
    if plan.profile_fixes:
        out.append("<h2>Fix the profile</h2><ul class='patterns'>"
                   + "".join(f"<li>{esc(x)}</li>" for x in plan.profile_fixes) + "</ul>")
    if plan.local_actions:
        out.append("<h2>Get found on Google</h2><ul class='patterns'>"
                   + "".join(f"<li>{esc(x)}</li>" for x in plan.local_actions) + "</ul>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# How Conra AI can help, and the call notes
# --------------------------------------------------------------------------- #

PRICES = {"Starter": "₹3,499 a month", "Pro": "₹8,999 a month (launch offer)",
          "Scale": "₹12,999 a month (launch offer)"}


def section_offer(extras) -> str:
    offer = extras.offer if extras else None
    if not offer or not offer.fits:
        return ""
    fits = "".join(
        f'<div class="fit"><div class="ffind">{esc(f.finding)}</div>'
        f'<div class="ffeat"><strong>{esc(f.feature)}</strong></div>'
        f'<div>{esc(f.how)}</div></div>' for f in offer.fits)
    plan = ""
    if offer.plan:
        plan = (f'<p class="verdict">Suggested plan: <strong>{esc(offer.plan)}</strong>'
                f' &mdash; {esc(PRICES.get(offer.plan, ""))}. {esc(offer.plan_why)}</p>')
    return (_part("Next", "How Conra AI can help")
            + f'<p class="lead">{esc(offer.headline)}</p>'
            + f'<div class="fits">{fits}</div>{plan}'
            + f'<div class="cta">Start with a 14-day free trial, no card needed. '
              f'<a href="{CONTACT["site"]}">conraai.com</a> &middot; '
              f'<a href="mailto:{CONTACT["email"]}">{CONTACT["email"]}</a> &middot; '
              f'<a href="{CONTACT["whatsapp"]}">WhatsApp</a></div>')


def section_notes(brief) -> str:
    if brief is None or not (brief.call_notes or "").strip():
        return ""
    return ("<h2>Notes from the call</h2>"
            f'<div class="notes">{html.escape(brief.call_notes.strip())}</div>')


def section_log(extras) -> str:
    """What could not be done, so a missing section is never a mystery."""
    if not extras:
        return ""
    bad = [m for m in extras.log if any(w in m.lower() for w in
                                        ("failed", "could not", "no ", "skipped"))]
    if not bad:
        return ""
    return ('<p class="note" style="margin-top:3rem"><strong>Not included this '
            'time:</strong> ' + " &middot; ".join(esc(m) for m in bad) + "</p>")
