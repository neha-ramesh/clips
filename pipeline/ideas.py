"""Turn what worked into what to make.

THE TWO HALVES, AND WHY ONLY ONE IS COMPUTED

Some of this is in the data. "A post showing only the product gets nothing; a
person wearing it and explaining gets three thousand" is a contrast between two
sets of captions from the same account, and no judgement is needed to see it —
only the comparison, which is what `evidence` assembles.

The rest is not in the data and never will be. Goundamani dialogue over an x-ray,
"yellow is for CSK not your teeth", filter coffee staining. That is knowing a
city and a language, and a scraper has no access to it. It comes from a model
with cultural knowledge, or from you, in the profile notes.

So the model is given the evidence and asked to turn it into formats. What
stops it producing the usual mush — "post more engaging content", "use trending
audio" — is a hard rule: every idea names a real post and quotes its numbers. An
idea that cannot cite one is dropped rather than guessed at.

WHY WINNERS AND LOSERS BOTH GO IN

Giving a model only the hits produces descriptions of the hits. The useful
signal is the difference: these captions did well and these did badly, for the
same account, in the same month. That contrast is what "product-only gets
nothing" actually comes from, and it is invisible if the losers are left out.
"""

from __future__ import annotations

import statistics
from typing import Any, Optional

from pydantic import BaseModel, Field

from .config import config
from .llm import complete_json
from .media import post_key
from .scan import Account, caption_of, hashtags, kind_of, url_of


def _first(d: dict, *names: str, default: str = "") -> str:
    """First present key out of several spellings.

    Models name fields their own way even when the schema says otherwise —
    this one returned "pattern" where the schema asked for "what", and the whole
    response was discarded over a synonym. Accepting the obvious alternatives
    costs nothing and means a good answer is not thrown away on a key name.
    """
    for n in names:
        v = d.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


class Pattern(BaseModel):
    """Something the posts show, with the numbers behind it."""

    what: str = ""               # the observation
    evidence: str = ""           # the posts and numbers that support it

    @classmethod
    def loose(cls, d: dict) -> "Pattern":
        return cls(
            what=_first(d, "what", "pattern", "observation", "finding", "title"),
            evidence=_first(d, "evidence", "proof", "numbers", "example",
                            "support", "detail"),
        )


class Idea(BaseModel):
    """One thing to make."""

    idea: str = ""               # concrete enough to shoot tomorrow
    goal: str = ""               # what it is for
    proof_account: str = ""      # who it demonstrably worked for
    proof_number: str = ""       # the numbers
    effort: str = ""             # what it takes to produce
    local: bool = False          # relies on culture rather than the data

    @classmethod
    def loose(cls, d: dict) -> "Idea":
        return cls(
            idea=_first(d, "idea", "what", "format", "concept", "title"),
            goal=_first(d, "goal", "why", "purpose", "achieves", "objective"),
            proof_account=_first(d, "proof_account", "account", "competitor",
                                 "worked_for", "source").lstrip("@"),
            proof_number=_first(d, "proof_number", "proof", "numbers",
                                "evidence", "metric"),
            effort=_first(d, "effort", "cost", "production", "what_it_takes"),
            local=bool(d.get("local") or d.get("untested")
                       or d.get("from_data") is False),
        )


class Teardown(BaseModel):
    """One competitor, the way the hand-written audits read each account."""

    handle: str = ""
    works: str = ""           # what earns them attention, with numbers
    doesnt: str = ""          # what falls flat, with numbers
    habits: str = ""          # how they post: language, length, cadence, tags
    takeaway: str = ""        # the one thing the client should take from them


class Week(BaseModel):
    week: int = 0
    reels: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    cadence: str = ""                                    # how often, which days
    calendar: list[Week] = Field(default_factory=list)
    hashtags_local: list[str] = Field(default_factory=list)
    hashtags_service: list[str] = Field(default_factory=list)
    hashtags_broad: list[str] = Field(default_factory=list)
    geotags: list[str] = Field(default_factory=list)
    profile_fixes: list[str] = Field(default_factory=list)
    local_actions: list[str] = Field(default_factory=list)   # Google, reviews...


