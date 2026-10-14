"""Which model is accurate enough for each job? Opus 5.5 vs Sonnet 5.5 vs Haiku 5.5.

Same prompts the pipeline uses, run with each model. A tracker records every
call's tokens and stops before total spend passes BUDGET.

    python temp/6_model_test/run.py vision|comments|judge|naming
"""

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))
from common import APIFY_TOKEN, clean, load, save  # noqa: E402

import anthropic  # noqa: E402

HERE = Path(__file__).resolve().parent
BUDGET = 0.50
LEDGER = HERE / "spend.json"
PRICE = {"claude-opus-5-5": (4, 20), "claude-sonnet-5-5": (2, 10),
         "claude-haiku-5-5": (0.10, 0.50)}
MODELS = list(PRICE)


def spent() -> float:
    return sum(r["usd"] for r in load(LEDGER)) if LEDGER.exists() else 0.0


def record(model: str, usage, label: str) -> None:
    i, o = PRICE[model]
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    usd = (usage.input_tokens * i + usage.output_tokens * o) / 1e6 + searches * 0.01
    rows = load(LEDGER) if LEDGER.exists() else []
    rows.append({"label": label, "model": model, "in": usage.input_tokens,
                 "out": usage.output_tokens, "searches": searches, "usd": round(usd, 5)})
    save(LEDGER, rows)
    print(f"    [{label}] {model}: {usage.input_tokens} in / {usage.output_tokens} out"
          f"{f' / {searches} searches' if searches else ''} = ${usd:.4f}"
          f"   (total ${spent():.3f})")


class Tracked(anthropic.Anthropic):
    """Records usage of every call; refuses a call once the budget is used up."""
    label = "?"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        for res in (self.messages, self.beta.messages):
            orig = res.create

            def create(_orig=orig, **kw):
                if spent() >= BUDGET - 0.02:
                    raise RuntimeError(f"budget reached (${spent():.3f})")
                r = _orig(**kw)
                record(kw["model"], r.usage, Tracked.label)
                return r
            res.create = create


anthropic.Anthropic = Tracked

from pipeline import competitors, comments, llm, visual  # noqa: E402
from pipeline.config import config  # noqa: E402


def with_model(model: str) -> None:
    """Point every pipeline step at one model for the next call."""
    ns = types.SimpleNamespace(**{k: getattr(config, k) for k in
                                  ("anthropic_api_key", "anthropic_model")},
                               discovery_model=model, analysis_model=model)
    for mod in (visual, comments, competitors, llm):
        mod.config = ns


# --------------------------------------------------------------------------- #

def test_vision() -> None:
    from pipeline import media
    from pipeline.scan import Account

    handle = "abarantimelessjewellery"
    cache = HERE / "vision_profile.json"
    if not cache.exists():
        prof = competitors._profiles(APIFY_TOKEN, [handle])[handle]
        save(cache, prof)
    prof = load(cache)
    posts = prof.get("latestPosts") or []
    a = Account(handle=handle, followers=int(prof.get("followersCount") or 0), posts=posts)
    saved, missing = media.fetch_thumbs([a], HERE)
    print(f"  images: {saved} saved now, {missing} failed, {len(posts)} posts")
    out = {}
    for m in MODELS:
        with_model(m)
        Tracked.label = "vision"
        look = visual.look_at(a, HERE)
        out[m] = {k: v.model_dump() for k, v in look.posts.items()}
        out[m]["_presenter"] = look.presenter
    save(HERE / "vision.json", out)
    keys = [k for k in out[MODELS[0]] if not k.startswith("_")]
    print(f"\n  {'post':14} " + " ".join(f"{m.split('-')[1]:>22}" for m in MODELS))
    agree = {m: 0 for m in MODELS[1:]}
    for k in keys:
        cells = [out[m].get(k, {}).get("format", "-") for m in MODELS]
        for m, c in zip(MODELS[1:], cells[1:]):
            agree[m] += c == cells[0]
        print(f"  {k:14} " + " ".join(f"{c:>22}" for c in cells))
        print(f"  {'':14} " + " | ".join((out[m].get(k, {}).get('describe') or '')[:40]
                                        for m in MODELS))
    print("\n  agreement with Opus:", {m: f"{v}/{len(keys)}" for m, v in agree.items()})
    print("  presenter:", {m: out[m]['_presenter'] for m in MODELS})


