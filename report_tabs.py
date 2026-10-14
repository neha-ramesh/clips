"""The report's layout: tabs, a one-screen summary, a competitor picker.

WHY TABS

The report had grown to twenty sections in one scroll, and the person it was
written for got tired before the end. Each tab now answers one question and
fits in a few screens:

    Summary            the five things that matter, each linked to its proof
    You today          the client's own numbers and profile
    Can people find you
    Competitors        one competitor at a time, picked from a row of names
    What works         what kind of post earns what; the detail folded away
    The plan           what to make, the month, hashtags, fixes
    Conra AI           how Conra helps, and the notes from the call

Every section opens with one plain sentence on what it means for the client
(`sowhat`), and the words a client might not know carry an ⓘ that explains them.

The summary is computed from the numbers, not written by a model: it costs
nothing and cannot drift from the evidence it links to.

It is still one self-contained HTML file. Printing shows every tab.
"""

from __future__ import annotations

import html
import statistics

from pipeline.scan import Account, rhythm_of
from pipeline.visibility import rank_of
from pipeline.visual import FORMATS, by_format

GLOSSARY = {
    "normal post": "The middle post: half of their posts did better, half did "
                   "worse. Unlike an average, one viral post cannot inflate it.",
    "reel": "A short video post. Instagram shows reels to people who do not "
            "follow the account yet, which is how accounts grow.",
    "carousel": "A post of several images or videos you swipe through.",
    "location tag": "The place added to a post. People browsing that place, "
                    "or searching it, can find the post.",
    "highlights": "The circles under the bio that keep stories on the profile "
                  "for good: prices, collections, reviews, directions.",
    "cover": "The first frame of a reel, shown in the grid. A reel whose cover "
             "is a poster is usually a still image set to music.",
    "direct competitor": "Sells the same thing to the same customers, where "
                         "the client sells.",
}

CSS = """
.tabs{position:sticky;top:0;z-index:5;background:var(--paper);display:flex;
      gap:.2rem;overflow-x:auto;border-bottom:1px solid var(--rule);
      margin:0 0 1.6rem;padding:.4rem 0 0;scrollbar-width:thin}
.tabs button{font:inherit;font-size:.88rem;background:none;border:0;
      border-bottom:3px solid transparent;padding:.6rem .9rem;cursor:pointer;
      color:var(--quiet);white-space:nowrap}
.tabs button:hover{color:var(--ink)}
.tabs button.on{color:var(--ink);border-bottom-color:var(--gold);font-weight:600}
.pane{display:none}
.pane.on{display:block;animation:fade .2s ease}
@keyframes fade{from{opacity:0}to{opacity:1}}
.pane .part{display:none}
.pane>h2:first-child,.pane>.sowhat:first-child{margin-top:.4rem}
.sowhat{font-size:1.05rem;margin:.6rem 0 1.4rem;padding:.8rem 1rem;
        background:#F2EFE7;border-radius:4px;max-width:48rem}
.sowhat::before{content:"What this means: ";font-weight:600}
.facts{display:grid;gap:.9rem;margin:1rem 0 1.6rem}
.fact{display:grid;grid-template-columns:2.2rem 1fr;gap:.9rem;align-items:start;
      border:1px solid var(--rule);border-radius:4px;padding:1rem 1.1rem;
      background:#FCFBF7}
.fact .n{font-size:1.4rem;color:var(--gold);line-height:1}
.fact p{margin:0 0 .3rem;font-size:1rem}
.fact a{font-size:.85rem;color:var(--good);cursor:pointer;text-decoration:none}
.fact a:hover{text-decoration:underline}
.start{border:2px solid var(--good);border-radius:4px;padding:1rem 1.2rem;
       background:#F5FAF7;margin:1.4rem 0}
.start b{display:block;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;
         color:var(--good);margin-bottom:.3rem}
details.more{border:1px solid var(--rule);border-radius:4px;margin:1rem 0;
             background:#FCFBF7}
details.more>summary{cursor:pointer;padding:.8rem 1.1rem;font-size:.95rem;
                     list-style:none;display:flex;justify-content:space-between}
details.more>summary::after{content:"Show";color:var(--good);font-size:.82rem}
details.more[open]>summary::after{content:"Hide"}
details.more>summary::-webkit-details-marker{display:none}
details.more>div{padding:0 1.1rem 1rem}
details.more h2{font-size:1.1rem;margin-top:1.4rem}
.pick{display:flex;flex-wrap:wrap;gap:.4rem;margin:.8rem 0 1.2rem}
.pick button{font:inherit;font-size:.85rem;border:1px solid var(--rule);
       background:#FCFBF7;border-radius:999px;padding:.35rem .9rem;cursor:pointer}
.pick button.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.cpane{display:none}.cpane.on{display:block}
.tip{display:inline-block;position:relative;cursor:help;color:var(--gold);
     font-size:.8em;margin-left:.2rem;font-style:normal}
.tip:hover::after,.tip:focus::after{content:attr(data-tip);position:absolute;
     left:50%;transform:translateX(-50%);bottom:1.6em;width:16rem;
     background:var(--ink);color:var(--paper);padding:.55rem .7rem;
     border-radius:4px;font-size:.78rem;line-height:1.4;z-index:10;
     font-weight:normal;text-transform:none;letter-spacing:0}
.howto{font-size:.82rem;color:var(--quiet);margin:-1rem 0 1.4rem}
.cmp td,.cmp th{text-align:right}
.cmp td:first-child,.cmp th:first-child{text-align:left}
@media print{.tabs,.pick{display:none}.pane,.cpane{display:block!important}
  details.more{border:0}details.more>div{display:block!important}
  .pane{page-break-before:always}}
"""

