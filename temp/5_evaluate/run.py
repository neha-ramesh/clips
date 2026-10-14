"""Score every method with the same yardstick.

1. Take each method's top candidates (and each variant on its own).
2. Look every distinct handle up once (profiles cached in profiles.json).
3. Claude labels each profile against a fixed rubric; labels cached in labels.json.
4. Precision, unique finds and cost per method -> results.md.

Rerunning is free once the caches exist: delete a cache to redo that step.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import (CLIENT, MODEL, ROOT, apify_run, clean, load,  # noqa: E402
                    log_llm_cost, save)

HERE = Path(__file__).resolve().parent
TOP = 25

# --------------------------------------------------------------------------- #
# 1. Candidates per method and variant
# --------------------------------------------------------------------------- #

def top(path: Path, keep=lambda c: True) -> list[str]:
    if not path.exists():
        return []
    out = []
    for c in load(path):
        h = clean(c["handle"])
        if h and h != CLIENT["handle"] and h not in out and keep(c):
            out.append(h)
    return out[:TOP]


methods = {
    "0 baseline (IG suggestions)": top(ROOT / "0_client" / "baseline_candidates.json"),
    "1 hashtags (all)": top(ROOT / "1_hashtags" / "candidates.json"),
    "1a hashtags: client's tags": top(ROOT / "1_hashtags" / "candidates.json",
                                      lambda c: "(client)" in c["why"]),
    "1b hashtags: local tags": top(ROOT / "1_hashtags" / "candidates.json",
                                   lambda c: "(local)" in c["why"]),
    "2 keyword (all)": top(ROOT / "2_keyword_search" / "candidates.json"),
    "2a keyword: city queries": top(ROOT / "2_keyword_search" / "candidates.json",
                                    lambda c: "(city)" in c["why"]),
    "2b keyword: area queries": top(ROOT / "2_keyword_search" / "candidates.json",
                                    lambda c: "(area)" in c["why"]),
    "3 google maps (all)": top(ROOT / "3_google_maps" / "candidates.json"),
    "3a maps: city search": top(ROOT / "3_google_maps" / "candidates.json",
                                lambda c: "city" in c["why"].split(":")[0]),
    "3b maps: area search": top(ROOT / "3_google_maps" / "candidates.json",
                                lambda c: "area" in c["why"].split(":")[0]),
    "4 claude web search": top(ROOT / "4_claude_search" / "candidates.json"),
}
methods = {k: v for k, v in methods.items() if v}
everyone = sorted({h for hs in methods.values() for h in hs})
print(f"{len(everyone)} distinct handles across {len(methods)} method/variants")

# --------------------------------------------------------------------------- #
# 2. Profiles
# --------------------------------------------------------------------------- #

prof_path = HERE / "profiles.json"
profiles: dict[str, dict] = load(prof_path) if prof_path.exists() else {}

kw_raw = ROOT / "2_keyword_search" / "raw.json"
if kw_raw.exists():   # keyword search already returned full profiles
    for rows in load(kw_raw).values():
        for r in rows:
            profiles.setdefault(clean(r.get("username")), r)

missing = [h for h in everyone if h not in profiles]
if missing:
    print(f"looking up {len(missing)} profiles")
    rows = apify_run("apify/instagram-profile-scraper",
                     {"usernames": missing, "resultsLimit": 1},
                     cap_usd=round(len(missing) * 0.0026 + 0.1, 2), label="eval-profiles")
    for r in rows:
        h = clean(r.get("username"))
        if h:
            profiles[h] = r
    for h in missing:   # remember the misses so a rerun does not re-bill them
        profiles.setdefault(h, {"__missing__": True})
    save(prof_path, profiles)


def card(h: str) -> dict:
    p = profiles.get(h) or {}
    if p.get("__missing__") or p.get("error") or not p:
        return {"handle": h, "exists": False}
    posts = p.get("latestPosts") or []
    return {
        "handle": h,
        "exists": True,
        "name": p.get("fullName"),
        "bio": p.get("biography"),
        "category": p.get("businessCategoryName"),
        "business_account": p.get("isBusinessAccount"),
        "followers": p.get("followersCount"),
        "posts": p.get("postsCount"),
        "website": p.get("externalUrl"),
        "recent_captions": [re.sub(r"\s+", " ", (x.get("caption") or ""))[:160]
                            for x in posts[:5]],
        "recent_locations": sorted({x.get("locationName") for x in posts
                                    if x.get("locationName")}),
    }

# --------------------------------------------------------------------------- #
# 3. Labels
# --------------------------------------------------------------------------- #

RUBRIC = f"""You are grading candidate competitors for a client.

