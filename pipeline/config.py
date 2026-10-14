"""Settings, read from .env once at import.

APIFY_TOKEN and COMPETITOR_DIR are read directly by `report.py` and
`find_competitors.py` via os.getenv, so they are not repeated here.

ONE MODEL PER JOB

Each job uses the cheapest model that matched the top model in a side-by-side
test on real data (temp/6_model_test, October 2026):

  job                         model     test result
  naming competitors          Opus      Sonnet missed the right-tier local peers
  understanding the client    Opus      decides local vs online; mistakes spread
  checking candidates         Sonnet    29/30 same labels as Opus
  labelling post images       Sonnet    12/12 same as Opus (Haiku 6/12)
  reading comments, terms     Haiku     same conclusions as Opus
  patterns, ideas, plan       Opus      the written analysis the client reads
  the Conra AI section        Sonnet

Any of them can be overridden in .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    # Patterns, content ideas, competitor write-ups and the month's plan.
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", OPUS)
    # Understanding the client and naming competitors with web search.
    discovery_model: str = os.getenv("DISCOVERY_MODEL", OPUS)
    # Checking each candidate competitor against the client.
    check_model: str = os.getenv("CHECK_MODEL", SONNET)
    # Reading what is in each post's image.
    vision_model: str = os.getenv("VISION_MODEL", SONNET)
    # Comments, search terms, the brief draft: reading, not judgement.
    light_model: str = os.getenv("LIGHT_MODEL", HAIKU)
    # The Conra AI section.
    analysis_model: str = os.getenv("ANALYSIS_MODEL", SONNET)


config = Config()