class Ideas(BaseModel):
    patterns: list[Pattern] = Field(default_factory=list)
    ideas: list[Idea] = Field(default_factory=list)
    teardowns: list[Teardown] = Field(default_factory=list)
    plan: Optional[Plan] = None


SCHEMA = {
    "type": "object",
    "properties": {
        "patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"what": {"type": "string"},
                               "evidence": {"type": "string"}},
                "required": ["what", "evidence"],
            },
        },
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idea": {"type": "string"},
                    "goal": {"type": "string"},
                    "proof_account": {"type": "string"},
                    "proof_number": {"type": "string"},
                    "effort": {"type": "string"},
                    "local": {"type": "boolean"},
                },
                "required": ["idea", "goal"],
            },
        },
        "teardowns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {k: {"type": "string"} for k in
                               ("handle", "works", "doesnt", "habits", "takeaway")},
                "required": ["handle", "works", "doesnt", "habits", "takeaway"],
            },
        },
    },
    "required": ["patterns", "ideas", "teardowns"],
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "cadence": {"type": "string"},
        "calendar": {"type": "array", "items": {
            "type": "object",
            "properties": {"week": {"type": "integer"},
                           "reels": {"type": "array", "items": {"type": "string"}},
                           "images": {"type": "array", "items": {"type": "string"}}},
            "required": ["week", "reels", "images"]}},
        **{k: {"type": "array", "items": {"type": "string"}} for k in
           ("hashtags_local", "hashtags_service", "hashtags_broad", "geotags",
            "profile_fixes", "local_actions")},
    },
    "required": ["cadence", "calendar", "hashtags_local", "hashtags_service",
                 "hashtags_broad", "geotags", "profile_fixes", "local_actions"],
}


SYSTEM_PROMPT = """You are planning content for a small business, from a month
of their competitors' Instagram posts.

You get, for each account, the posts that did far better than that account's own
normal, and the posts that did far worse — with captions and numbers.

Write for the owner, not a marketer. Say likes, comments, posts. Never say
engagement, reach, impressions, or anything they would have to look up.

FIRST: patterns. Three to five things the posts show. Each needs the contrast
that makes it visible, and real numbers.

  Good: "A post of the product on its own gets almost nothing. The same account
         posting a person wearing it and talking about it gets 2,800."
  Bad:  "Video content performs better." — no numbers, no contrast, and the
         reader already knew.

Look for what the winning captions have that the losing ones do not: a person
in shot, a named collaborator, a festival, a story, a price or an offer, a
question. Say which.

SECOND: ideas. Seven to ten things to make. Each one:

  idea   Concrete enough to shoot tomorrow. "The owner explaining how gold
         purity is checked, 30 seconds, phone on a tripod" — not "educational
         content".
  goal   What it is for, in one line. Recall, saves, footfall, trust.
  proof_account / proof_number
         The competitor it worked for and the numbers. If an idea comes from
         knowing the place rather than from the data — a local reference, a
         language, a festival, a film — set "local": true and leave the proof
         fields empty. Do not invent evidence.
  effort What it takes to make. Be realistic for a small business with a phone.

At least five ideas must be backed by the data. The rest may be local ideas, and
those are welcome — a reference the audience recognises beats a generic format —
but they must be marked so nobody mistakes a hunch for a measurement.

Repeatable formats are worth more than one-off posts: a named weekly series, a
recurring face, a running character. Say so when the data supports it.

If competitors run their own branded hashtags, that is worth one idea. Do not
tell the client to avoid a competitor's tag — that is obvious and reads as a
telling-off. Say what the competitor built and propose the client's own version,
with something to attach it to: a giveaway, a series, a customer photo, a
festival campaign. Cite the competitor's tag and its numbers as the proof that
the tactic works.

Only cite a post listed under DID WELL. Some accounts have none — they are in
here so you can see what does NOT work, and citing one of their posts as proof
would undermine everything else in the report. If an idea has no strong post
behind it, mark it "local": true instead of reaching for a weak one.

WHAT IS IN THE POSTS. Where a post line carries [brackets], that is what its
image shows, read from the image itself - a person talking on camera, the
product alone, a designed poster, a greeting. "FORMATS" lines give each
account's normal likes per kind of image. These are the strongest contrasts you
have: "the product alone, 10 posts, normal 15 likes; a person talking on
camera, 4 posts, normal 600" is exactly the kind of pattern wanted. Prefer
them over guessing from captions. "COMMENTS" lines say who is commenting -
price enquiries are buyers; compliments to a model are not.

THE CLIENT BRIEF, when given, holds hard rules (for example "never show
prices", a professional code of ethics). No idea may break one. Write for the
client's actual customer, language and positioning as the brief states them.

THIRD: teardowns. One for each competitor (not the client), the way an analyst
reads an account:
  works     what earns them attention, with their numbers
  doesnt    what falls flat for them, with numbers
  habits    how they post - language, reel length, how often, hashtags and
            location tags, a recurring face - only what the data shows
  takeaway  the one thing the client should take from them, one sentence
For an account where nothing works, say so plainly; it is a finding too.

Return ONLY JSON."""

