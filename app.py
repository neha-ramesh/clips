"""Streamlit dashboard: handle in, full competitor audit out.

    streamlit run app.py

Wires the three CLIs into one flow. A customer types their Instagram handle
and either:

  - hands over the competitors they want compared, or
  - clicks 'Find competitors', which searches the web, Google Maps and
    Instagram and checks every candidate (`pipeline/competitors.py`).

Then 'Run the audit' fetches posts, measures, calls the model for content
ideas, and shows the report.

Every number the report shows is computed by `pipeline/scan.py`, which was
checked against real profile grids. Nothing new is calculated here — this file
only orchestrates the existing pipeline and renders it.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pipeline.competitors import find_competitors, is_stale  # noqa: E402
from pipeline.discover import DiscoveryError, check_details  # noqa: E402
from pipeline.scan import (  # noqa: E402
    load_snapshots,
    save_snapshot,
    scan,
)
from report import build  # noqa: E402


st.set_page_config(page_title="Competitor audit", page_icon=":material/dashboard:",
                   layout="wide")

DATA_DIR = Path(os.getenv("COMPETITOR_DIR", "data/competitors"))


def _clean(raw: str) -> str:
    return raw.strip().lstrip("@").lower()


def _split_handles(raw: str) -> list[str]:
    if not raw:
        return []
    parts = raw.replace("\n", ",").replace(" ", ",").split(",")
    return [_clean(p) for p in parts if p.strip()]


def _init_state() -> None:
    for key, default in {
        "discovery": None,
        "accounts": None,
        "ideas": None,
        "stamp": "",
        "client": "",
        "context": {},
        "log": [],
    }.items():
        st.session_state.setdefault(key, default)


_init_state()


st.title("Competitor audit")
st.caption(
    "Type an Instagram handle. Get a month of what the competition posted, "
    "what it earned, and what to make next."
)

apify_token = os.getenv("APIFY_TOKEN", "")
anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

with st.sidebar:
    st.subheader("Credentials")
    if apify_token:
        st.success("APIFY_TOKEN loaded")
    else:
        st.error("APIFY_TOKEN missing. Set it in .env or the environment.")
    if anthropic_key:
        st.success("ANTHROPIC_API_KEY loaded")
    else:
        st.warning("ANTHROPIC_API_KEY missing. The audit still runs; the "
                   "content-ideas section will be skipped.")

    st.divider()
    st.subheader("Scan settings")
    days = st.number_input("Days of history", min_value=7, max_value=90,
                           value=30, step=1)
    limit = st.number_input("Posts per account", min_value=10, max_value=200,
                            value=40, step=5,
                            help="Apify bills per result. 40 covers 30 days "
                                 "for anyone posting under twice a day.")

    st.divider()
    st.subheader("Discovery settings")
    st.caption("'Find competitors' costs about $1–1.50 a run (about $0.40 "
               "Apify, the rest Claude) and takes a few minutes.")
    min_followers = st.number_input("Min followers", min_value=0,
                                    value=0, step=500)
    max_followers = st.number_input("Max followers (0 = no cap)",
                                    min_value=0, value=0, step=1000)


st.subheader("1. Your handle")
client_in = st.text_input(
    "Instagram handle",
    value=st.session_state.get("client_input", ""),
    placeholder="davanam_jewellers",
    help="No @. Public accounts only.",
    key="client_input",
)
client = _clean(client_in) if client_in else ""

c1, c2, c3 = st.columns(3)
with c1:
    business = st.text_input(
        "Business (optional)", placeholder="Bridal gold jewellery",
        help="What they sell, in a few words. The business is worked out from "
             "its profile and website anyway; this helps when those say "
             "little. The content ideas use it too.")
with c2:
    place = st.text_input(
        "City or market (optional)", placeholder="Bangalore",
        help="Where their customers are — a city for a shop, a country or "
             "'global' for software or an online brand.")
with c3:
    website = st.text_input(
        "Website (optional)", placeholder="https://example.com",
        help="Read to understand the business when Instagram says little. "
             "Leave empty to use the link in their Instagram bio.")


col_check, col_find = st.columns(2)

with col_check:
    check_btn = st.button(
        "Check this handle",
        help="One billed lookup (under a cent). Confirms the handle exists "
             "and shows its profile.",
        disabled=not (client and apify_token),
        width="stretch",
    )

with col_find:
    find_btn = st.button(
        "Find competitors for me",
        help="Reads the profile and website to work out what the business "
             "is, then searches the web, Google Maps (for local businesses) "
             "and Instagram, and checks every candidate against the client. "
             "Needs both API keys. About $1–1.50 a run.",
        type="primary",
        disabled=not (client and apify_token and anthropic_key),
        width="stretch",
    )


if check_btn:
    with st.spinner(f"Looking up @{client}..."):
        try:
            info = check_details(apify_token, client)
        except Exception as e:
            st.error(f"Lookup failed: {e}")
            info = None

    if info is not None:
        if not info["found"]:
            st.error("Nothing came back for that handle. Check the spelling "
                     "— no @, no URL, just the username.")
        else:
            followers = info["followers"]
            rel = info["related"]
            badges = []
            if info["verified"]:
                badges.append("verified")
            if info["private"]:
                badges.append("private")
            badge_str = f" · {' · '.join(badges)}" if badges else ""
            st.info(f"@{client} — {followers:,} followers · "
                    f"{info['posts']:,} posts{badge_str}. "
                    f"{len(rel)} suggestions returned.")

            if info["category"] or info["bio"]:
                st.caption(
                    (f"**{info['category']}**. " if info["category"] else "")
                    + (info["bio"] or "")
                )

            if rel:
                st.caption("Instagram suggestions preview: "
                           + ", ".join("@" + h for h in rel[:10]))
                st.success("Handle found. Click 'Find competitors for me'.")
            else:
                st.info(
                    "Handle found, but Instagram returned no suggested "
                    "accounts for it — usually because the owner turned off "
                    "'Show suggested accounts on profile', or the profile is "
                    "private or small. That's fine: suggestions are only one "
                    "of the sources 'Find competitors for me' uses. Web "
                    "search and Google Maps don't depend on them."
                )

                with st.expander("Diagnostic: what actually came back"):
                    st.write({
                        "found": info["found"],
                        "followers": info["followers"],
                        "posts": info["posts"],
                        "private": info["private"],
                        "verified": info["verified"],
                        "category": info["category"],
                        "bio": info["bio"],
                        "related_count": len(info["related"]),
                        "has_relatedProfiles_key":
                            "relatedProfiles" in info["keys"],
                        "profile_keys": info["keys"],
                    })
                    st.caption(
                        "If `has_relatedProfiles_key` is `true` and "
                        "`related_count` is `0`, Instagram itself is "
                        "returning an empty list — case 1 or 2 above. If "
                        "the key is missing entirely, the Apify actor "
                        "dropped it (rare) and the fix is on our side."
                    )


if find_btn:
    with st.status(f"Finding competitors for @{client}...",
                   expanded=True) as status:
        try:
            result = find_competitors(
                apify_token, client, business=business, place=place,
                website=website,
                min_followers=int(min_followers),
                max_followers=int(max_followers),
                progress=st.write,
            )
            status.update(label="Competitor search finished — click to see "
                                "each step", state="complete", expanded=False)
        except DiscoveryError as e:
            status.update(label="Competitor search failed", state="error")
            st.error(f"Discovery failed: {e}")
            result = None
        except Exception as e:
            status.update(label="Competitor search failed", state="error")
            msg = str(e)
            if "hard limit" in msg or "usage" in msg.lower():
                st.error("Apify's monthly credit is spent.")
            else:
                st.error(f"Discovery failed: {e}")
            result = None

    if result is not None:
        st.session_state["discovery"] = result
        rows = result.found
        direct = sum(1 for f in rows if f.label == "direct")
        no_ig = sum(1 for f in rows if f.label == "no_instagram")
        if direct:
            st.success(f"{direct} direct competitors on Instagram"
                       + (f", plus {no_ig} without a usable Instagram"
                          if no_ig else "") + ". Review them below.")
        elif rows:
            st.warning(
                f"None of the {len(rows) - no_ig} Instagram accounts checked "
                "out as a direct competitor"
                + (f" ({no_ig} competitors were found without a usable "
                   "Instagram — listed below)" if no_ig else "")
                + ". Look through the set-aside list — one may be marked "
                "'unclear' only because its profile says little — or type "
                "competitors in the box."
            )
        else:
            st.warning(
                "No candidates came back from any source. What each step "
                "returned:\n\n" + "\n".join(f"- {line}" for line in result.log)
                + "\n\nIf the 'Read as' line is wrong, fill in Business, "
                "City/market or Website above and run it again."
            )


SOURCE_NAMES = {"web": "web search", "maps": "Google Maps",
                "suggested": "Instagram suggestions"}
SET_ASIDE = {"unclear": "Possibly a competitor, not enough to tell",
             "other_market": "Same trade, different market",
             "adjacent": "Related, not like-for-like",
             "unrelated": "Different trade",
             "not_found": "No Instagram account found",
             "": "Not checked"}


def _activity(f) -> str:
    if f.last_post:
        stale = " — quiet lately" if is_stale(f) else ""
        return f"{f.posts:,} posts, last {f.last_post}{stale}"
    return f"{f.posts:,} posts"


def _pick(f, default: bool) -> bool:
    by = ", ".join(SOURCE_NAMES.get(s, s) for s in f.sources)
    label = f"@{f.handle}" + (f" — {f.name}" if f.name else "")
    checked = st.checkbox(label, value=default, key=f"pick_{f.handle}")
    site = f" · [{f.website}]({f.website})" if f.website.startswith("http") else ""
    st.caption(f"{f.followers:,} followers · {_activity(f)} · found by {by}"
               f"{site}. {f.reason}")
    return checked


st.subheader("2. Their competitors")

disc = st.session_state["discovery"]
against_from_picks: list[str] = []
if disc is not None:
    u = disc.understood
    st.info(f"**Read as:** {u.summary}  \n"
            f"{'Online' if u.kind == 'online' else 'Local'} business · "
            f"category: {u.category} · market: {u.market or '?'} · "
            f"confidence: {u.confidence}"
            + (f"  \n_{u.notes}_" if u.notes else ""))
    found = disc.found
    direct = [f for f in found if f.label == "direct"]
    web_only = [f for f in found if f.label == "no_instagram"]
    rest = [f for f in found if f.label not in ("direct", "no_instagram")]
    if direct:
        st.caption("Checked against the client and judged direct competitors. "
                   "Uncheck any that don't fit — the analysis runs on what's "
                   "checked.")
        cols = st.columns(2)
        for i, f in enumerate(direct):
            with cols[i % 2]:
                if _pick(f, True):
                    against_from_picks.append(f.handle)
    if web_only:
        with st.expander(f"Competitors without a usable Instagram "
                         f"({len(web_only)})", expanded=not direct):
            st.caption("Named by web search, but no Instagram account could "
                       "be found for them, so they can't be scanned. Worth "
                       "knowing about all the same. If you know a handle, "
                       "type it in the box below.")
            for f in web_only:
                site = f" — [{f.website}]({f.website})" if f.website.startswith("http") else ""
                st.markdown(f"- **{f.name}**{site}: {f.reason}")
    if rest:
        with st.expander(f"Set aside ({len(rest)}) — tick any you want anyway"):
            for lab, title in SET_ASIDE.items():
                group = [f for f in rest if f.label == lab]
                if not group:
                    continue
                st.markdown(f"**{title}**")
                for f in group:
                    if f.handle and _pick(f, False):
                        against_from_picks.append(f.handle)
    # The ideas section needs a business and a market; fall back to what was
    # read from the profile when the user left them empty.
    business = business or u.category
    place = place or u.market

manual_raw = st.text_area(
    "Or type competitors — comma or line-separated",
    placeholder="tanishqjewellery, kalyanjewellers_official",
    help="Add or override the picks above. Everything listed here gets "
         "included.",
    key="against_manual",
)
manual = _split_handles(manual_raw)

against = list(dict.fromkeys(against_from_picks + manual))
if against:
    st.caption(f"Will scan {len(against)} account(s) alongside @{client or '…'}: "
               + ", ".join("@" + h for h in against))


st.subheader("3. Context for the content ideas")
st.caption("Optional but useful. The ideas section leans on place and "
           "language — a scraper doesn't know the audience is in Chennai and "
           "speaks Tamil. Business and city are taken from step 1.")
c1, c2 = st.columns(2)
with c1:
    language = st.text_input("Audience language",
                             placeholder="English with Kannada festival names")
with c2:
    notes = st.text_input("Anything else worth knowing",
                          placeholder="Storefront on Commercial Street")


st.subheader("4. Run the audit")

reuse_available = False
if client:
    try:
        snaps = load_snapshots(DATA_DIR, client)
        reuse_available = bool(snaps)
    except Exception:
        reuse_available = False

col_run, col_reuse = st.columns([2, 1])

with col_run:
    run_btn = st.button(
        "Run the audit",
        type="primary",
        disabled=not (client and against and apify_token),
        width="stretch",
        help=("Fetches fresh posts, measures, and builds the report. "
              "Cost: about ${:.2f}".format(
                  (len(against) + 1) * float(limit) * 0.0023 if against else 0.0)),
    )

with col_reuse:
    reuse_btn = st.button(
        "Use last scan",
        disabled=not reuse_available,
        width="stretch",
        help=("Rebuild the report from the most recent stored scan, without "
              "fetching. Available once you've scanned this client before."),
    )


def _run_scan() -> None:
    handles = [client] + list(against)
    with st.spinner(f"Fetching {int(limit)} posts each for "
                    f"{len(handles)} account(s)..."):
        try:
            accounts = scan(apify_token, handles,
                            days=int(days), limit=int(limit),
                            verbose=False)
        except Exception as e:
            msg = str(e)
            if "hard limit" in msg or "usage" in msg.lower():
                st.error("Apify's monthly credit is spent.")
            else:
                st.error(f"Scan failed: {e}")
            return

    try:
        path = save_snapshot(accounts, DATA_DIR, client)
        stamp = path.stem.rsplit("_", 1)[-1]
    except Exception as e:
        st.warning(f"Scan ran but the snapshot could not be saved: {e}")
        stamp = datetime.now().strftime("%Y%m%d")

    st.session_state["accounts"] = accounts
    st.session_state["stamp"] = stamp
    st.session_state["client"] = client
    st.session_state["context"] = {
        "Business": business,
        "Customers in": place,
        "Audience language": language,
        "Notes": notes,
    }
    _generate_ideas(accounts)


def _reuse_scan() -> None:
    snaps = load_snapshots(DATA_DIR, client)
    if not snaps:
        st.error(f"No stored scan for @{client}.")
        return
    stamp, accounts = snaps[-1]
    st.session_state["accounts"] = accounts
    st.session_state["stamp"] = stamp
    st.session_state["client"] = client
    st.session_state["context"] = {
        "Business": business,
        "Customers in": place,
        "Audience language": language,
        "Notes": notes,
    }
    _generate_ideas(accounts)


def _generate_ideas(accounts) -> None:
    if not anthropic_key:
        st.session_state["ideas"] = None
        return
    with st.spinner("Reading the winners and losers..."):
        try:
            from pipeline.ideas import suggest as ideas_suggest
            st.session_state["ideas"] = ideas_suggest(
                accounts, client, business=business, place=place,
                language=language, notes=notes, verbose=False,
            )
        except Exception as e:
            st.warning(f"Ideas section unavailable: {e}")
            st.session_state["ideas"] = None


if run_btn:
    _run_scan()

if reuse_btn:
    _reuse_scan()


accounts = st.session_state.get("accounts")
if accounts:
    stamp = st.session_state["stamp"]
    saved_client = st.session_state["client"]
    ideas = st.session_state["ideas"]
    context = st.session_state["context"]

    st.divider()
    st.subheader("Results")

    ok = [a for a in accounts if not a.error]
    failed = [a for a in accounts if a.error]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Accounts scanned", len(ok))
    m2.metric("Posts read", sum(a.post_count for a in ok))
    m3.metric("Window", f"{ok[0].days if ok else int(days)} days")
    m4.metric("Snapshot", stamp)

    if failed:
        with st.expander(f"{len(failed)} account(s) came back empty"):
            for a in failed:
                st.write(f"- @{a.handle}: {a.error[:200]}")

    st.markdown("#### Quick read")
    if ok:
        ok_sorted = sorted(ok, key=lambda a: -a.typical_likes)
        for a in ok_sorted:
            is_client = a.handle.lower() == saved_client.lower()
            label = f"@{a.handle}" + (" — your client" if is_client else "")
            with st.container(border=True):
                cols = st.columns([2, 1, 1, 1])
                cols[0].markdown(f"**{label}**")
                cols[1].metric("Followers", f"{a.followers:,}")
                cols[2].metric("Normal post", f"{a.typical_likes:,.0f} likes")
                cols[3].metric("Best post", f"{a.best_likes:,} likes")
                if a.likes_by_kind:
                    kinds = sorted(a.likes_by_kind.items(), key=lambda x: -x[1])
                    bits = [f"{k}: {v:,.0f}" for k, v in kinds]
                    st.caption(
                        f"{a.post_count} posts · " + " · ".join(bits)
                    )

    st.markdown("#### The full report")
    report_html = build(accounts, saved_client, stamp, DATA_DIR, ideas, context)

    report_path = DATA_DIR / f"{saved_client}_report_{stamp}.html"
    try:
        report_path.write_text(report_html, encoding="utf-8")
    except OSError:
        pass

    st.download_button(
        "Download the report as HTML",
        data=report_html,
        file_name=f"{saved_client}_report_{stamp}.html",
        mime="text/html",
    )

    st.iframe(report_html, height=1600)

else:
    st.info(
        "Ready when you are. Enter a handle, pick competitors (or click "
        "'Find competitors for me'), and hit 'Run the audit'."
    )