JS = """
(function(){
  function show(id){
    document.querySelectorAll('.pane').forEach(function(p){p.classList.toggle('on',p.id===id)});
    document.querySelectorAll('.tabs button').forEach(function(b){b.classList.toggle('on',b.dataset.tab===id)});
    if(history.replaceState)history.replaceState(null,'','#'+id);
    window.scrollTo({top:0,behavior:'smooth'});
  }
  document.querySelectorAll('.tabs button').forEach(function(b){
    b.addEventListener('click',function(){show(b.dataset.tab)})});
  document.querySelectorAll('[data-goto]').forEach(function(a){
    a.addEventListener('click',function(e){e.preventDefault();show(a.dataset.goto)})});
  document.querySelectorAll('.pick').forEach(function(row){
    row.querySelectorAll('button').forEach(function(b){
      b.addEventListener('click',function(){
        row.querySelectorAll('button').forEach(function(x){x.classList.toggle('on',x===b)});
        document.querySelectorAll('.cpane').forEach(function(p){p.classList.toggle('on',p.id===b.dataset.c)});
      })})});
  var start=(location.hash||'').slice(1);
  show(document.getElementById(start)&&start.indexOf('t-')===0?start:'t-summary');
})();
"""


def esc(s) -> str:
    return html.escape(" ".join(str(s or "").split()))


def tip(term: str) -> str:
    """An ⓘ that explains a term on hover or tap."""
    text = GLOSSARY.get(term, "")
    return (f'<span class="tip" tabindex="0" data-tip="{esc(text)}">ⓘ</span>'
            if text else "")


def sowhat(text: str) -> str:
    return f'<p class="sowhat">{text}</p>' if text else ""


def fold(title: str, body: str, open_: bool = False) -> str:
    """A section the reader opens if they want the detail."""
    if not body.strip():
        return ""
    return (f'<details class="more"{" open" if open_ else ""}><summary>{esc(title)}'
            f'</summary><div>{body}</div></details>')


# --------------------------------------------------------------------------- #
# The summary: computed, not written
# --------------------------------------------------------------------------- #

