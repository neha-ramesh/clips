"""The client brief: the business facts the report opens with.

The hand-written audits open with a table — brand, legacy, stores, products,
average ticket, customers, positioning, partnerships, languages — and the rest
of the audit leans on it: "Bhima is a national group; Davanam's real peers are
the three-store Bangalore jewellers", "never show prices", "Dental Council of
India ethics". Most of it comes from the client, not from Instagram.

So the brief is a form. `draft` fills what it can from the Instagram profile and
the website so the user corrects rather than types; everything else — how the
business actually makes money, the hard content rules, what was said on the
call — only the user can supply, and the report prints those as written.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from .config import config
from .llm import complete_json

# Field -> (label in the dashboard and report, hint). Order is display order.
FIELDS: dict[str, tuple[str, str]] = {
    "brand": ("Brand", "Davanam Jewellers Pvt Ltd"),
    "legacy": ("Legacy", "Since 1905, 4th generation"),
    "locations": ("Stores / locations", "Avenue Road, Commercial Street, Malleshwaram"),
    "geography": ("Geography", "Bangalore only; known across Karnataka"),
    "products": ("Products / services", "Gold, silver, diamond; flagship diamonds"),
    "avg_ticket": ("Average ticket", "~₹50,000"),
    "customer_base": ("Customer base", "30-40K customers in schemes"),
    "positioning": ("Positioning", "Quality & trust since 1905 · IGI certified"),
    "partnerships": ("Key partnerships", "Divine Solitaires, 15 years"),
    "languages": ("Languages", "Kannada, English, Tamil"),
    "audience": ("Ideal customer", "Bridal & milestone buyers, age 30-55"),
    "money": ("How the business makes money", "80-90% referral, rest footfall"),
    "goals": ("Goals", "Brand awareness, followers, walk-ins"),
    "rules": ("Hard content rules", "Never show prices; management approves posts"),
    "brand_look": ("Brand colours & tagline", "Maroon & gold · Quality & Trust Since 1905"),
}
# Only the user can supply these; `draft` leaves them empty.
USER_ONLY = {"avg_ticket", "customer_base", "money", "goals", "rules"}


class Brief(BaseModel):
    brand: str = ""
    legacy: str = ""
    locations: str = ""
    geography: str = ""
    products: str = ""
    avg_ticket: str = ""
    customer_base: str = ""
    positioning: str = ""
    partnerships: str = ""
    languages: str = ""
    audience: str = ""
    money: str = ""
    goals: str = ""
    rules: str = ""
    brand_look: str = ""
    images_per_month: int = 0
    reels_per_month: int = 0
    call_notes: str = ""

    def rows(self) -> list[tuple[str, str]]:
        """(label, value) for every filled field, in display order."""
        return [(FIELDS[k][0], getattr(self, k)) for k in FIELDS
                if getattr(self, k).strip()]

    def as_text(self) -> str:
        """For the model steps that should respect the brief."""
        lines = [f"{label}: {value}" for label, value in self.rows()]
        if self.images_per_month or self.reels_per_month:
            lines.append(f"Agreed volume: {self.images_per_month} images and "
                         f"{self.reels_per_month} reels a month")
        if self.call_notes.strip():
            lines.append(f"Notes from the call: {self.call_notes.strip()}")
        return "\n".join(lines)


DRAFT_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in FIELDS if k not in USER_ONLY},
    "required": [k for k in FIELDS if k not in USER_ONLY],
    "additionalProperties": False,
}

DRAFT_SYSTEM = """You draft the fact sheet that opens a social media audit for a
business, from its Instagram profile, recent captions and website text.

Fill each field only with what the material actually says - quote figures,
years and names as written. Leave a field as "" when the material does not say;
an empty field is corrected by a person, a guessed one misleads a client.
Keep each value under 20 words."""


def draft(profile: dict, site_text: str, *, business: str = "",
          place: str = "") -> Brief:
    posts = profile.get("latestPosts") or []
    material = (
        f"Instagram: @{profile.get('username')} - {profile.get('fullName')}\n"
        f"Bio: {profile.get('biography')}\n"
        f"Category: {profile.get('businessCategoryName')}\n"
        f"Followers: {profile.get('followersCount')}\n"
        "Recent captions:\n" + "\n".join(
            "- " + " ".join((p.get("caption") or "").split())[:200]
            for p in posts[:8])
        + f"\n\nWebsite text:\n{site_text or '(none)'}\n\n"
        f"The user describes it as: {business or '-'}; customers in: {place or '-'}")
    got = complete_json(DRAFT_SYSTEM, material, schema=DRAFT_SCHEMA,
                        list_key="brief", required_field="brand",
                        model=config.check_model, temperature=1.0, effort="low")
    return Brief(**{k: str(v)[:200] for k, v in got.items()
                    if k in FIELDS and k not in USER_ONLY and isinstance(v, str)})


def from_form(values: dict, images: int = 0, reels: int = 0,
              notes: str = "") -> Brief:
    b = Brief(**{k: (values.get(k) or "").strip() for k in FIELDS})
    b.images_per_month, b.reels_per_month = int(images or 0), int(reels or 0)
    b.call_notes = notes or ""
    return b


def empty() -> Brief:
    return Brief()


def merge(a: Optional[Brief], b: Brief) -> Brief:
    """b's filled fields over a's."""
    if a is None:
        return b
    data = a.model_dump()
    for k, v in b.model_dump().items():
        if v not in ("", 0, None):
            data[k] = v
    return Brief(**data)