PLAN_SYSTEM = """You turn a social media audit into a month's working plan for
the client. You get the client brief, the patterns found, the content ideas
(numbered), and how the client and competitors currently post.

Write:
- cadence: how often to post and on which days, one line, grounded in what the
  data showed about posting rhythm and timing.
- calendar: four weeks. Each week lists the reels and the images to make, by
  short name and idea number ("#2 Owner explains IGI certificate"). Use the
  agreed monthly volume from the brief if given (split across the weeks);
  otherwise suggest a realistic volume for a small business. Mix proven ideas
  with local ones; repeat a strong recurring format rather than inventing.
- hashtags in three tiers, 4-6 each, written with #: hashtags_local (the city
  and areas, as people search them), hashtags_service (what they sell or
  treat), hashtags_broad (category reach). Prefer tags that appear in the
  competitor data; never a competitor's own branded tag.
- geotags: the places to tag on posts - the client's own locations first.
- profile_fixes: concrete fixes to the client's Instagram profile from the
  checklist given (location in bio, highlights to add and what to put in them,
  link, category). Only fixes that the checklist shows are needed.
- local_actions: only for a local business, and only where the data shows a
  gap (search visibility, Google rating and reviews against competitors):
  concrete steps such as a review QR at the counter, replying to reviews, a
  weekly Google Business Profile update. Empty for an online business.

Every item must respect the hard rules in the brief. Plain words."""


def _extremes(a: Account, floor: int, top_n: int = 4,
              bottom_n: int = 3) -> tuple[list, list]:
    """The posts that beat this account's usual, and the ones that flopped.

    `floor` is what stops a dead account supplying evidence. Beating your own
    median is a relative test, and for an account whose normal post gets 8
    likes, a post with 28 clears it three times over — which produced the line
    "Worked for @b.b.jewellers — 28 likes" two sections after the same report
    called that account invisible. A client reading that stops trusting every
    number above it.

    So a winner has to clear both bars: unusual for its own account, AND large
    enough that quoting it does not embarrass the report.
    """
    scored = [(int(p.get("likesCount") or 0), p) for p in a.posts
              if int(p.get("likesCount") or 0) >= 0 and caption_of(p)]
    if len(scored) < 4:
        return [], []
    scored.sort(key=lambda x: -x[0])
    usual = statistics.median(x[0] for x in scored) or 1
    winners = [(lk, p) for lk, p in scored[:top_n]
               if lk >= usual * 1.5 and lk >= floor]
    losers = [(lk, p) for lk, p in scored[-bottom_n:] if lk <= usual * 0.7]
    return winners, losers


