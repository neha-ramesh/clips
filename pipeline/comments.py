"""What the comments say about who is watching.

Likes count everyone. Comments show who: the hand-written audits drew some of
their sharpest lines from them — "people are commenting for the model, not the
jewellery", "the first competitor where people ask for the price under multiple
posts", "they already have a comment-to-DM system". Indian Instagram has its own
shorthand for buying intent: "Pp" and "Pls share price" under a product mean a
price enquiry.

The scraper returns a handful of recent comments per post (`latestComments`).
That is a sample, not every comment, and the report says so.

Whether the account replies, and whether its replies move the conversation to
DM or WhatsApp, is counted here directly — no model involved.
"""

from __future__ import annotations

import re
from typing import Callable

from pydantic import BaseModel, Field

from .config import config
from .llm import complete_json
from .scan import Account

PER_ACCOUNT = 60

KINDS = {
    "price_or_buying": "Asking the price or how to buy",
    "booking_or_visit": "Wanting to book, visit or be contacted",
    "product_question": "A question about the product or service",
    "about_the_person": "About the model, actor or presenter, not the product",
    "praise_or_emoji": "General praise or emojis",
    "other": "Something else (tags, spam, unrelated)",
}

REDIRECT = re.compile(r"\b(dm|inbox|direct message|whats ?app|call us|message us|"
                      r"check your (dm|messages|inbox)|contact us)\b", re.I)

SCHEMA = {
    "type": "object",
    "properties": {"accounts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "handle": {"type": "string"},
            **{k: {"type": "integer"} for k in KINDS},
            "examples": {"type": "array", "items": {
                "type": "object",
                "properties": {"kind": {"type": "string", "enum": list(KINDS)},
                               "text": {"type": "string"}},
                "required": ["kind", "text"], "additionalProperties": False}},
            "read": {"type": "string"},
        },
        "required": ["handle", *KINDS, "examples", "read"],
        "additionalProperties": False,
    }}},
    "required": ["accounts"],
    "additionalProperties": False,
}

SYSTEM = """You sort Instagram comments by what they reveal about the people
leaving them, for a business studying its competitors. Each account's comments
are listed one per line.

For each account, count how many comments fall in each kind (every comment in
exactly one):
- price_or_buying: asking the price or how to buy. In India "Pp", "pp",
  "price pls", "rate?", "cost?", "available?" all mean this.
- booking_or_visit: wants an appointment, to visit, or to be called back.
- product_question: asks about the product or service itself (size, material,
  treatment, timing) without asking the price.
- about_the_person: about the model, actor, presenter or doctor's looks or
  acting, not about what is being sold ("you look stunning", "acting super").
- praise_or_emoji: general praise, emojis, "nice", "beautiful".
- other: tags of friends, spam, unrelated.

examples: up to 3 short quotes (verbatim, shortened if long) that best show the
kinds that matter most - buying intent and comments about the person.
read: one plain sentence on what these comments say about whether the account
is reaching buyers. Use the counts. No jargon."""


class CommentRead(BaseModel):
    handle: str
    sampled: int = 0               # comments from other people that were read
    counts: dict[str, int] = Field(default_factory=dict)
    examples: list[dict] = Field(default_factory=list)
    read: str = ""
    owner_replies: int = 0         # replies by the account itself
    redirects: int = 0             # ...of which point to DM / WhatsApp / a call
    skipped: str = ""


def _comments(a: Account) -> tuple[list[str], int, int]:
    """(other people's comment texts, owner replies, owner redirects)."""
    mine = a.handle.lower()
    texts: list[str] = []
    owner = redirects = 0

    def visit(c: dict) -> None:
        nonlocal owner, redirects
        text = " ".join((c.get("text") or "").split())
        who = (c.get("ownerUsername") or "").lower()
        if who == mine:
            owner += 1
            redirects += bool(REDIRECT.search(text))
        elif text:
            texts.append(text[:200])
        for r in c.get("replies") or []:
            if isinstance(r, dict):
                visit(r)

    for p in sorted(a.posts, key=lambda p: p.get("timestamp") or "", reverse=True):
        for c in p.get("latestComments") or []:
            if isinstance(c, dict):
                visit(c)
    return texts[:PER_ACCOUNT], owner, redirects


def read_comments(accounts: list[Account],
                  progress: Callable[[str], None] = print) -> dict[str, CommentRead]:
    out: dict[str, CommentRead] = {}
    lines: list[str] = []
    for a in accounts:
        if a.error:
            continue
        texts, owner, redirects = _comments(a)
        out[a.handle.lower()] = CommentRead(handle=a.handle, sampled=len(texts),
                                            owner_replies=owner, redirects=redirects)
        if texts:
            lines.append(f"\n@{a.handle} ({len(texts)} comments):")
            lines += [f"- {t}" for t in texts]
        else:
            out[a.handle.lower()].skipped = "no comments came back for this account"

    if not lines:
        progress("No comments to read.")
        return out
    try:
        got = complete_json(SYSTEM, "\n".join(lines), schema=SCHEMA,
                            list_key="accounts", required_field="handle",
                            model=config.light_model, temperature=1.0, effort="low")
    except Exception as e:
        progress(f"Comment reading failed, carrying on without it: {e}")
        for c in out.values():
            c.skipped = c.skipped or "comment reading failed"
        return out
    for row in got.get("accounts", []):
        c = out.get(str(row.get("handle", "")).lstrip("@").lower())
        if c is None:
            continue
        c.counts = {k: int(row.get(k) or 0) for k in KINDS}
        c.examples = [e for e in row.get("examples") or [] if isinstance(e, dict)][:3]
        c.read = row.get("read") or ""
    progress(f"Read {sum(c.sampled for c in out.values())} comments.")
    return out