def _fmt_k(n: float) -> str:
    return f"{n:,.0f}"


def summary_facts(accounts: list[Account], client: str, extras, ideas
                  ) -> list[tuple[str, str]]:
    """(sentence, tab it links to), most important first. At most five."""
    me = next((a for a in accounts if a.handle.lower() == client.lower()
               and not a.error), None)
    rivals = [a for a in accounts if not a.error and a.posts
              and a.handle.lower() != client.lower()]
    facts: list[tuple[str, str]] = []

    if me and rivals:
        top = max(rivals, key=lambda a: a.typical_likes)
        if me.posts:
            facts.append((
                f"A normal post of yours gets <strong>{_fmt_k(me.typical_likes)} "
                f"likes</strong>{tip('normal post')}. @{esc(top.handle)}'s gets "
                f"<strong>{_fmt_k(top.typical_likes)}</strong> &mdash; from "
                f"{top.followers / max(me.followers, 1):.0f}&times; your followers "
                f"and {top.post_count} posts to your {me.post_count} this month.",
                "t-competitors"))
        else:
            facts.append((f"You posted nothing in the last {me.days} days. "
                          f"@{esc(top.handle)} posted {top.post_count} times.",
                          "t-today"))

    # The sharpest contrast between two kinds of post on one account.
    best = None
    if extras and extras.looks:
        for a in rivals + ([me] if me else []):
            look = extras.looks.get(a.handle.lower())
            if not look or not look.posts:
                continue
            rows = [r for r in by_format(a, look) if r.posts >= 2]
            if len(rows) < 2:
                continue
            hi, lo = rows[0], rows[-1]
            ratio = hi.typical_likes / max(lo.typical_likes, 1)
            if hi.typical_likes >= 30 and ratio >= 2 and (best is None or ratio > best[0]):
                best = (ratio, a, hi, lo)
    if best:
        _, a, hi, lo = best
        facts.append((
            f"On @{esc(a.handle)}, <strong>{esc(FORMATS[hi.format].lower())}</strong> "
            f"gets {_fmt_k(hi.typical_likes)} likes on a normal post; "
            f"<strong>{esc(FORMATS[lo.format].lower())}</strong> gets "
            f"{_fmt_k(lo.typical_likes)}. Same account, same followers &mdash; "
            f"the kind of post is the difference.", "t-works"))

    v = extras.visibility if extras else None
    if v and v.instagram:
        term, handles = next(iter(v.instagram.items()))
        r = rank_of(client, handles)
        known = {a.handle.lower() for a in rivals}
        theirs = [h for h in handles[:10] if h in known]
        if not r:
            facts.append((
                f"Someone searching Instagram for &ldquo;{esc(term)}&rdquo; does "
                f"<strong>not find you</strong>"
                + (f"; they find {', '.join('@' + esc(h) for h in theirs[:3])}."
                   if theirs else "."), "t-find"))
        elif r > 3:
            facts.append((f"For &ldquo;{esc(term)}&rdquo; on Instagram you come "
                          f"up <strong>#{r}</strong>.", "t-find"))

    if v and v.client_place and v.maps:
        reviews = [p.reviews for ps in v.maps.values() for p in ps[:10] if p.reviews]
        mid = statistics.median(reviews) if reviews else 0
        if mid and v.client_place.reviews < mid * 0.6:
            facts.append((
                f"On Google Maps you have <strong>{v.client_place.reviews:,} "
                f"reviews</strong>; the places shown first have around "
                f"{_fmt_k(mid)}. Reviews decide who Google shows first.",
                "t-find"))

    if me and me.posts:
        r = rhythm_of(me)
        if r and r.longest_gap_days >= 7:
            facts.append((
                f"Your longest stretch without a post this month was "
                f"<strong>{r.longest_gap_days:.0f} days</strong>. Gaps cost "
                f"reach: Instagram shows accounts that post steadily.",
                "t-today"))

    if extras and extras.comments and rivals:
        asks = [(c.counts.get("price_or_buying", 0), h) for h, c in extras.comments.items()
                if c.counts and h != client.lower()]
        if asks:
            n, h = max(asks)
            if n >= 2:
                facts.append((
                    f"Under @{esc(h)}'s posts, <strong>{n} people asked the price"
                    f"</strong> in the comments read &mdash; that is where the "
                    f"buyers are, and what their posts do to get them.",
                    "t-competitors"))

    if not facts and ideas and getattr(ideas, "patterns", None):
        facts = [(esc(p.what), "t-plan") for p in ideas.patterns[:3]]
    return facts[:5]