def _seen(extras, a: Account, p: dict) -> str:
    """' [a person talking on camera: owner explains a necklace]', or ''."""
    look = getattr(extras, "looks", {}).get(a.handle.lower()) if extras else None
    tag = look.posts.get(post_key(p)) if look else None
    if not tag:
        return ""
    from .visual import FORMATS
    bits = FORMATS.get(tag.format, tag.format).lower()
    if tag.ai_look:
        bits += ", looks AI-generated"
    return f" [{bits}: {tag.describe}]" if tag.describe else f" [{bits}]"


def _account_extras(extras, a: Account) -> list[str]:
    """FORMATS / presenter / COMMENTS / habits lines for one account."""
    if extras is None:
        return []
    from .habits import habits_of
    from .visual import FORMATS, by_format, graphic_reels

    lines: list[str] = []
    look = extras.looks.get(a.handle.lower()) if extras.looks else None
    if look and look.posts:
        rows = by_format(a, look)
        lines.append("  FORMATS: " + "; ".join(
            f"{FORMATS[r.format].lower()}: {r.posts} posts, normal {r.typical_likes:,.0f} "
            f"likes, best {r.best_likes:,}" for r in rows))
        g = graphic_reels(a, look)
        if g:
            lines.append(f"  {g} of their reels have a poster or product-shot "
                         "cover (likely a still image set to music)")
        if look.presenter:
            lines.append(f"  Recurring face: {look.presenter}")
    c = extras.comments.get(a.handle.lower()) if extras.comments else None
    if c and c.counts:
        lines.append(f"  COMMENTS (sample of {c.sampled}): "
                     + ", ".join(f"{k.replace('_', ' ')} {v}"
                                 for k, v in c.counts.items() if v)
                     + (f". They replied {c.owner_replies} times, "
                        f"{c.redirects} pointing to DM/WhatsApp" if c.owner_replies else "")
                     + (f'. Read: {c.read}' if c.read else ""))
    h = habits_of(a, getattr(extras, "place_words", []))
    if h.posts:
        langs = ", ".join(f"{k} {v}" for k, v in h.languages.items())
        lines.append(f"  HABITS: location tag on {h.with_location}/{h.posts} posts, "
                     f"hashtags on {h.with_hashtags}/{h.posts}"
                     + (f" (~{h.tags_per_post:.0f} each)" if h.with_hashtags else "")
                     + (f", caption languages: {langs}" if langs else "")
                     + (f", reels {h.reel_seconds:.0f}s typical" if h.reels else "")
                     + (f", up to {h.busiest_day_posts} posts in one day"
                        if h.busiest_day_posts >= 3 else ""))
    return lines


def evidence(accounts: list[Account], client: str, extras=None) -> str:
    """What the model sees. Numbers, captions and what the images show."""
    live = [a for a in accounts if not a.error and a.posts]
    if not live:
        return ""

    # A post has to clear this to be quotable as proof. Set from the strongest
    # account in the set, so it scales with the category — a dental practice
    # and a jewellery chain live at different orders of magnitude, and a fixed
    # number would be wrong for both.
    strongest = max(a.typical_likes for a in live) or 1
    floor = max(30, strongest * 0.15)

    lines: list[str] = []
    for a in sorted(live, key=lambda x: -x.typical_likes):
        tag = "  [THIS IS THE CLIENT]" if a.handle.lower() == client.lower() else ""
        lines.append(f"\n@{a.handle}{tag} — {a.followers:,} followers, "
                     f"{a.post_count} posts in {a.days} days, "
                     f"a normal post gets {a.typical_likes:,.0f} likes")

        for k, v in sorted(a.likes_by_kind.items(), key=lambda x: -x[1]):
            share = a.mix.get(k, 0) * 100
            lines.append(f"  {k}s: {share:.0f}% of the feed, "
                         f"a normal one gets {v:,.0f} likes")

        lines.extend(_account_extras(extras, a))

        winners, losers = _extremes(a, floor)
        if not winners and a.handle.lower() != client.lower():
            lines.append("  (nothing here did well enough to hold up as an "
                         "example — do not cite this account as proof)")
        for lk, p in winners:
            lines.append(f'  DID WELL — {lk:,} likes, '
                         f'{int(p.get("commentsCount") or 0):,} comments, '
                         f'{kind_of(p)}{_seen(extras, a, p)}: "{caption_of(p)[:180]}"')
        for lk, p in losers:
            lines.append(f'  DID BADLY — {lk:,} likes, {kind_of(p)}'
                         f'{_seen(extras, a, p)}: "{caption_of(p)[:180]}"')

    # Branded tags, as a strategy rather than a prohibition. A competitor
    # running #celebratewithabaran is not a rule about what the client may type
    # — it is a thing they built, and building one is a recommendation.
    # Genuinely branded only — a tag carrying an account's own name. A generic
    # tag that happens to be used by one account is not a brand, and listing it
    # here would suggest the client invent a version of #bridaljewellery.
    branded = [t for t in hashtags(live) if t.branded]
    if branded:
        lines.append("\nBRANDED TAGS THESE ACCOUNTS RUN (their own, not "
                     "searchable by anyone else — listed because building one "
                     "is a tactic worth copying, not because the client should "
                     "use these):")
        for t in branded[:8]:
            lines.append(f"  #{t.label} — {t.who[0]}, on {t.posts} posts, "
                         f"a normal one gets {t.typical_likes:,.0f} likes")

    return "\n".join(lines)


