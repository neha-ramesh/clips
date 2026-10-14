"""Settings, read from .env once at import.

Four settings, because the audit does four things: fetch posts, fetch profiles,
write the patterns, write the ideas. The version this replaces carried fifty —
transcription backends, ffmpeg paths, Vizard templates, Drive credentials —
because it was shared with a video pipeline. None of it was read here, and a
file full of settings that do nothing makes it hard to see which ones matter.

APIFY_TOKEN and COMPETITOR_DIR are read directly by `report.py` and
`find_competitors.py` via os.getenv, so they are not repeated here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    # The one model call in the whole audit: pipeline/ideas.py, which reads the
    # winning and losing captions and writes the patterns and content ideas.
    # Everything else is arithmetic and needs no model at all.
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
    # Competitor discovery (pipeline/competitors.py): names competitors with
    # web search and grades every candidate. Kept separate from the ideas model
    # because discovery was tested on this one.
    discovery_model: str = os.getenv("DISCOVERY_MODEL", "claude-opus-5-5")


config = Config()