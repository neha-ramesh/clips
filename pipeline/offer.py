"""How Conra AI can help: the audit's findings, matched to what CONRA does.

The facts below are from conraai.com (read October 2026). Edit them here when
the product or pricing changes — this is the only place they live.

THE RULE THAT KEEPS THIS HONEST

CONRA makes carousel posts: plans the month, writes and designs in the brand's
style, waits for approval, publishes on schedule, and shows when posts do best.
It does not shoot or edit reels, run ads, automate DMs or manage a Google
Business Profile. The audits often find that real people on camera and reels
are what work — so the section has to say plainly which findings CONRA answers
and which it does not. A pitch that claims everything is the quickest way to
lose a client who has just read twenty pages of careful evidence.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .config import config
from .llm import complete_json

CONRA = """CONRA AI - "Turn your ideas into high-converting carousels."
"Strategy. Design. Content. All in one place." Built for creators, coaches,
consultants and businesses. "This is not another design tool. It's your
content team."

How it works (three clicks a month):
1. Plans your month - a theme for every posting day.
2. Writes and designs - in your tone, colours and logo.
3. You approve first - nothing goes out until you say so.
4. Posts on schedule - approved posts publish at your chosen times.

Features:
- Monthly content calendar: themes planned, every post on one calendar.
- Brand Kit: tone of voice, audience, offerings, colours and logo.
- Scheduled publishing to Instagram, Facebook, LinkedIn and X.
- Post analytics: shows when posts get the most engagement.
- Inspiration library: paste an Instagram carousel link to capture its
  colours, type, layout and mood, then build a post in that style.
- Story structures: Storytelling, PAS, Myth vs truth, AIDA, List and how-to,
  BAB, or Auto.
- Editing and versions: change themes or slide text, restore earlier versions.
- Media uploads: use your own photos, including a person as a brand avatar.
Time saved: 13 posts a month take about 9 h 45 min by hand vs 26 min.

Plans (INR a month + 18% GST), 14-day free trial, no card, no autopay:
- Starter Rs 3,499: 8 carousels, 5 slides, 1 social account.
- Pro Rs 8,999 (launch offer; regularly 9,399): 25 carousels, 7 slides,
  3 accounts, priority support.
- Scale Rs 12,999 (launch offer; regularly 14,199): 30 carousels, 10 slides,
  5 accounts, weekly strategy call, priority support.

Does NOT do: reels or video, ads, DM or comment automation, Google Business
Profile, review collection, influencer work.

Contact: hello@conraai.com · WhatsApp +91 80975 42858 · conraai.com"""

CONTACT = {"email": "hello@conraai.com", "whatsapp": "https://wa.me/918097542858",
           "site": "https://conraai.com"}

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "fits": {"type": "array", "items": {
            "type": "object",
            "properties": {"finding": {"type": "string"},
                           "feature": {"type": "string"},
                           "how": {"type": "string"}},
            "required": ["finding", "feature", "how"],
            "additionalProperties": False}},
        "plan": {"type": "string", "enum": ["Starter", "Pro", "Scale"]},
        "plan_why": {"type": "string"},
    },
    "required": ["headline", "fits", "plan", "plan_why"],
    "additionalProperties": False,
}

SYSTEM = f"""You write the closing section of a social media audit: how CONRA
AI can help this business. You get the audit's findings and the client brief.

What CONRA is and does, the only facts you may use:
{CONRA}

Write:
- headline: one sentence tying CONRA to this client's main problem.
- fits: 3-6 findings from the audit that CONRA directly addresses. For each,
  quote or closely paraphrase the finding, name the CONRA feature, and say in
  one or two plain sentences how it fixes that problem for this client. Use the
  audit's own numbers. Only claim what the feature list says.
- plan: Starter, Pro or Scale, from the agreed monthly volume and the number
  of platforms (Instagram + Facebook is 2 accounts). plan_why: one line.

Plain words for a business owner. No hype, no exclamation marks."""


class Fit(BaseModel):
    finding: str = ""
    feature: str = ""
    how: str = ""


class Offer(BaseModel):
    headline: str = ""
    fits: list[Fit] = Field(default_factory=list)
    not_covered: list[str] = Field(default_factory=list)
    plan: str = ""
    plan_why: str = ""


def pitch(findings: str, brief_text: str) -> Offer:
    got = complete_json(SYSTEM, f"CLIENT BRIEF:\n{brief_text or '(none)'}\n\n"
                        f"AUDIT FINDINGS:\n{findings}",
                        schema=SCHEMA, list_key="fits", required_field="feature",
                        model=config.analysis_model, temperature=1.0, effort="medium")
    return Offer(
        headline=got.get("headline") or "",
        fits=[Fit(**{k: str(f.get(k) or "") for k in ("finding", "feature", "how")})
              for f in got.get("fits") or [] if isinstance(f, dict)],
        plan=got.get("plan") or "",
        plan_why=got.get("plan_why") or "",
    )
