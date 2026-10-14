"""Streamlit dashboard: handle in, full competitor audit out.

    streamlit run app.py

Three steps, one screen each, one main button each:

  1. Client       the handle, and optional details for the report
  2. Competitors  found for you (pipeline/competitors.py) or typed in
  3. Report       the audit, in tabs, with a download

Settings live in the sidebar, out of the way. Each long step shows a checklist
of what it is doing, with the time so far.

Every number the report shows is computed by `pipeline/`; this file only
orchestrates it and renders it.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pipeline import brief as brief_mod  # noqa: E402
from pipeline.audit import Options, enrich, make_offer  # noqa: E402
from pipeline.audit import load as load_extras  # noqa: E402
from pipeline.competitors import find_competitors, is_stale  # noqa: E402
from pipeline.discover import DiscoveryError, check_details  # noqa: E402
from pipeline.scan import load_snapshots, save_snapshot, scan_fast  # noqa: E402
from report import build  # noqa: E402

st.set_page_config(page_title="Social media audit", page_icon=":material/dashboard:",
                   layout="wide")

DATA_DIR = Path(os.getenv("COMPETITOR_DIR", "data/competitors"))
apify_token = os.getenv("APIFY_TOKEN", "")
anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

# Widget values vanish when their step is not on screen, so everything a later
# step needs is copied here when the user moves on.
DEFAULTS = {"step": 1, "inputs": {}, "brief": None, "discovery": None,
            "accounts": None, "ideas": None, "extras": None, "stamp": "",
            "client": "", "context": {}, "log": [], "took": 0.0}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)
S = st.session_state


def _clean(raw: str) -> str:
    return (raw or "").strip().lstrip("@").lower()


def _split_handles(raw: str) -> list[str]:
    parts = (raw or "").replace("\n", ",").replace(" ", ",").split(",")
    return [_clean(p) for p in parts if p.strip()]


def _go(step: int) -> None:
    S["step"] = step
    st.rerun()


def _restore(key: str, saved_key: str) -> None:
    """Put a saved value back into a widget before it is drawn."""
    if key not in S and S["inputs"].get(saved_key):
        S[key] = S["inputs"][saved_key]


class Clock:
    """Progress lines with the time so far: '0:42  Reading comments...'.

    Steps that run side by side report from worker threads, where Streamlit
    cannot draw. Those lines are kept and shown at the next update from the
    page's own thread.
    """

    def __init__(self) -> None:
        self.t0 = time.time()
        self.lines: list[str] = []
        self.shown = 0
        self.home = threading.current_thread()

    def __call__(self, msg: str) -> None:
        s = int(time.time() - self.t0)
        self.lines.append(f"`{s // 60}:{s % 60:02d}`  {msg}")
        if threading.current_thread() is self.home:
            for line in self.lines[self.shown:]:
                st.write(line)
            self.shown = len(self.lines)

    @property
    def took(self) -> float:
        return time.time() - self.t0


# --------------------------------------------------------------------------- #
# Sidebar: status and settings, out of the way
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.markdown("**Keys**  " + ("✅ Apify" if apify_token else "❌ Apify")
                + " · " + ("✅ Claude" if anthropic_key else "❌ Claude"))
    if not apify_token:
        st.caption("Set APIFY_TOKEN in .env.")
    if not anthropic_key:
        st.caption("Set ANTHROPIC_API_KEY in .env — without it there are no "
                   "ideas or competitor search.")
    if st.button("Start a new audit", width="stretch"):
        for k in list(S.keys()):
            del S[k]
        st.rerun()

    with st.expander("Settings"):
        days = st.number_input("Days of history", 7, 90, 30, 1)
        limit = st.number_input("Most posts per account", 10, 200, 40, 5,
                                help="Only for accounts posting more than 12 times "
                                     "in the window; the rest come free with "
                                     "their profile.")
        min_followers = st.number_input("Competitors: min followers", 0, value=0, step=500)
        max_followers = st.number_input("Competitors: max followers (0 = no cap)",
                                        0, value=0, step=1000)
        st.markdown("**Extra checks in the audit**")
        opt_visual = st.checkbox("What's in each post", value=True,
                                 help="Each post's image sorted: a person on "
                                      "camera, the product alone, a poster… ~$0.15")
        opt_comments = st.checkbox("What the comments say", value=True, help="< $0.01")
        opt_visibility = st.checkbox("Search visibility", value=True,
                                     help="Free after competitor search; ~$0.10 otherwise.")
        opt_facebook = st.checkbox("Facebook", value=True, help="~$0.15")
        opt_ads = st.checkbox("Running ads (experimental)", value=True, help="~$0.05")

# --------------------------------------------------------------------------- #
# Header: where you are
# --------------------------------------------------------------------------- #

st.title("Social media audit")
steps = ["Client", "Competitors", "Report"]
cols = st.columns(3)
for i, (col, name) in enumerate(zip(cols, steps), 1):
    mark = "✅" if S["step"] > i else ("🔵" if S["step"] == i else "⚪")
    col.markdown(f"{mark} **{i}. {name}**" if S["step"] == i else f"{mark} {i}. {name}")
st.divider()


# --------------------------------------------------------------------------- #
# Step 1: the client
# --------------------------------------------------------------------------- #

def _draft_brief(handle: str, website: str, business: str, place: str) -> None:
    """Fill the brief fields from the profile and website. Runs before the
    fields are drawn — the only time Streamlit lets them be set."""
    from pipeline.competitors import _client_site, _profiles, _site_text
    with st.spinner(f"Reading @{handle}'s profile and website..."):
        try:
            prof = _profiles(apify_token, [handle]).get(handle)
            if not prof:
                st.error(f"No profile came back for @{handle}.")
                return
            site = _client_site(prof, website)
            got = brief_mod.draft(prof, _site_text(site) if site else "",
                                  business=business, place=place)
        except Exception as e:
            st.error(f"Could not draft the details: {e}")
            return
    for k in brief_mod.FIELDS:
        if getattr(got, k):
            S[f"brief_{k}"] = getattr(got, k)
    st.success("Drafted from their profile and website. Check it, and add what "
               "only the client knows.")


def _save_step1(handle, business, place, website) -> None:
    S["inputs"] = {"handle": handle, "business": business, "place": place,
                   "website": website, "language": S.get("w_language", ""),
                   **{f"brief_{k}": S.get(f"brief_{k}", "") for k in brief_mod.FIELDS},
                   "brief_images": S.get("brief_images", 0),
                   "brief_reels": S.get("brief_reels", 0),
                   "brief_notes": S.get("brief_notes", "")}
    S["brief"] = brief_mod.from_form(
        {k: S.get(f"brief_{k}", "") for k in brief_mod.FIELDS},
        S.get("brief_images", 0), S.get("brief_reels", 0), S.get("brief_notes", ""))


def step_client() -> None:
    st.subheader("Who is the client?")
    for key, saved in (("w_handle", "handle"), ("w_business", "business"),
                       ("w_place", "place"), ("w_website", "website"),
                       ("w_language", "language")):
        _restore(key, saved)
    for k in [*(f"brief_{f}" for f in brief_mod.FIELDS), "brief_images",
              "brief_reels", "brief_notes"]:
        _restore(k, k)

    handle = _clean(st.text_input("Instagram handle", key="w_handle",
                                  placeholder="davanam_jewellers"))
    c1, c2, c3 = st.columns(3)
    business = c1.text_input("What they sell (optional)", key="w_business",
                             placeholder="Bridal gold jewellery")
    place = c2.text_input("City or market (optional)", key="w_place",
                          placeholder="Bangalore")
    website = c3.text_input("Website (optional)", key="w_website",
                            placeholder="https://example.com")
    st.caption("Only the handle is needed. The rest is read from their profile "
               "and website; fill it in when those say little.")

    with st.expander("Details for the report (optional) — brief, rules, call notes"):
        if st.button("Draft these from their profile & website",
                     disabled=not (handle and apify_token and anthropic_key),
                     help="A few cents."):
            _draft_brief(handle, website, business, place)
        cols = st.columns(2)
        for i, (k, (label, hint)) in enumerate(brief_mod.FIELDS.items()):
            cols[i % 2].text_input(label, key=f"brief_{k}", placeholder=hint)
        v1, v2, v3 = st.columns(3)
        v1.number_input("Images a month", 0, key="brief_images")
        v2.number_input("Reels a month", 0, key="brief_reels")
        v3.text_input("Audience language", key="w_language",
                      placeholder="English with Kannada")
        st.text_area("Notes from the call", key="brief_notes", height=120,
                     help="Printed in the report as written.")

    with st.expander("Not sure the handle is right? Check it (under a cent)"):
        if st.button("Check handle", disabled=not (handle and apify_token)):
            try:
                info = check_details(apify_token, handle)
                if info["found"]:
                    st.success(f"@{handle} — {info['followers']:,} followers, "
                               f"{info['posts']:,} posts. {info['bio']}")
                else:
                    st.error("Nothing came back. No @, no URL, just the username.")
            except Exception as e:
                st.error(f"Lookup failed: {e}")

    st.write("")
    a, b = st.columns([2, 1])
    find = a.button("Find competitors for me  ·  ~4–7 min, ~$1.40", type="primary",
                    width="stretch",
                    disabled=not (handle and apify_token and anthropic_key))
    manual = b.button("I'll type the competitors", width="stretch",
                      disabled=not handle)
    if manual:
        _save_step1(handle, business, place, website)
        S["discovery"] = None
        _go(2)
    if find:
        _save_step1(handle, business, place, website)
        clock = Clock()
        with st.status(f"Finding competitors for @{handle}...", expanded=True) as box:
            try:
                S["discovery"] = find_competitors(
                    apify_token, handle, business=business, place=place,
                    website=website, min_followers=int(min_followers),
                    max_followers=int(max_followers), progress=clock)
                box.update(label=f"Found them in {clock.took / 60:.1f} min",
                           state="complete")
            except DiscoveryError as e:
                box.update(label="Competitor search failed", state="error")
                st.error(str(e))
                return
            except Exception as e:
                box.update(label="Competitor search failed", state="error")
                msg = str(e)
                st.error("Apify's monthly credit is spent." if "hard limit" in msg
                         or "usage" in msg.lower() else f"Something went wrong: {e}")
                return
        _go(2)


# --------------------------------------------------------------------------- #
# Step 2: the competitors
# --------------------------------------------------------------------------- #

SOURCE = {"web": "web search", "maps": "Google Maps", "suggested": "Instagram suggestions"}
ASIDE = {"unclear": "Possibly a competitor, not enough to tell",
         "other_market": "Same trade, different market",
         "adjacent": "Related, not like-for-like",
         "unrelated": "Different trade", "not_found": "No Instagram account"}


def _pick(f, default: bool) -> bool:
    label = f"@{f.handle}" + (f" — {f.name}" if f.name else "")
    on = st.checkbox(label, value=default, key=f"pick_{f.handle}")
    quiet = " · quiet lately" if is_stale(f) else ""
    st.caption(f"{f.followers:,} followers{quiet} · "
               f"{', '.join(SOURCE.get(s, s) for s in f.sources)}. {f.reason}")
    return on


def _run_audit(client: str, against: list[str], reuse_only: bool = False) -> None:
    """Scan, extra checks, ideas, plan, offer — with a checklist and timings."""
    inp, brief, disc = S["inputs"], S["brief"] or brief_mod.empty(), S["discovery"]
    business = inp.get("business") or (disc.understood.category if disc else "") or brief.products
    place = inp.get("place") or (disc.understood.market if disc else "")
    local = disc.understood.kind != "online" if disc else True
    clock = Clock()
    with st.status("Running the audit...", expanded=True) as box:
        if reuse_only:
            snaps = load_snapshots(DATA_DIR, client)
            stamp, accounts = snaps[-1]
            clock(f"Using the scan from {stamp}.")
            extras = load_extras(DATA_DIR, client, stamp)
        else:
            clock(f"Reading {len(against) + 1} accounts...")
            try:
                accounts = scan_fast(apify_token, [client] + against, days=int(days),
                                     limit=int(limit),
                                     profiles=disc.profiles if disc else None,
                                     progress=clock)
            except Exception as e:
                box.update(label="The scan failed", state="error")
                st.error(f"Scan failed: {e}")
                return
            try:
                stamp = save_snapshot(accounts, DATA_DIR, client).stem.rsplit("_", 1)[-1]
            except Exception:
                stamp = datetime.now().strftime("%Y%m%d")
            reuse = ({"ig_search": disc.ig_search, "search_terms": disc.search_terms,
                      "maps_places": disc.maps_places, "client_place": disc.client_place}
                     if disc else None)
            extras = enrich(
                apify_token, accounts, client, stamp, DATA_DIR, business=business,
                place=place, local=local, locations=brief.locations,
                options=Options(visual=opt_visual and bool(anthropic_key),
                                comments=opt_comments and bool(anthropic_key),
                                visibility=opt_visibility, facebook=opt_facebook,
                                ads=opt_ads),
                reuse=reuse, progress=clock)

        ideas = None
        if anthropic_key:
            from pipeline.ideas import plan as ideas_plan
            from pipeline.ideas import suggest as ideas_suggest
            clock("Writing the findings and ideas...")
            ideas = ideas_suggest(accounts, client, business=business, place=place,
                                  language=inp.get("language", ""), verbose=False,
                                  brief_text=brief.as_text(), extras=extras)
            if ideas is not None:
                clock("Planning the month and the Conra AI section...")
                # Independent of each other; side by side.
                with ThreadPoolExecutor(max_workers=2) as pool:
                    plan_f = pool.submit(ideas_plan, accounts, client, ideas,
                                         brief_text=brief.as_text(), extras=extras,
                                         local=local, verbose=False)
                    offer_f = (pool.submit(make_offer, accounts, client, extras, ideas,
                                           brief.as_text(), DATA_DIR, lambda m: None)
                               if extras is not None else None)
                    ideas.plan = plan_f.result()
                    if offer_f:
                        offer_f.result()
        box.update(label=f"Done in {clock.took / 60:.1f} min", state="complete",
                   expanded=False)
    S.update(accounts=accounts, stamp=stamp, client=client, ideas=ideas,
             extras=extras, took=clock.took, log=clock.lines,
             context={"Business": business, "Customers in": place})
    _go(3)


def step_competitors() -> None:
    inp, disc = S["inputs"], S["discovery"]
    client = inp.get("handle", "")
    st.subheader(f"Who should @{client} be compared with?")
    picked: list[str] = []
    if disc is not None:
        u = disc.understood
        st.info(f"**Read as:** {u.summary}  \n"
                f"{'Online' if u.kind == 'online' else 'Local'} business · "
                f"{u.category} · market: {u.market or '?'}")
        direct = [f for f in disc.found if f.label == "direct"]
        web_only = [f for f in disc.found if f.label == "no_instagram"]
        rest = [f for f in disc.found if f.label not in ("direct", "no_instagram")]
        if direct:
            st.caption("Checked against the client. Untick any that don't fit.")
            cols = st.columns(2)
            for i, f in enumerate(direct):
                with cols[i % 2]:
                    if _pick(f, i < 6):
                        picked.append(f.handle)
        else:
            st.warning("None checked out as a direct competitor. Look in the "
                       "set-aside list, or type them below.")
        if rest:
            with st.expander(f"Set aside ({len(rest)})"):
                for lab, title in ASIDE.items():
                    group = [f for f in rest if f.label == lab and f.handle]
                    if group:
                        st.markdown(f"**{title}**")
                        for f in group:
                            if _pick(f, False):
                                picked.append(f.handle)
        if web_only:
            with st.expander(f"Competitors without a usable Instagram ({len(web_only)})"):
                for f in web_only:
                    site = f" — {f.website}" if f.website else ""
                    st.markdown(f"- **{f.name}**{site}: {f.reason}")

    typed = _split_handles(st.text_area(
        "Add competitors" if disc else "Competitors (comma or one per line)",
        placeholder="tanishqjewellery, kalyanjewellers_official", key="w_against",
        height=80))
    against = [h for h in dict.fromkeys(picked + typed) if h != client]
    n = len(against)
    est = 0.45 + 0.05 * n + (0.0 if disc else 0.10)
    st.caption(f"Comparing **{n}** account{'s' if n != 1 else ''} with @{client}."
               + (" Six or fewer keeps the report readable." if n > 6 else ""))

    a, b, c = st.columns([1, 2, 1])
    if a.button("← Back", width="stretch"):
        _go(1)
    run = b.button(f"Run the audit  ·  ~2–3 min, ~${est:.2f}", type="primary",
                   width="stretch", disabled=not (n and apify_token))
    has_scan = bool(client) and bool(load_snapshots(DATA_DIR, client))
    reuse = c.button("Use last scan", width="stretch", disabled=not has_scan,
                     help="Rebuild from the stored scan without fetching. Ideas "
                          "are rewritten (~$0.30).")
    if run:
        _run_audit(client, against)
    elif reuse:
        _run_audit(client, against, reuse_only=True)


# --------------------------------------------------------------------------- #
# Step 3: the report
# --------------------------------------------------------------------------- #

def step_report() -> None:
    accounts, client, stamp = S["accounts"], S["client"], S["stamp"]
    if not accounts:
        _go(2)
    ok = [a for a in accounts if not a.error]
    failed = [a for a in accounts if a.error]
    report_html = build(accounts, client, stamp, DATA_DIR, S["ideas"], S["context"],
                        extras=S["extras"], brief=S["brief"])
    try:
        (DATA_DIR / f"{client}_report_{stamp}.html").write_text(report_html, encoding="utf-8")
    except OSError:
        pass

    a, b, c, d = st.columns([1, 1, 1, 2])
    a.metric("Accounts", len(ok))
    b.metric("Posts read", sum(x.post_count for x in ok))
    c.metric("Took", f"{S['took'] / 60:.1f} min" if S["took"] else "—")
    d.download_button("Download the report", data=report_html, type="primary",
                      file_name=f"{client}_audit_{stamp}.html", mime="text/html",
                      width="stretch")
    if failed:
        st.warning("Could not read: " + ", ".join(f"@{x.handle}" for x in failed))
    with st.expander("What ran, and how long each step took"):
        for line in S["log"]:
            st.markdown(line)
        if S["extras"] is not None:
            for line in S["extras"].log:
                if any(w in line.lower() for w in ("failed", "could not", "skipped")):
                    st.markdown(f"⚠️ {line}")
    if st.button("← Change the competitors"):
        _go(2)
    st.iframe(report_html, height=1500)


{1: step_client, 2: step_competitors, 3: step_report}[S["step"]]()
