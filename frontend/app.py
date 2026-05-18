"""Streamlit UI for the OSS Contributor Engine — v2 (OAuth login).

Run with:
    uv run streamlit run frontend/app.py

Talks to the FastAPI backend over HTTP (default: http://localhost:8000).
Set API_URL env var or st.secrets["API_URL"] to point elsewhere.

Auth flow:
    1. Anon visitor clicks "Sign in with GitHub" → redirects to FastAPI /auth/login
    2. GitHub OAuth happens → callback at FastAPI
    3. FastAPI redirects back to Streamlit with ?session=<signed-token>
    4. Streamlit stores the token in st.session_state + sends it as a Cookie
       on all subsequent API calls

This cross-origin handoff is a dev convenience; a production deploy would
put both apps behind a reverse proxy on one domain so cookies just work.
"""
from __future__ import annotations

import contextlib
import os

import streamlit as st

from frontend.api_client import ApiClient, ApiError

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="OSS Contributor Engine",
    page_icon=":mag:",
    layout="wide",
)


def _resolve_api_url() -> str:
    if (env := os.getenv("API_URL")):
        return env
    try:
        return st.secrets["API_URL"]
    except (KeyError, FileNotFoundError, Exception):
        return "http://localhost:8000"


API_URL = _resolve_api_url()


# ---------------------------------------------------------------------------
# Session-cookie handoff (one-time read from URL ?session=...)
# ---------------------------------------------------------------------------

def _consume_session_param() -> str | None:
    """If FastAPI redirected us with ?session=<token>, capture + clear it."""
    qp = st.query_params
    if "session" in qp:
        token = qp.get("session")
        # Clean the URL so the token isn't visible/refreshable
        st.query_params.clear()
        return token
    return None


# Capture token from URL if present (will only fire on the redirect-back)
_token_from_url = _consume_session_param()
if _token_from_url and "session_cookie" not in st.session_state:
    st.session_state.session_cookie = _token_from_url


def _build_client() -> ApiClient:
    return ApiClient(
        base_url=API_URL,
        session_cookie=st.session_state.get("session_cookie"),
    )


# Fresh client every render (cheap; cookies live in session_state)
client: ApiClient = _build_client()


# Persistent app state
for key, default in [
    ("me", None),                 # /auth/me result (or None if logged out)
    ("profile", None),
    ("matches", None),
    ("match_mode", "general"),    # "general" | "gsoc"
    ("matches_for_mode", None),   # mode the cached matches were fetched in
    ("selected_issue", None),
    ("investigation_id", None),
    ("investigation_for_issue_id", None),
    ("investigation_result", None),
    ("pitch", None),
]:
    st.session_state.setdefault(key, default)


# ---------------------------------------------------------------------------
# Refresh "who am I" on every render — cheap, lets us reflect login state
# ---------------------------------------------------------------------------

if st.session_state.get("session_cookie"):
    try:
        st.session_state.me = client.me()
    except Exception:
        st.session_state.me = None
else:
    st.session_state.me = None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _service_row(label: str, ok: bool) -> str:
    dot = "🟢" if ok else "⚪"
    return f"{dot} {label}"


