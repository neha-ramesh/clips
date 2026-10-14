"""Shared plumbing for the competitor-discovery experiment.

Each method lives in its own folder and writes `candidates.json`: a ranked list
of {"handle", "why"} rows. `5_evaluate` then looks every candidate up and
judges it, so all four methods are scored by the same yardstick.

Every Apify run is capped with `max_total_charge_usd` and logged to
`temp/costs.jsonl`, because the account is on the $5/month free plan.
"""

from __future__ import annotations

import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
sys.path.insert(0, str(PROJECT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT / ".env")

APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-opus-5-5"

# The test client, and what a user would type into section 3 of the dashboard.
CLIENT = {
    "handle": "davanam_jewellers",
    "business": "Gold and diamond jewellery store",
    "place": "Bangalore",
}


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str),
                    encoding="utf-8")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def clean(handle: str) -> str:
    return (handle or "").strip().lstrip("@").strip("/").lower()


def apify_run(actor: str, run_input: dict, cap_usd: float, label: str) -> list[dict]:
    """Run an actor with a hard spending cap; return its dataset rows."""
    from apify_client import ApifyClient

    client = ApifyClient(APIFY_TOKEN)
    t0 = time.time()
    run = client.actor(actor).call(run_input=run_input,
                                   max_total_charge_usd=Decimal(str(cap_usd)),
                                   logger=None)
    if run is None:
        raise RuntimeError(f"{actor} returned no run")
    run_d = run if isinstance(run, dict) else run.model_dump(by_alias=True)
    ds = run_d.get("defaultDatasetId")
    listed = client.dataset(ds).list_items()
    rows = listed.items if hasattr(listed, "items") else listed.get("items", [])
    rows = [r for r in rows if isinstance(r, dict)]
    usd = run_d.get("usageTotalUsd")
    with open(ROOT / "costs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"label": label, "actor": actor, "rows": len(rows),
                            "usd": usd, "status": run_d.get("status"),
                            "secs": round(time.time() - t0)}) + "\n")
    print(f"  [{label}] {actor}: {len(rows)} rows, ${usd}, {run_d.get('status')}")
    return rows


def log_llm_cost(label: str, usage) -> None:
    """Opus 5.5 list price: $4 in / $20 out per million tokens."""
    i = getattr(usage, "input_tokens", 0) or 0
    o = getattr(usage, "output_tokens", 0) or 0
    searches = getattr(getattr(usage, "server_tool_use", None),
                       "web_search_requests", 0) or 0
    usd = i * 4e-6 + o * 20e-6 + searches * 0.01
    with open(ROOT / "costs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"label": label, "actor": MODEL, "in": i, "out": o,
                            "web_searches": searches, "usd": round(usd, 4)}) + "\n")
    print(f"  [{label}] {MODEL}: {i} in / {o} out / {searches} searches, ~${usd:.3f}")