def suggest(
    accounts: list[Account],
    client: str,
    *,
    business: str = "",
    place: str = "",
    language: str = "",
    notes: str = "",
    verbose: bool = True,
    brief_text: str = "",
    extras=None,
) -> Optional[Ideas]:
    """Patterns and content ideas. None if the model call fails.

    `place` and `language` matter more than they look: they are what let a local
    reference appear at all. Without them the ideas come back generic, because
    the data alone cannot tell anyone that the audience is in Chennai and speaks
    Tamil.
    """
    data = evidence(accounts, client, extras)
    if not data.strip():
        return None

    mine = next((a for a in accounts
                 if a.handle.lower() == client.lower() and not a.error), None)
    ctx = [f"CLIENT: @{client}"]
    if mine and mine.posts:
        ctx.append(f"For scale: a normal post on the client's own account gets "
                   f"{mine.typical_likes:,.0f} likes and their best got "
                   f"{mine.best_likes:,}.")
    if business:
        ctx.append(f"Business: {business}")
    if place:
        ctx.append(f"Where their customers are: {place}")
    if language:
        ctx.append(f"Language their audience uses: {language}")
    if notes:
        ctx.append(f"Anything else worth knowing: {notes}")
    if brief_text:
        ctx.append(f"\nCLIENT BRIEF:\n{brief_text}")

    try:
        got = complete_json(
            SYSTEM_PROMPT,
            "\n".join(ctx) + "\n\nTHE POSTS:\n" + data,
            schema=SCHEMA,
            list_key="ideas",
            required_field="idea",
            temperature=0.5,      # ideas benefit from some variety
            effort="high",
        )
        # Built field by field rather than by validating the whole shape, so a
        # renamed key costs one entry instead of the entire response.
        out = Ideas(
            patterns=[Pattern.loose(x) for x in got.get("patterns", [])
                      if isinstance(x, dict)],
            ideas=[Idea.loose(x) for x in got.get("ideas", [])
                   if isinstance(x, dict)],
            teardowns=[Teardown(**{k: str(x.get(k) or "") for k in
                                   ("handle", "works", "doesnt", "habits", "takeaway")})
                       for x in got.get("teardowns", []) if isinstance(x, dict)],
        )
        for t in out.teardowns:
            t.handle = t.handle.lstrip("@")
        out.teardowns = [t for t in out.teardowns
                         if t.handle and t.handle.lower() != client.lower()]
        out.patterns = [p for p in out.patterns if p.what]
        out.ideas = [i for i in out.ideas if i.idea]
    except Exception as e:
        if verbose:
            print(f"  ideas unavailable: {e}")
        return None

    # An idea claiming proof has to name both halves of it. Half a citation is
    # worse than none — it reads as evidence and is not.
    for i in out.ideas:
        if not (i.proof_account and i.proof_number):
            i.local = True
            i.proof_account = ""
            i.proof_number = ""
    return out


