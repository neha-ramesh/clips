"""Method 4: Claude with web search names the competitors.

Given only what the dashboard has — handle, business, city, the client's bio —
Claude searches the web and returns competitors with Instagram handles. It is
told to give a handle only when it saw one in a source, and every handle is
checked for existence in 5_evaluate, so an invented one shows up as a miss.

Cost: Opus 5.5 ($4/$20 per M tokens) + $0.01 per web search; ~$0.3-0.8.
"""

import json
import sys
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import CLIENT, MODEL, ROOT, clean, load, log_llm_cost, save  # noqa: E402

from pipeline.llm import _salvage, _strip_fences  # noqa: E402

HERE = Path(__file__).resolve().parent
prof = (load(ROOT / "0_client" / "profile.json") or [{}])[0]

SYSTEM = """You find a local business's direct competitors on Instagram.

A direct competitor sells the same kind of product to the same customers in the
same city: someone choosing the client could plausibly choose them instead.
Not competitors: brands or manufacturers the client stocks, influencers, media
pages, wholesalers that do not sell to the public, and businesses in other
cities.

Use web search. Good sources are Google Maps / Justdial / directory listings,
"best X in <city>" articles, and the businesses' own websites, which usually
link their Instagram. Include a handle only if you saw it in a source - an
instagram.com/<handle> URL or an @handle on the business's site or listing.
Never construct a handle from a business name. If you found a competitor but
not its handle, list it with handle null."""

USER = f"""Client: @{CLIENT['handle']} ({prof.get('fullName') or ''})
Business: {CLIENT['business']}
City: {CLIENT['place']}
Their Instagram bio: {prof.get('biography') or ''!r}

Find up to 20 direct competitors. Reply with JSON only:
{{"competitors": [{{"name": "...", "handle": "... or null",
  "source_url": "where you saw the handle (or the business)",
  "why": "one line: what they sell, where, why they compete"}}]}}"""

client = anthropic.Anthropic()   # ANTHROPIC_API_KEY, loaded from .env by common
messages = [{"role": "user", "content": USER}]
tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 15,
          "user_location": {"type": "approximate", "city": CLIENT["place"],
                            "country": "IN"}}]

transcript = []
for turn in range(5):
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000, system=SYSTEM, messages=messages,
        tools=tools, output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    )
    log_llm_cost(f"claude-search-{turn}", resp.usage)
    transcript.append(resp.to_dict())
    if resp.stop_reason == "refusal":
        sys.exit(f"refused: {resp.stop_details}")
    if resp.stop_reason != "pause_turn":
        break
    # Server tool loop hit its iteration limit; hand the turn back to continue.
    messages = messages + [{"role": "assistant", "content": resp.content}]

save(HERE / "transcript.json", transcript)
text = "".join(b.text for b in resp.content if b.type == "text")
(HERE / "answer.txt").write_text(text, encoding="utf-8")

try:
    rows = json.loads(_strip_fences(text)).get("competitors", [])
except ValueError:
    rows = _salvage(text, "name")

save(HERE / "named.json", rows)
cands = [{"handle": clean(r["handle"]),
          "why": f"{r.get('name')}: {r.get('why')} [{r.get('source_url')}]"}
         for r in rows if r.get("handle") and clean(r["handle"]) != CLIENT["handle"]]
save(HERE / "candidates.json", cands)

print(f"\n{len(rows)} competitors named, {len(cands)} with a handle")
for r in rows:
    print(f"  {r.get('name')!s:40} @{r.get('handle')}  <{r.get('source_url')}>")