with st.sidebar:
    st.markdown("## 🧭 OSS Engine")
    st.caption("Multi-agent OSS issue finder")

    try:
        h = client.health()
        services = h["services"]
        embed_ok = services.get("embedder", services.get("voyage", False))
        st.markdown(
            f"<div style='font-size:0.85em;opacity:0.85;line-height:1.6'>"
            f"API <code>v{h['version']}</code><br>"
            f"{_service_row('GitHub', services['github'])} &nbsp; "
            f"{_service_row('Embed', embed_ok)} &nbsp; "
            f"{_service_row('LLM', services['llm_router'])}"
            f"</div>",
            unsafe_allow_html=True,
        )
    except Exception as e:
        st.error(f"API down: {e}")
        st.stop()

    st.divider()

    # --- Auth section ---
    if st.session_state.me is None:
        st.markdown("##### Sign in")
        # st.link_button is a real <a> tag styled as a Streamlit button.
        # Works for cross-origin navigation (st.button can't redirect).
        st.link_button(
            "Sign in with GitHub",
            f"{API_URL}/auth/login",
            type="primary",
            use_container_width=True,
        )
        st.caption("Authorizes the app to read your public GitHub profile.")
    else:
        me_data = st.session_state.me
        display_name = me_data.get("name") or me_data["github_login"]
        st.markdown(
            f"<div style='padding:.6rem .75rem;background:rgba(120,120,120,.10);"
            f"border-radius:8px;margin-bottom:.5rem'>"
            f"<div style='font-size:.75em;opacity:.7'>Signed in as</div>"
            f"<div style='font-weight:600'>{display_name}</div>"
            f"<div style='font-size:.8em;opacity:.7'>@{me_data['github_login']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button("Sign out", use_container_width=True):
            with contextlib.suppress(Exception):
                client.logout()
            for key in ("session_cookie", "me", "profile", "matches",
                        "selected_issue", "investigation_id",
                        "investigation_for_issue_id",
                        "investigation_result", "pitch"):
                st.session_state.pop(key, None)
            st.rerun()

    st.divider()

    # --- Cost meter (compact) ---
    st.markdown("##### 💰 Total cost")
    try:
        cost = client.global_cost()
        st.markdown(
            f"<div style='font-size:.85em;line-height:1.7'>"
            f"<b>{cost['total_calls']}</b> calls &middot; "
            f"<b>${cost['total_cost_usd']:.4f}</b><br>"
            f"<span style='opacity:.7'>"
            f"in {cost['total_tokens_in']:,} &nbsp;|&nbsp; "
            f"out {cost['total_tokens_out']:,}"
            f"</span></div>",
            unsafe_allow_html=True,
        )
    except Exception as e:
        st.caption(f"(cost: {e})")


# ---------------------------------------------------------------------------
# Main column — landing vs logged-in
# ---------------------------------------------------------------------------

if st.session_state.me is None:
    # Hero
    st.markdown(
        "<div style='padding:2.5rem 0 1rem 0'>"
        "<div style='font-size:2.6rem;font-weight:700;line-height:1.15;"
        "letter-spacing:-.02em'>"
        "OSS issues that actually fit your skills."
        "</div>"
        "<div style='font-size:1.1rem;opacity:.75;margin-top:.75rem;max-width:38rem'>"
        "A multi-agent system that profiles your GitHub history, hunts matching "
        "open-source issues, investigates one end-to-end, and drafts the comment "
        "you'd actually feel good posting."
        "</div></div>",
        unsafe_allow_html=True,
    )

    # Feature grid — 2 columns × 2 rows
    features = [
        ("🧠 Profile from real work",
         "Reads your top repos to figure out what you actually build "
         "— languages, frameworks, domains, experience signal."),
        ("🎯 Ranked, explainable matches",
         "Each issue is scored on skill match, repo health, freshness, "
         "difficulty, and impact — with a one-line 'why this fits you'."),
        ("🔍 Multi-agent investigation",
         "Four specialist agents read the issue, map the repo, scan commit "
         "history, and synthesize an approach in ~15 seconds for under $0.01."),
        ("✍️  Draft a real comment",
         "Tone-guarded pitch writer produces a comment that doesn't sound "
         "AI-generated — copy, edit, post."),
    ]
    for row_start in range(0, len(features), 2):
        cols = st.columns(2, gap="medium")
        for col, (title, body) in zip(cols, features[row_start:row_start + 2], strict=False):
            with col:
                st.markdown(
                    f"<div style='padding:1rem 1.1rem;border-radius:10px;"
                    f"background:rgba(120,120,120,.08);margin-bottom:.75rem;"
                    f"min-height:7rem'>"
                    f"<div style='font-weight:600;margin-bottom:.4rem'>{title}</div>"
                    f"<div style='opacity:.8;font-size:.92em'>{body}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    st.markdown(
        "<div style='margin-top:1rem;opacity:.75;font-size:.95em'>"
        "👈 <b>Sign in with GitHub</b> in the sidebar to start."
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()


me = st.session_state.me


# --- Profile section ---

header_name = me.get("name") or f"@{me['github_login']}"
st.markdown(
    f"<div style='font-size:2.2rem;font-weight:700;line-height:1.1;"
    f"letter-spacing:-.02em'>{header_name}</div>"
    f"<div style='opacity:.7;margin-bottom:1.25rem'>@{me['github_login']}</div>",
    unsafe_allow_html=True,
)

# Load or refresh cached profile from API
if st.session_state.profile is None:
    try:
        st.session_state.profile = client.get_my_profile()  # may be None if no profile yet
    except ApiError:
        st.session_state.profile = None

profile = st.session_state.profile

if profile is None:
    st.info(
        "No profile yet. Click **Profile me** below — we'll scan your top "
        "active repos to figure out what you build."
    )
    if st.button("Profile me", type="primary"):
        with st.spinner("Reading GitHub history (30-90s)..."):
            try:
                st.session_state.profile = client.profile_me()
                st.session_state.matches = None
                st.rerun()
            except ApiError as e:
                st.error(str(e))
    st.stop()


# Profile card
if summary := profile.get("summary"):
    st.markdown(
        f"<div style='padding:1rem 1.1rem;border-radius:10px;"
        f"background:rgba(120,120,120,.08);margin-bottom:1rem;"
        f"font-size:1.02em;line-height:1.6'>{summary}</div>",
        unsafe_allow_html=True,
    )
else:
    st.caption("_(no summary)_")

card_cols = st.columns(4, gap="small")
chip_blocks = [
    ("Languages", profile["languages"][:6]),
    ("Frameworks", profile["frameworks"][:6]),
    ("Domains", profile["domains"]),
    ("Experience", [profile.get("experience_signal") or "—"]),
]
for col, (label, items) in zip(card_cols, chip_blocks, strict=False):
    with col:
        st.markdown(
            f"<div style='font-size:.78em;text-transform:uppercase;"
            f"letter-spacing:.06em;opacity:.65;margin-bottom:.3rem'>{label}</div>",
            unsafe_allow_html=True,
        )
        if items:
            chips = " ".join(
                f"<span style='display:inline-block;padding:.18rem .55rem;"
                f"margin:.12rem .15rem .12rem 0;border-radius:999px;"
                f"background:rgba(120,120,120,.18);font-size:.85em'>{x}</span>"
                for x in items
            )
            st.markdown(chips, unsafe_allow_html=True)
        else:
            st.caption("—")

if st.button("Re-profile (refresh)"):
    with st.spinner("Reading GitHub history (30-90s)..."):
        try:
            st.session_state.profile = client.profile_me()
            st.session_state.matches = None
            st.rerun()
        except ApiError as e:
            st.error(str(e))


# --- Matches section ---

st.divider()
st.header("Issues that match")

# Mode picker — defines the scope of repos we consider. GSoC mode restricts
# to orgs that have shipped GSoC projects in the last 3 years; General mode
# searches across all of GitHub.
MODE_LABELS = {"general": "🌐 General", "gsoc": "🎓 GSoC"}
mode_label = st.radio(
    "Search scope",
    options=list(MODE_LABELS.values()),
    index=0 if st.session_state.match_mode == "general" else 1,
    horizontal=True,
    label_visibility="collapsed",
    key="match_mode_picker",
)
new_mode = "general" if mode_label == MODE_LABELS["general"] else "gsoc"

# Flipping mode invalidates cached matches so the user notices the
# scope changed without a stale list lingering.
if new_mode != st.session_state.match_mode:
    st.session_state.match_mode = new_mode
    if st.session_state.matches_for_mode != new_mode:
        st.session_state.matches = None
        st.session_state.selected_issue = None

if st.session_state.match_mode == "gsoc":
    st.caption(
        "Filtered to organizations that have shipped Google Summer of Code "
        "projects in the last 3 years."
    )

mcol1, mcol2, mcol3 = st.columns([2, 2, 1])
top = mcol1.slider("How many", 5, 30, 10)
difficulty = mcol2.selectbox("Difficulty", ["any", "easy", "medium", "hard"], index=0)
explain = mcol3.checkbox("Explain", value=True)

if st.button("Find matches"):
    with st.spinner("Embedding + ranking..."):
        try:
            st.session_state.matches = client.get_my_matches(
                top=top, difficulty=difficulty, explain=explain,
                mode=st.session_state.match_mode,
            )
            st.session_state.matches_for_mode = st.session_state.match_mode
            st.session_state.selected_issue = None
            st.session_state.investigation_id = None
            st.session_state.pitch = None
        except ApiError as e:
            st.error(str(e))


if st.session_state.matches is not None:
    matches = st.session_state.matches
    if not matches:
        if st.session_state.match_mode == "gsoc":
            st.info(
                "No GSoC matches yet. The candidate pool may not include any "
                "issues from GSoC-listed orgs. Run the Issue Hunter in GSoC mode "
                "(`uv run python -m app.workers hunt --mode gsoc`) to populate it."
            )
        else:
            st.info(
                "No matches yet. Run the Issue Hunter to populate the candidate pool."
            )
    for i, m in enumerate(matches):
        with st.container(border=True):
            row1, row2 = st.columns([5, 1])
            with row1:
                st.markdown(
                    f"**[{m['repo_full_name']}#{m['issue_number']}]({m['html_url']})** "
                    f"· :star: {m['stargazers_count']:,} "
                    f"· `{m.get('difficulty') or '?'}`"
                )
                st.write(m["title"])
                if m.get("why_it_fits"):
                    st.caption(f":speech_balloon: {m['why_it_fits']}")
                st.progress(m["final_score"], text=f"Score: {m['final_score']:.2f}")
            with row2:
                if st.button("Investigate", key=f"inv_{i}", type="primary"):
                    st.session_state.selected_issue = m
                    st.session_state.investigation_id = None
                    st.session_state.investigation_result = None
                    st.session_state.pitch = None


# --- Investigation section ---

if st.session_state.selected_issue:
    issue = st.session_state.selected_issue
    st.divider()
    st.header(f"Investigation: {issue['repo_full_name']}#{issue['issue_number']}")
    st.caption(f"[Open issue on GitHub :arrow_upper_right:]({issue['html_url']})")

    no_active_inv = (
        st.session_state.investigation_id is None
        or st.session_state.investigation_for_issue_id != issue["issue_id"]
    )
    if no_active_inv and st.button("Run investigation", type="primary"):
        try:
            job_id = client.create_investigation(
                repo=issue["repo_full_name"],
                issue_number=issue["issue_number"],
            )
            st.session_state.investigation_id = job_id
            st.session_state.investigation_for_issue_id = issue["issue_id"]
            st.session_state.investigation_result = None
            st.rerun()
        except ApiError as e:
            st.error(str(e))

    if st.session_state.investigation_id and \
       st.session_state.investigation_result is None:
        inv_id = st.session_state.investigation_id
        with st.status("Investigating...", expanded=True) as status:
            terminal_seen = False
            for event in client.stream_investigation(inv_id):
                etype = event.get("type", "?")
                if etype == "queued":
                    st.write(":hourglass: queued")
                elif etype == "investigation_started":
                    st.write(":rocket: investigation started")
                elif etype == "data_fetched":
                    st.write(
                        f":satellite: data fetched "
                        f"({event.get('comments', 0)} comments, "
                        f"{event.get('tree_files', 0)} files)"
                    )
                elif etype == "agent_started":
                    st.write(f":runner: `{event.get('agent', '?')}` running...")
                elif etype == "agent_completed":
                    extras = (
                        f" ({event['candidate_files']} files)"
                        if event.get("candidate_files") is not None else ""
                    )
                    st.write(f":white_check_mark: `{event.get('agent', '?')}`{extras}")
                elif etype == "investigation_completed":
                    status.update(
                        label=f"Investigation completed (effort: {event.get('effort', '?')})",
                        state="complete",
                    )
                    terminal_seen = True
                elif etype == "investigation_failed":
                    status.update(label=f"Failed: {event.get('error', '?')}", state="error")
                    terminal_seen = True
            if terminal_seen:
                st.session_state.investigation_result = client.get_investigation(inv_id)
                st.rerun()

    result = st.session_state.investigation_result
    if result is not None:
        if result["status"] == "completed":
            st.markdown("### Report")
            st.markdown(result["markdown_report"])

            try:
                cost = client.investigation_cost(st.session_state.investigation_id)
                cols = st.columns(4)
                cols[0].metric("LLM calls", cost["total_calls"])
                cols[1].metric("Tokens in", f"{cost['total_tokens_in']:,}")
                cols[2].metric("Tokens out", f"{cost['total_tokens_out']:,}")
                cols[3].metric("USD", f"${cost['total_cost_usd']:.4f}")
            except Exception:
                pass

            # --- Pitch section ---
            st.divider()
            st.header("Draft a comment")

            pcol1, pcol2 = st.columns([1, 1])
            with pcol1:
                if st.button("Draft pitch", type="primary"):
                    try:
                        st.session_state.pitch = client.draft_pitch(
                            st.session_state.investigation_id,
                        )
                    except ApiError as e:
                        st.error(str(e))
            with pcol2:
                if st.session_state.pitch and st.button("Regenerate"):
                    try:
                        st.session_state.pitch = client.draft_pitch(
                            st.session_state.investigation_id, force=True,
                        )
                    except ApiError as e:
                        st.error(str(e))

            if st.session_state.pitch:
                pitch = st.session_state.pitch
                tags = [pitch.get("tone", "respectful")]
                if pitch.get("estimated_timeline"):
                    tags.append(f"timeline: {pitch['estimated_timeline']}")
                if pitch.get("asks_questions"):
                    tags.append("asks questions")
                if pitch.get("cached"):
                    tags.append("cached")
                st.caption(" · ".join(tags))

                st.markdown("**Preview**")
                with st.container(border=True):
                    st.markdown(pitch["comment_md"])

                st.markdown("**Copy-paste**")
                st.code(pitch["comment_md"], language="markdown")
        else:
            st.error(f"Investigation failed: {result.get('error') or 'unknown'}")