def plan(accounts: list[Account], client: str, ideas: Ideas, *,
         brief_text: str = "", extras=None, local: bool = True,
         verbose: bool = True) -> Optional[Plan]:
    """The month's calendar, hashtag tiers, profile fixes and local actions."""
    from .habits import checklist, habits_of

    lines = [f"CLIENT: @{client} ({'local business' if local else 'online business'})"]
    if brief_text:
        lines.append(f"\nCLIENT BRIEF:\n{brief_text}")
    lines.append("\nPATTERNS FOUND:")
    lines += [f"- {p.what} ({p.evidence})" for p in ideas.patterns]
    lines.append("\nCONTENT IDEAS:")
    lines += [f"#{n} {i.idea} - {i.goal}" + (" [local idea]" if i.local else
              f" [worked for @{i.proof_account}: {i.proof_number}]")
              for n, i in enumerate(ideas.ideas, 1)]

    pw = getattr(extras, "place_words", []) if extras else []
    mine = next((a for a in accounts if a.handle.lower() == client.lower()
                 and not a.error), None)
    if mine:
        h = habits_of(mine, pw)
        lines.append("\nCLIENT PROFILE CHECKLIST:")
        lines += [f"- {item}: {'OK' if ok else 'NEEDS FIXING' if ok is False else '?'}"
                  f" ({detail})" for item, ok, detail in checklist(h)]
        if h.top_locations:
            lines.append(f"Client's location tags so far: {', '.join(h.top_locations)}")
    lines.append("\nHOW EVERYONE POSTS:")
    for a in accounts:
        if a.error or not a.posts:
            continue
        lines.append(f"@{a.handle}: {a.post_count} posts in {a.days} days, "
                     f"normal post {a.typical_likes:,.0f} likes")
        lines.extend(_account_extras(extras, a))
    tags = [t for t in hashtags([a for a in accounts if not a.error and a.posts])
            if not t.branded][:25]
    if tags:
        lines.append("\nHASHTAGS SEEN IN THE DATA (not branded): " + ", ".join(
            f"#{t.label} ({t.posts} posts, {t.accounts} accounts)" for t in tags))
    vis = getattr(extras, "visibility", None) if extras else None
    if vis:
        from .visibility import rank_of
        for t, handles in vis.instagram.items():
            r = rank_of(client, handles)
            lines.append(f"Instagram search '{t}': client "
                         + (f"#{r}" if r else "not in the top results"))
        if vis.client_place:
            cp = vis.client_place
            lines.append(f"Client on Google Maps: {cp.rating} stars, {cp.reviews} reviews")
        for t, places in vis.maps.items():
            top = ", ".join(f"{p.title} ({p.rating}, {p.reviews} reviews)"
                            for p in places[:5])
            lines.append(f"Google Maps '{t}' top results: {top}")

    try:
        got = complete_json(PLAN_SYSTEM, "\n".join(lines), schema=PLAN_SCHEMA,
                            list_key="calendar", required_field="week",
                            model=config.anthropic_model, temperature=1.0, effort="medium")
    except Exception as e:
        if verbose:
            print(f"  plan unavailable: {e}")
        return None

    def strs(key: str) -> list[str]:
        return [str(x) for x in got.get(key) or [] if str(x).strip()]

    return Plan(
        cadence=str(got.get("cadence") or ""),
        calendar=[Week(week=int(w.get("week") or n),
                       reels=[str(x) for x in w.get("reels") or []],
                       images=[str(x) for x in w.get("images") or []])
                  for n, w in enumerate(got.get("calendar") or [], 1)
                  if isinstance(w, dict)],
        hashtags_local=strs("hashtags_local"),
        hashtags_service=strs("hashtags_service"),
        hashtags_broad=strs("hashtags_broad"),
        geotags=strs("geotags"),
        profile_fixes=strs("profile_fixes"),
        local_actions=strs("local_actions") if local else [],
    )