def summary_pane(accounts, client, extras, ideas) -> str:
    facts = summary_facts(accounts, client, extras, ideas)
    items = "".join(
        f'<div class="fact"><div class="n">{n}</div><div><p>{text}</p>'
        f'<a data-goto="{tab}" href="#{tab}">See the evidence &rarr;</a></div></div>'
        for n, (text, tab) in enumerate(facts, 1))
    start = ""
    ideas_list = [i for i in getattr(ideas, "ideas", []) or [] if not i.local]
    if ideas_list:
        i = ideas_list[0]
        start = (f'<div class="start"><b>Start here</b><strong>{esc(i.idea)}</strong>'
                 f'<br><span class="note">{esc(i.goal)}'
                 + (f" &middot; worked for @{esc(i.proof_account)}: {esc(i.proof_number)}"
                    if i.proof_account else "") +
                 f'</span><br><a data-goto="t-plan" href="#t-plan" '
                 f'style="color:var(--good);font-size:.85rem">The full plan &rarr;</a></div>')
    if not items and not start:
        return '<p class="note">Not enough data for a summary.</p>'
    return ('<h2 style="margin-top:.4rem">What matters most</h2>'
            '<p class="note">The five findings that matter most, in plain '
            'numbers. Each links to the proof.</p>'
            f'<div class="facts">{items}</div>{start}')


# --------------------------------------------------------------------------- #
# Competitors: one at a time
# --------------------------------------------------------------------------- #

def compare_table(accounts: list[Account], client: str, extras) -> str:
    rows = []
    for a in sorted([a for a in accounts if not a.error], key=lambda a: -a.typical_likes):
        fb = extras.fb_pages.get(a.handle.lower()) if extras else None
        ads = extras.fb_ads.get(a.handle.lower()) if extras else None
        mine = a.handle.lower() == client.lower()
        rows.append(
            f"<tr{' class=mine' if mine else ''}><td>@{esc(a.handle)}"
            f"{' (you)' if mine else ''}</td><td>{a.followers:,}</td>"
            f"<td>{a.post_count}</td><td>{a.typical_likes:,.0f}</td>"
            f"<td>{a.best_likes:,}</td>"
            f"<td>{f'{fb.followers:,}' if fb and fb.followers else '&mdash;'}</td>"
            f"<td>{('yes' if ads.active else 'no') if ads and not ads.error else '&mdash;'}</td></tr>")
    return ('<table class="cmp"><thead><tr><th>Account</th><th>Followers</th>'
            f'<th>Posts this month</th><th>Normal post{tip("normal post")}</th>'
            '<th>Best post</th><th>Facebook followers</th><th>Running ads</th>'
            '</tr></thead><tbody>' + "".join(rows) + "</tbody></table>")


def picker(cards: list[tuple[str, str]]) -> str:
    """(handle, card html) -> a row of names and one card shown at a time."""
    if not cards:
        return ""
    buttons = "".join(f'<button data-c="c-{i}"{" class=on" if i == 0 else ""}>'
                      f'@{esc(h)}</button>' for i, (h, _) in enumerate(cards))
    panes = "".join(f'<div class="cpane{" on" if i == 0 else ""}" id="c-{i}">{c}</div>'
                    for i, (_, c) in enumerate(cards))
    return f'<div class="pick">{buttons}</div>{panes}'