Client: @{CLIENT['handle']} - Davanam Jewellers, a retail gold and diamond
jeweller since 1905 with stores on Avenue Road, Commercial Street and in
Malleshwaram, Bangalore.

Label each Instagram profile with exactly one of:
- "direct": a retail jeweller (fine gold / diamond / silver jewellery sold to
  consumers) with a store in Bangalore or clearly serving Bangalore customers.
  National chains with Bangalore stores count.
- "same_trade_other_city": a retail jeweller of the same kind, but its stores
  and customers are evidently elsewhere (another city or country).
- "adjacent": jewellery-related but not a like-for-like competitor -
  manufacturers / brands sold through retailers, wholesalers, imitation or
  fashion jewellery resellers, jewellery influencers, news or media pages.
- "unrelated": not a jewellery business at all.
- "unclear": a jeweller, but the profile gives no way to tell where it sells.

Judge only from the profile given. Location evidence is the bio, captions,
post locations, website and name. Be strict: "direct" needs Bangalore evidence."""

SCHEMA = {
    "type": "object",
    "properties": {"labels": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "handle": {"type": "string"},
            "label": {"type": "string", "enum": ["direct", "same_trade_other_city",
                                                 "adjacent", "unrelated", "unclear"]},
            "city": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["handle", "label", "city", "reason"],
        "additionalProperties": False,
    }}},
    "required": ["labels"],
    "additionalProperties": False,
}

lab_path = HERE / "labels.json"
labels: dict[str, dict] = load(lab_path) if lab_path.exists() else {}
for h in everyone:
    if not card(h)["exists"]:
        labels[h] = {"label": "not_found", "city": "", "reason": "no profile came back"}

todo = [h for h in everyone if h not in labels]
client = anthropic.Anthropic()
for i in range(0, len(todo), 15):
    batch = todo[i:i + 15]
    resp = client.messages.create(
        model=MODEL, max_tokens=16000, system=RUBRIC,
        output_config={"effort": "high",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(
            [card(h) for h in batch], ensure_ascii=False, indent=1)}],
    )
    log_llm_cost(f"eval-judge-{i // 15}", resp.usage)
    text = "".join(b.text for b in resp.content if b.type == "text")
    for row in json.loads(text)["labels"]:
        h = clean(row.pop("handle"))
        if h in batch:
            labels[h] = row
    save(lab_path, labels)

# --------------------------------------------------------------------------- #
# 3b. Second pass on "unclear": add the location evidence the method itself
#     produced. A Maps listing is a Google-verified address; Claude's answer
#     cites a page. The profile-only pass cannot see either, which penalises
#     exactly the two methods that start from outside Instagram.
# --------------------------------------------------------------------------- #

evidence: dict[str, list[str]] = defaultdict(list)
maps_places = ROOT / "3_google_maps" / "places.json"
if maps_places.exists():
    for p in load(maps_places):
        if p["instagram"]:
            evidence[p["instagram"][0]].append(
                f"Google Maps listing: {p['title']} - {p['address']} ({p['category']})")
claude_named = ROOT / "4_claude_search" / "named.json"
if claude_named.exists():
    for r in load(claude_named):
        if r.get("handle"):
            evidence[clean(r["handle"])].append(
                f"Web source {r.get('source_url')}: {r.get('name')} - {r.get('why')}")

lab2_path = HERE / "labels_with_evidence.json"
labels2: dict[str, dict] = load(lab2_path) if lab2_path.exists() else {}
todo2 = [h for h in everyone
         if labels[h]["label"] in ("unclear", "adjacent") and evidence.get(h)
         and h not in labels2]
if todo2:
    resp = client.messages.create(
        model=MODEL, max_tokens=16000,
        system=RUBRIC + "\n\nSome profiles now carry `external_evidence` from "
               "Google Maps listings or web pages. Treat a Maps address as "
               "reliable location evidence; treat a web source as evidence of "
               "what the page is claimed to say.",
        output_config={"effort": "high",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(
            [card(h) | {"external_evidence": evidence[h][:4]} for h in todo2],
            ensure_ascii=False, indent=1)}],
    )
    log_llm_cost("eval-judge-evidence", resp.usage)
    text = "".join(b.text for b in resp.content if b.type == "text")
    for row in json.loads(text)["labels"]:
        h = clean(row.pop("handle"))
        if h in todo2:
            labels2[h] = row
    save(lab2_path, labels2)

# --------------------------------------------------------------------------- #
# 4. Scores
# --------------------------------------------------------------------------- #

def lab(h: str) -> str:
    return labels.get(h, {}).get("label", "unlabelled")


def lab2(h: str) -> str:
    """The label after the evidence pass, where there was one."""
    return labels2.get(h, {}).get("label") or lab(h)


top_level = [k for k in methods if re.match(r"^\d ", k)]
found_by: dict[str, set[str]] = defaultdict(set)
for k in top_level:
    for h in methods[k]:
        found_by[h].add(k)
all_direct = {h for h in everyone if lab2(h) == "direct"}

costs = [json.loads(line) for line in
         (ROOT / "costs.jsonl").read_text(encoding="utf-8").splitlines() if line]


def cost_of(prefixes: tuple[str, ...]) -> float:
    return sum(c.get("usd") or 0 for c in costs if c["label"].startswith(prefixes))


COST = {"0": ("client-profile",), "1": ("hashtags", "client-posts"),
        "2": ("kw:",), "3": ("maps:",), "4": ("claude-search",)}

lines = ["| Method | Candidates | Direct | Other city | Adjacent | Unrelated | Unclear | Not found "
         "| Precision (profile only) | **Precision (with evidence)** | P@10 (evidence) "
         "| Share of all direct found | Found by no other method | Cost |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for k, hs in methods.items():
    c = Counter(lab2(h) for h in hs)
    n = len(hs)
    d1 = sum(1 for h in hs if lab(h) == "direct")
    d2 = c["direct"]
    p10 = sum(1 for h in hs[:10] if lab2(h) == "direct") / min(10, n)
    uniq = (sum(1 for h in hs if lab2(h) == "direct" and found_by[h] == {k})
            if k in top_level else "")
    cost = f"${cost_of(COST[k[0]]):.2f}" if k in top_level else ""
    lines.append(f"| {k} | {n} | {d2} | {c['same_trade_other_city']} | "
                 f"{c['adjacent']} | {c['unrelated']} | {c['unclear']} | "
                 f"{c['not_found']} | {d1 / n:.0%} | **{d2 / n:.0%}** | {p10:.0%} | "
                 f"{d2 / len(all_direct):.0%} | {uniq} | {cost} |")

overlap = Counter(len(found_by[h]) for h in all_direct)
combos = {
    "keyword + maps": ["2 keyword (all)", "3 google maps (all)"],
    "keyword + maps + local hashtags": ["2 keyword (all)", "3 google maps (all)",
                                        "1b hashtags: local tags"],
    "keyword + maps + local hashtags + claude": [
        "2 keyword (all)", "3 google maps (all)", "1b hashtags: local tags",
        "4 claude web search"],
    "all five": top_level,
}
cover = []
for name, ks in combos.items():
    got = {h for k in ks for h in methods.get(k, []) if lab2(h) == "direct"}
    cover.append(f"- {name}: {len(got)} of {len(all_direct)} direct competitors")

summary = ["", "## Overlap", "",
           f"{len(all_direct)} distinct direct competitors in total (with evidence). "
           + ", ".join(f"{n} found by {k} method(s)" for k, n in sorted(overlap.items())),
           ""] + cover

detail = ["", "## Every candidate", "",
          "| Handle | Label | Profile-only label | City | Found by | Reason |",
          "|---|---|---|---|---|---|"]
for h in sorted(everyone, key=lambda h: (lab2(h) != "direct", lab2(h), h)):
    l = labels2.get(h) or labels.get(h, {})
    by = ", ".join(sorted(k.split(" ")[0] for k in methods if h in methods[k]))
    detail.append(f"| @{h} | {lab2(h)} | {lab(h)} | {l.get('city', '')} | {by} | "
                  f"{(l.get('reason') or '').replace('|', '/')} |")

report = "\n".join(
    [f"# Competitor discovery test - @{CLIENT['handle']}", "",
     f"{len(everyone)} distinct candidates, {len(all_direct)} judged direct "
     f"competitors. Top {TOP} per method.", ""] + lines + summary + detail)
(HERE / "results.md").write_text(report, encoding="utf-8")
print("\n".join(lines + summary))
print(f"\ntotal spend so far: ${sum(c.get('usd') or 0 for c in costs):.2f}")