def test_comments() -> None:
    from pipeline.scan import load_snapshots
    _, accounts = load_snapshots(ROOT.parent / "data" / "competitors", "davanam_jewellers")[-1]
    one = [a for a in accounts if a.handle == "praveenjewellers_bangalore"]
    out = {}
    for m in MODELS:
        with_model(m)
        Tracked.label = "comments"
        got = comments.read_comments(one, progress=lambda s: None)
        c = got["praveenjewellers_bangalore"]
        out[m] = {"counts": c.counts, "read": c.read, "examples": c.examples}
        print(f"\n  {m}: {c.counts}\n    read: {c.read}\n    examples: {c.examples}")
    save(HERE / "comments.json", out)


def test_judge() -> None:
    """Sonnet and Haiku on 30 candidates, against the Opus labels from 5_evaluate."""
    ev = ROOT / "5_evaluate"
    profiles, labels = load(ev / "profiles.json"), load(ev / "labels.json")
    labels2 = load(ev / "labels_with_evidence.json")
    pick = [h for h in sorted(labels) if labels[h]["label"] != "not_found"
            and profiles.get(h) and not profiles[h].get("error")][::4][:30]
    ref = {h: (labels2.get(h) or labels[h])["label"] for h in pick}
    ref = {h: {"same_trade_other_city": "other_market"}.get(v, v) for h, v in ref.items()}
    u = competitors.Understanding(
        summary="Davanam Jewellers: retail gold and diamond jeweller since 1905, "
                "3 stores in Bangalore (Avenue Road, Commercial Street, Malleshwaram)",
        kind="local", category="fine gold and diamond jewellery retail",
        customers="Bangalore families, bridal and milestone buyers",
        market="Bangalore")
    client = {"handle": "davanam_jewellers", "name": "Davanam Jewellers Pvt Ltd"}
    cards = [competitors._card(h, profiles[h], [], "") for h in pick]
    out = {"opus (reference)": ref}
    for m in MODELS[1:]:
        with_model(m)
        Tracked.label = "judge"
        got = competitors._judge(client, u, cards)
        out[m] = {h: got.get(h, {}).get("label", "?") for h in pick}
    save(HERE / "judge.json", out)
    for m in MODELS[1:]:
        same = sum(out[m][h] == ref[h] for h in pick)
        d_ref = {h for h in pick if ref[h] == "direct"}
        d_m = {h for h in pick if out[m][h] == "direct"}
        print(f"\n  {m}: same label {same}/{len(pick)}; 'direct' — "
              f"agreed {len(d_ref & d_m)}, missed {len(d_ref - d_m)}, extra {len(d_m - d_ref)}")
        for h in pick:
            if out[m][h] != ref[h]:
                print(f"     @{h:34} opus={ref[h]:13} {m.split('-')[1]}={out[m][h]}")


def test_naming() -> None:
    """Sonnet with web search, against Opus's list from 4_claude_search."""
    competitors.WEB_SEARCHES = 8
    u = competitors.Understanding(
        summary="Retail gold and diamond jeweller since 1905 with 3 Bangalore stores",
        kind="local", category="fine gold and diamond jewellery retail",
        customers="Bangalore families; bridal and milestone buyers; ~Rs 50,000 ticket",
        market="Bangalore (Avenue Road, Commercial Street, Malleshwaram)")
    with_model("claude-sonnet-5-5")
    Tracked.label = "naming"
    named = competitors._web_named("davanam_jewellers", "Davanam Jewellers Pvt Ltd", u)
    save(HERE / "naming_sonnet.json", named)
    opus = load(ROOT / "4_claude_search" / "named.json")
    print(f"\n  OPUS ({len(opus)}): " + "; ".join(r["name"] for r in opus))
    print(f"\n  SONNET ({len(named)}): " + "; ".join(
        f"{r['name']}{' @' + r['handle'] if r.get('handle') else ''}" for r in named))


if __name__ == "__main__":
    {"vision": test_vision, "comments": test_comments, "judge": test_judge,
     "naming": test_naming}[sys.argv[1]]()
    print(f"\n  TOTAL SPENT SO FAR: ${spent():.3f} of ${BUDGET}")
