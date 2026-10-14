"""One way to run an Apify actor: capped in money and, when asked, in time.

Every scraper call in the pipeline goes through `run`. The spending cap is a
hard limit Apify enforces. The time cap exists because some actors are slow in
a way that has nothing to do with how much they return — Instagram's search
took 2 to 7 minutes a run in testing, to return ten names. With `timeout_s` the
actor is stopped at that point and whatever it has found so far is used.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Optional


def run(token: str, actor: str, run_input: dict, cap_usd: float,
        timeout_s: Optional[int] = None) -> list[dict]:
    """Run an actor; return its dataset rows (partial if it hit `timeout_s`)."""
    from apify_client import ApifyClient

    client = ApifyClient(token)
    kwargs: dict = {"run_input": run_input, "logger": None,
                    "max_total_charge_usd": Decimal(str(cap_usd))}
    if timeout_s:
        kwargs["run_timeout"] = timedelta(seconds=timeout_s)
    run_ = client.actor(actor).call(**kwargs)
    if run_ is None:
        return []
    d = run_ if isinstance(run_, dict) else run_.model_dump(by_alias=True)
    if not d.get("defaultDatasetId"):
        return []
    listed = client.dataset(d["defaultDatasetId"]).list_items()
    rows = listed.items if hasattr(listed, "items") else listed.get("items", [])
    return [r for r in rows if isinstance(r, dict)]
