"""
RailCast Dashboard — Streamlit frontend (v5)
=============================================
Talks to api_main.py over HTTP. Start both with `python run_all.py` locally.

Changes in this version vs your last one:
  - Self-starts the FastAPI backend (api_main.py) in a background thread if
    it isn't already reachable at API_BASE. This is ONLY for Streamlit Cloud
    deploys, where only `dashboard_app.py` gets run (Cloud does
    `streamlit run dashboard_app.py`, it never runs `run_all.py`, so without
    this the app would get connection errors trying to reach localhost:8000).
    Locally, if you already started the API via `python run_all.py`, this
    self-start check just sees the API is already up and does nothing.
  - Everything else — Seasonal Risk explanations, the Why-this-prediction /
    Seasonal Risk cards showing in BOTH Passenger and Officer views, the
    layout fix that removed the white-space gap, 24-hour time formatting,
    color-coded Operational Actions, etc. — is unchanged from your version.
"""

import os
import time
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

try:
    import folium
    from streamlit_folium import st_folium
    HAS_MAP = True
except ImportError:
    HAS_MAP = False

API_BASE = os.environ.get("RAILCAST_API_BASE", "http://localhost:8000")


# =============================================================================
# SELF-START THE API (Streamlit Cloud only runs this file, not run_all.py) —
# if the API is already up (e.g. you started it locally via run_all.py),
# this just confirms that and does nothing else.
# =============================================================================
def _api_is_up():
    try:
        return requests.get(f"{API_BASE}/", timeout=1).status_code == 200
    except Exception:
        return False


@st.cache_resource
def _ensure_api_running():
    if _api_is_up():
        return True
    import threading
    import uvicorn
    from api_main import app as fastapi_app

    def _run():
        try:
            uvicorn.run(fastapi_app, host="127.0.0.1", port=8000, log_level="warning")
        except Exception:
            pass  # already running (e.g. started separately via run_all.py)

    threading.Thread(target=_run, daemon=True).start()
    deadline = time.time() + 15
    while time.time() < deadline:
        if _api_is_up():
            break
        time.sleep(0.5)
    return True


_ensure_api_running()

st.set_page_config(page_title="RailCast", layout="wide", page_icon="🚆")

# =============================================================================
# STYLE
# =============================================================================
st.markdown("""
<style>
    :root {
        /* ---- Elevation system: 3 consistent shadow depths ---- */
        --rc-shadow-flat: 0 1px 3px rgba(15, 23, 42, 0.07);
        --rc-shadow-raised: 0 4px 12px rgba(15, 23, 42, 0.12);
        --rc-shadow-floating: 0 14px 30px rgba(15, 23, 42, 0.20);
    }
    .stApp { background-color: #F1F5F9; }
    section[data-testid="stSidebar"] { background-color: #0B1220; }
    section[data-testid="stSidebar"] * { color: #E7EBF5 !important; }

    .rc-logo { font-size: 1.3rem; font-weight: 800; color: white; }

    /* ---- Sidebar nav items: icon + label, left-bar accent instead of a
       full solid pill, so the active state reads as "product nav" rather
       than a plain radio dot. Shared by both the static "Dashboard" item
       and the st.radio-based view switcher below. ---- */
    .rc-nav-item { display: flex; align-items: center; gap: 10px; padding: 9px 12px;
        border-radius: 8px; margin-bottom: 4px; color: #94A3B8; font-size: 0.92rem;
        border-left: 3px solid transparent; }
    .rc-nav-active { background: rgba(37, 99, 235, 0.18); color: white !important;
        font-weight: 700; border-left: 3px solid #2563EB; }
    .rc-mae { font-size: 1.4rem; font-weight: 800; color: white; }

    /* Restyle Streamlit's radio (used for Passenger / Control Room) to look
       like the same icon-led nav list instead of default radio dots. */
    section[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] {
        display: flex; flex-direction: column; gap: 2px; margin-top: 2px;
    }
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label {
        display: flex; align-items: center; gap: 10px; padding: 9px 12px;
        border-radius: 8px; border-left: 3px solid transparent; cursor: pointer;
        transition: background 0.15s ease, border-color 0.15s ease; margin-bottom: 0 !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {
        background: rgba(255,255,255,0.06);
    }
    /* hide the native circle indicator — the left accent bar + bold text
       carries the "selected" state instead */
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label > div:first-child {
        display: none !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label div[data-testid="stMarkdownContainer"] p {
        font-size: 0.92rem !important; font-weight: 500; margin: 0;
    }
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {
        background: rgba(37, 99, 235, 0.18);
        border-left: 3px solid #2563EB;
    }
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) p {
        color: #FFFFFF !important; font-weight: 700 !important;
    }

    .rc-hero {
        border-radius: 16px; padding: 26px 30px; margin-bottom: 16px;
        background: linear-gradient(120deg, #0B1220 0%, #1E3A8A 55%, #2563EB 100%);
        color: white; position: relative; overflow: hidden;
        box-shadow: var(--rc-shadow-floating); /* floating elevation */
    }
    .rc-hero h1 { margin: 0; font-size: 1.7rem; font-style: italic; }
    .rc-tricolor { height: 4px; width: 90px; margin: 6px 0 8px 0;
        background: linear-gradient(90deg, #FF9933 33%, #FFFFFF 33%, #FFFFFF 66%, #138808 66%); border-radius: 2px; }
    .rc-hero p { margin: 0; color: #CBD5E1; font-style: italic; font-size: 0.95rem; }

    .rc-card { border-radius: 14px; padding: 16px 18px; color: white; min-height: 96px;
        box-shadow: var(--rc-shadow-raised); /* raised elevation */ }
    /* ---- Tighter type scale: small/light label, big/bold hero number,
       small/muted sub-line — makes the delay & ETA figures pop. ---- */
    .rc-card .rc-label { font-size: 0.68rem; opacity: 0.85; letter-spacing: 0.06em;
        margin-bottom: 6px; font-weight: 700; text-transform: uppercase; }
    .rc-card .rc-value { font-size: 1.85rem; font-weight: 800; line-height: 1.15; }
    .rc-card .rc-sub { font-size: 0.72rem; opacity: 0.85; margin-top: 4px; }
    .rc-delta { font-size: 1rem; margin-left: 6px; font-weight: 700; }

    /* ---- Pending / "waiting for data" cards (Actual Arrival, Prediction
       Error before feedback exists) — dashed border + hourglass reads as
       "not yet available" rather than "broken". ---- */
    .rc-card-pending { border-radius: 14px; padding: 16px 18px; min-height: 96px;
        background: #F8FAFC; border: 2px dashed #CBD5E1; box-shadow: none;
        display: flex; flex-direction: column; justify-content: center; }
    .rc-card-pending .rc-label { font-size: 0.68rem; color: #64748B; letter-spacing: 0.06em;
        margin-bottom: 6px; font-weight: 700; text-transform: uppercase; }
    .rc-card-pending .rc-value { font-size: 1.05rem; font-weight: 700; color: #94A3B8; }
    .rc-card-pending .rc-sub { font-size: 0.72rem; color: #94A3B8; margin-top: 4px; }

    .rc-blue   { background: linear-gradient(135deg, #3b82f6, #2563eb); }
    .rc-green  { background: linear-gradient(135deg, #22c55e, #16a34a); }
    .rc-orange { background: linear-gradient(135deg, #fb923c, #ea580c); }
    .rc-purple { background: linear-gradient(135deg, #a78bfa, #7c3aed); }
    .rc-red    { background: linear-gradient(135deg, #f87171, #dc2626); }
    .rc-gray   { background: linear-gradient(135deg, #94a3b8, #64748b); }

    .rc-highlight { border: 3px solid #FACC15; box-shadow: 0 0 0 4px rgba(250,204,21,0.25), 0 4px 14px rgba(0,0,0,0.15); }

    .rc-panel { background: white; border-radius: 14px; padding: 16px 18px; box-shadow: var(--rc-shadow-flat); margin-bottom: 14px; }
    .rc-panel h4 { margin-top: 0; margin-bottom: 10px; font-size: 0.92rem; font-weight: 700;
        color: #334155; text-transform: uppercase; letter-spacing: 0.04em; }

    .rc-badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 600; }
    .rc-badge-live { background: #dcfce7; color: #166534; }
    .rc-badge-delay { background: #fee2e2; color: #991b1b; }

    /* ---- Status/risk pill badges — same idea as the STATUS card, reused
       for Seasonal Risk and Operational Actions tags ---- */
    .rc-pill { display: inline-block; padding: 3px 11px; border-radius: 999px; font-size: 0.74rem; font-weight: 700; letter-spacing: 0.01em; }
    .rc-pill-green  { background: #dcfce7; color: #166534; }
    .rc-pill-amber  { background: #fef3c7; color: #92400e; }
    .rc-pill-red    { background: #fee2e2; color: #991b1b; }
    .rc-pill-gray   { background: #e2e8f0; color: #475569; }

    .rc-progress-track { background: #E2E8F0; border-radius: 999px; height: 8px; width: 100%; }
    .rc-progress-fill { background: #22c55e; border-radius: 999px; height: 8px; }

    /* Legacy horizontal bar-row (kept in case other code still uses it) */
    .rc-bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 0.82rem; }
    .rc-bar-label { width: 60px; color: #475569; }
    .rc-bar-track { flex: 1; background: #E2E8F0; border-radius: 6px; height: 14px; position: relative; }
    .rc-bar-fill { height: 14px; border-radius: 6px; }
    .rc-bar-value { width: 46px; text-align: right; font-weight: 600; color: #0F172A; }

    /* ---- Vertical bar-row: label sits ABOVE the bar so long disruption
       names ("Signal Halt / Unscheduled Stoppage") never wrap into a thin
       bar and look broken. Long labels ellipsis with a native tooltip. ---- */
    .rc-bar-row-v { margin-bottom: 12px; font-size: 0.82rem; }
    .rc-bar-toprow { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 4px; }
    .rc-bar-label-v { color: #475569; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 78%; }
    .rc-bar-value-v { font-weight: 700; color: #0F172A; white-space: nowrap; }

    .rc-oc-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; text-align: center; }
    .rc-oc-item { background: #F8FAFC; border-radius: 10px; padding: 10px 6px; box-shadow: var(--rc-shadow-flat); }
    .rc-oc-item .rc-oc-icon { font-size: 1.2rem; }
    .rc-oc-item .rc-oc-label { font-size: 0.68rem; color: #64748B; margin: 4px 0 2px 0; }
    .rc-oc-item .rc-oc-value { font-weight: 700; color: #0F172A; font-size: 0.88rem; }

    /* ---- Themed tint per condition, matching its icon, so the row reads
       as designed rather than 6 identical gray tiles. ---- */
    .rc-oc-item.rc-oc-blue   { background: #EFF6FF; }
    .rc-oc-item.rc-oc-blue   .rc-oc-icon { filter: none; }
    .rc-oc-item.rc-oc-orange { background: #FFF7ED; }
    .rc-oc-item.rc-oc-purple { background: #F5F3FF; }
    .rc-oc-item.rc-oc-slate  { background: #F1F5F9; }
    .rc-oc-item.rc-oc-red    { background: #FEF2F2; }
    .rc-oc-item.rc-oc-green  { background: #F0FDF4; }

    div[data-testid="stMetricValue"] { font-size: 1.4rem; }

    /* =========================================================================
       SKELETON LOADING — shimmering placeholder blocks shown in place of the
       metric cards / map / timeline while api_predict + api_eta are in flight,
       instead of a blank flash.
       ========================================================================= */
    @keyframes rc-shimmer { 0% { background-position: -400px 0; } 100% { background-position: 400px 0; } }
    .rc-skel { border-radius: 14px; background: linear-gradient(90deg, #E2E8F0 25%, #EDF1F7 37%, #E2E8F0 63%);
        background-size: 800px 100%; animation: rc-shimmer 1.4s ease-in-out infinite; }
    .rc-skel-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; margin-bottom: 14px; }
    .rc-skel-card { height: 96px; }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# API HELPERS — short TTL caches, show_spinner=False so no per-card
# "Running..." text appears — the dashboard loads fully before anything renders.
# =============================================================================
@st.cache_data(ttl=30, show_spinner=False)
def api_get_trains():
    return requests.get(f"{API_BASE}/trains", timeout=10).json()


@st.cache_data(ttl=30, show_spinner=False)
def api_get_journey(train_id):
    r = requests.get(f"{API_BASE}/train/{train_id}/journey", timeout=10)
    r.raise_for_status()
    return pd.DataFrame(r.json())


@st.cache_data(ttl=5, show_spinner=False)
def api_predict(train_id, station, disruption, date=None):
    r = requests.post(f"{API_BASE}/predict", json={
        "train": train_id, "station": station, "disruption": disruption, "date": date
    }, timeout=10)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=5, show_spinner=False)
def api_eta(train_id, from_station, date=None):
    r = requests.get(f"{API_BASE}/train/{train_id}/eta",
                      params={"from_station": from_station, "date": date}, timeout=10)
    r.raise_for_status()
    return pd.DataFrame(r.json())


@st.cache_data(ttl=15, show_spinner=False)
def api_risk(train_id):
    r = requests.get(f"{API_BASE}/train/{train_id}/risk", timeout=10)
    r.raise_for_status()
    return r.json()


def api_live_state():
    try:
        r = requests.get(f"{API_BASE}/simulate/state", timeout=5)
        return r.json()
    except Exception:
        return {}


def compute_eta_client(sch_arr, delay_minutes):
    """Mirrors the API's compute_arrival_time — used for the Actual Arrival
    card, computed locally from the feedback the user just typed in, with no
    extra round trip. 24-hour format to match the rest of the dashboard."""
    if not sch_arr or sch_arr == "--":
        return "--"
    try:
        base = pd.to_datetime(str(sch_arr))
    except Exception:
        return "--"
    return (base + pd.Timedelta(minutes=float(delay_minutes))).strftime("%H:%M")


# =============================================================================
# CARD RENDER HELPERS — built as ONE continuous line each. Do not reformat
# these across multiple lines with a blank line in the middle; that's exactly
# what caused the stray "</div>" text bug in an earlier version.
# =============================================================================
def metric_card(label, value, sub="", css="rc-blue", highlight=False, icon="", delta=None):
    """delta: optional signed number. Positive renders a red ▲ (worse/more
    delay), negative a green ▼ (better/less delay), zero a neutral ▬ —
    same visual language as a stock ticker, per the icons+delta request."""
    classes = f"rc-card {css}" + (" rc-highlight" if highlight else "")
    icon_html = f'<span style="margin-right:6px;">{icon}</span>' if icon else ""
    delta_html = f'<span class="rc-delta">{delta_arrow(delta)}</span>' if delta is not None else ""
    sub_html = f'<div class="rc-sub">{sub}</div>' if sub else ""
    return f'<div class="{classes}"><div class="rc-label">{icon_html}{label}</div><div class="rc-value">{value}{delta_html}</div>{sub_html}</div>'


def pending_card(label, message, icon="⏳"):
    """Renders a dashed-border 'waiting for data' card — used for Actual
    Arrival / Prediction Error before passenger feedback exists, so it reads
    as 'not yet available' rather than 'disabled' or broken."""
    return (f'<div class="rc-card-pending"><div class="rc-label">{label}</div>'
            f'<div class="rc-value">{icon} Waiting for feedback</div>'
            f'<div class="rc-sub">{message}</div></div>')


def status_card(status, sub, css="rc-green", progress_pct=0, icon=""):
    icon_html = f'<span style="margin-right:6px;">{icon}</span>' if icon else ""
    sub_html = f'<div class="rc-sub">{sub}</div>' if sub else ""
    bar = (f'<div class="rc-progress-track" style="margin-top:8px;">'
           f'<div class="rc-progress-fill" style="width:{progress_pct}%;"></div></div>')
    return f'<div class="rc-card {css}"><div class="rc-label">STATUS</div><div class="rc-value">{icon_html}{status}</div>{sub_html}{bar}</div>'


def delta_arrow(value):
    """Small ▲/▼/▬ indicator, colored red (worse) / green (better) /
    neutral, used next to delay figures on the metric cards."""
    if value is None:
        return ""
    if value > 0:
        return '<span style="color:#fecaca;">▲</span>'
    if value < 0:
        return '<span style="color:#bbf7d0;">▼</span>'
    return '<span style="color:#e2e8f0;">▬</span>'


def mini_bar(label, minutes, max_minutes, color):
    """Label sits ABOVE the bar (rc-bar-row-v) instead of to its left, so a
    long disruption name never wraps into 3 lines next to a thin bar; the
    title attribute keeps the full text available as a native tooltip."""
    pct = 0 if max_minutes <= 0 else min(100, (minutes / max_minutes) * 100)
    return (
        f'<div class="rc-bar-row-v">'
        f'<div class="rc-bar-toprow">'
        f'<span class="rc-bar-label-v" title="{label}">{label}</span>'
        f'<span class="rc-bar-value-v">{minutes:.0f} min</span>'
        f'</div>'
        f'<div class="rc-bar-track"><div class="rc-bar-fill" style="width:{pct}%; background:{color};"></div></div>'
        f'</div>'
    )


def oc_item(icon, label, value, theme="slate"):
    return (f'<div class="rc-oc-item rc-oc-{theme}"><div class="rc-oc-icon">{icon}</div>'
            f'<div class="rc-oc-label">{label}</div><div class="rc-oc-value">{value}</div></div>')


def skeleton_cards_row(n=5):
    cells = '<div class="rc-skel rc-skel-card"></div>' * n
    return f'<div class="rc-skel-row">{cells}</div>'


def skeleton_panels_row(n=3, height=330):
    cells = "".join(f'<div class="rc-skel" style="height:{height}px;"></div>' for _ in range(n))
    cols = " ".join(["1fr"] * n)
    return f'<div style="display:grid; grid-template-columns:{cols}; gap:14px; margin-bottom:14px;">{cells}</div>'


# =============================================================================
# COLOR-CODING HELPERS — pill badges for risk/status words (Seasonal Risk,
# Operational Actions), and a light-green→amber→red heatmap for the
# Station Timeline's predicted_delay column.
# =============================================================================
def status_color_level(text):
    """Map a risk/severity word to a pill color level."""
    t = str(text).lower()
    if any(k in t for k in ("low", "normal", "minimal", "on time", "good", "clear")):
        return "green"
    if any(k in t for k in ("elevated", "moderate", "medium", "caution", "watch")):
        return "amber"
    if any(k in t for k in ("high", "severe", "critical", "delayed", "alert")):
        return "red"
    return "gray"


def pill_badge(text, level="gray"):
    return f'<span class="rc-pill rc-pill-{level}">{text}</span>'


def _lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _delay_heat_color(value, vmin, vmax):
    rng = (vmax - vmin) or 1
    t = max(0.0, min(1.0, (value - vmin) / rng))
    green, amber, red = (187, 247, 208), (253, 230, 138), (252, 165, 165)
    r, g, b = _lerp(green, amber, t / 0.5) if t < 0.5 else _lerp(amber, red, (t - 0.5) / 0.5)
    return f"rgb({r},{g},{b})"


def style_delay_heatmap(df, column="predicted_delay"):
    """pandas Styler gradient (no matplotlib dependency) so the worst
    stations pop out without reading every row."""
    if column not in df.columns or df.empty:
        return df
    vmin, vmax = df[column].min(), df[column].max()

    def _apply(col):
        return [f"background-color:{_delay_heat_color(v, vmin, vmax)}; color:#1E293B; font-weight:600;" for v in col]

    return df.style.apply(_apply, subset=[column])


WEATHER_ICONS = {
    "Clear": "☀️", "Foggy": "🌫️", "Heavy Rain / Storm": "🌧️",
    "Speed Restriction in effect": "🚧", "Signal Halt in effect": "🛑",
    "Track Congestion Spike": "🚦", "Maintenance Block in effect": "🔧",
}


# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.markdown('<div class="rc-logo">🚆 RailCast</div>', unsafe_allow_html=True)
    st.caption("Dynamic ETA & Delay Intelligence")
    st.markdown("---")
    st.markdown('<div class="rc-nav-item rc-nav-active">🏠&nbsp;&nbsp;Dashboard</div>', unsafe_allow_html=True)
    page_choice = st.radio(
        "Dashboard view", ["🧍  Passenger View", "🎛️  Control Room / Officer"],
        label_visibility="collapsed"
    )
    page = "Control Room / Officer" if "Control Room" in page_choice else "Passenger View"
    st.markdown("---")
    st.markdown("**Model Reference**")
    st.markdown('<div class="rc-mae">7.88 minutes</div>', unsafe_allow_html=True)
    st.caption("XGBoost prediction engine — historical data + live operating conditions.")
    st.markdown("---")
    live_on = st.toggle(
        "🔴 Live simulated feed", value=False,
        help=("Replays your historical demo data as if trains were moving right now, one station "
              "every few seconds. It does NOT call any real railway API; it's a replay of "
              "demo_data.csv, used to demo train-to-train effects and the live-refresh UI.")
    )
    if live_on:
        try:
            requests.post(f"{API_BASE}/simulate/start", timeout=5)
        except Exception:
            st.warning("Couldn't reach the API to start the live feed.")
        st_autorefresh(interval=8000, key="live_refresh")
    else:
        try:
            requests.post(f"{API_BASE}/simulate/stop", timeout=5)
        except Exception:
            pass
    st.markdown("---")
    st.caption("Decision-support prototype. Operational actions remain with authorised railway staff.")


# =============================================================================
# LOAD TRAINS / JOURNEY / PREDICTION — all wrapped in one silent spinner so
# the dashboard renders complete, with no per-card loading text visible.
# =============================================================================
try:
    with st.spinner(""):
        trains = api_get_trains()
except Exception as e:
    st.error(f"Can't reach the API at {API_BASE}. Make sure you started everything with `python run_all.py`.\n\n{e}")
    st.stop()

# =============================================================================
# HERO BANNER
# =============================================================================
st.markdown(
    '<div class="rc-hero"><h1>🚆 RailCast — Dynamic ETA &amp; Delay Intelligence</h1>'
    '<div class="rc-tricolor"></div>'
    '<p>Predict the arrival. Understand the delay. Act on it.</p></div>',
    unsafe_allow_html=True,
)

# =============================================================================
# TRAIN INFO BAR
# =============================================================================
bar_l, bar_m, bar_r1, bar_r2 = st.columns([1.6, 1, 1, 1])
with bar_l:
    selected_train = st.selectbox("Select Train", trains)

with st.spinner(""):
    journey_df = api_get_journey(selected_train)

with bar_m:
    row_index = st.selectbox(
        "Select Journey Point", journey_df.index,
        format_func=lambda i: f'{journey_df.loc[i, "station"]} → {journey_df.loc[i, "next_station"]}'
    )
current_station = journey_df.loc[row_index, "station"]
current_date = journey_df.loc[row_index, "date"] if "date" in journey_df.columns else None
with bar_r1:
    st.markdown(f'<div style="margin-top:28px;"><span class="rc-badge rc-badge-live">● Running</span> &nbsp;<b>Train {selected_train}</b></div>', unsafe_allow_html=True)
with bar_r2:
    st.markdown(f'<div style="margin-top:28px; color:#64748B; font-size:0.85rem;">📅 {datetime.now().strftime("%d %b %Y, %I:%M %p")}</div>', unsafe_allow_html=True)

st.selectbox("⚠️ Simulate a disruption", [
    "None", "Fog", "Heavy Rain / Storm", "Speed Restriction",
    "Signal Halt / Unscheduled Stoppage", "Track Congestion Spike", "Unscheduled Maintenance Block"
], key="disruption")
disruption = st.session_state.disruption

# ---- Skeleton loading: show shimmering placeholders for the cards + the
# map/timeline (/ actions) row while the prediction call is in flight, then
# swap them for the real content — no blank-page flash. ----
dashboard_skeleton = st.empty()
with dashboard_skeleton.container():
    st.markdown(skeleton_cards_row(5), unsafe_allow_html=True)
    st.markdown(
        skeleton_panels_row(3 if page == "Control Room / Officer" else 2, height=330),
        unsafe_allow_html=True,
    )

result = api_predict(selected_train, current_station, disruption, current_date)
forecast = api_eta(selected_train, current_station, current_date)
live_state = api_live_state().get(str(selected_train)) if live_on else None

dashboard_skeleton.empty()

# =============================================================================
# METRIC CARDS — 5 across. Card 2 (ETA) is the highlighted headline, 24-hour
# format throughout.
# =============================================================================
predicted_delay = result["predicted_delay"]
original_delay = result["original_predicted_delay"]

# actual delay comes from passenger feedback, stored client-side per (train, station)
fb_key = f"{selected_train}_{current_station}"
st.session_state.setdefault("feedback", {})
actual_delay = st.session_state["feedback"].get(fb_key)

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.markdown(metric_card("SCHEDULED ARRIVAL", result["sch_arr"], current_station, "rc-blue", icon="🕐"), unsafe_allow_html=True)
with c2:
    st.markdown(metric_card(
        "RAILCAST PREDICTED ARRIVAL", result["predicted_eta"],
        f"+{predicted_delay:.0f} min delay", "rc-green", highlight=True, icon="🎯", delta=predicted_delay
    ), unsafe_allow_html=True)
with c3:
    if actual_delay is not None:
        actual_eta = compute_eta_client(result["sch_arr"], actual_delay)
        st.markdown(metric_card("ACTUAL ARRIVAL", actual_eta, f"+{actual_delay:.0f} min delay", "rc-orange", icon="✅", delta=actual_delay), unsafe_allow_html=True)
    else:
        st.markdown(pending_card("ACTUAL ARRIVAL", "Log it below to fill this in."), unsafe_allow_html=True)
with c4:
    if actual_delay is not None:
        error_min = abs(predicted_delay - actual_delay)
        st.markdown(metric_card("PREDICTION ERROR", f"{error_min:.0f} min", "Our prediction vs actual", "rc-purple", icon="📏"), unsafe_allow_html=True)
    else:
        st.markdown(pending_card("PREDICTION ERROR", "Needs an actual arrival to compare."), unsafe_allow_html=True)
with c5:
    # Judged by actual delay when we have it, so this card and the Actual
    # Arrival card are never contradicting each other.
    effective_delay = actual_delay if actual_delay is not None else predicted_delay
    is_delayed = effective_delay >= 10
    css = "rc-red" if is_delayed else "rc-green"
    status_text = "DELAYED" if is_delayed else "ON TIME"
    status_icon = "⚠️" if is_delayed else "✅"
    if effective_delay <= 0:
        status_msg = "Train is running on schedule."
    elif effective_delay < 10:
        status_msg = "Train is running with a small delay."
    else:
        status_msg = "Train is running behind schedule."
    progress_pct = round(min(100, ((row_index + 1) / max(1, len(journey_df))) * 100))
    sub = f"{status_msg} Currently at: {current_station} → Next: {result['next_station']}"
    st.markdown(status_card(status_text, sub, css, progress_pct, icon=status_icon), unsafe_allow_html=True)

if result.get("disruption_note"):
    st.info(f"Simulated event: {result['disruption_note']}")
if result.get("network_note"):
    st.warning(f"🔗 **Network effect:** {result['network_note']}")

st.write("")

# =============================================================================
# TOP ROW — MAP + TIMELINE + (OFFICER-ONLY) OPERATIONAL ACTIONS
# Only Operational Actions lives in the third column now, so all three
# columns stay roughly equal height — this is what removes the big white-
# space gap that showed up when Why-this-prediction and Seasonal Risk were
# also stacked in this narrow column.
# =============================================================================
if page == "Control Room / Officer":
    map_col, timeline_col, side_col = st.columns([2, 2, 1.5])
else:
    # No Operational Actions panel in Passenger view, so there's no third
    # column to fill — give the map and timeline more room instead, with a
    # visible gap between them, rather than leaving blank space on the right.
    map_col, timeline_col = st.columns([1, 1], gap="large")
    side_col = None

with map_col:
    st.markdown('<div class="rc-panel"><h4>📍 Route Map</h4>', unsafe_allow_html=True)
    if HAS_MAP and {"latitude", "longitude"}.issubset(journey_df.columns):
        # Plain OpenStreetMap tiles only — always free, no API key, no
        # "API key required" watermark.
        m = folium.Map(tiles="OpenStreetMap")
        coords = list(zip(journey_df["latitude"], journey_df["longitude"]))
        folium.PolyLine(coords, color="#2563eb", weight=3).add_to(m)
        highlight_station = live_state["station"] if live_state else current_station
        for _, r in journey_df.iterrows():
            is_current = r["station"] == highlight_station
            folium.CircleMarker(
                [r["latitude"], r["longitude"]],
                radius=7 if is_current else 4,
                color="#16a34a" if is_current else "#dc2626",
                fill=True, fill_opacity=1,
                tooltip=r["station"],
            ).add_to(m)
        m.fit_bounds(coords)
        st_folium(m, height=330, use_container_width=True)
    else:
        st.write("Add latitude/longitude to demo_data.csv (or to /train/{id}/journey) to enable the map.")
    st.markdown('</div>', unsafe_allow_html=True)

with timeline_col:
    st.markdown('<div class="rc-panel"><h4>🕐 Station Timeline</h4>', unsafe_allow_html=True)
    display_cols = [c for c in ["station", "next_station", "sch_arr", "eta", "predicted_delay", "low", "high"] if c in forecast.columns]
    timeline_table = forecast[display_cols].round(1)
    # Light green → amber → red gradient on predicted_delay so the worst
    # stations pop out without reading every row.
    st.dataframe(style_delay_heatmap(timeline_table), hide_index=True, use_container_width=True)
    st.caption("Confidence range widens with each station further into the journey — cascading uncertainty. Darker red = higher predicted delay.")
    st.markdown('</div>', unsafe_allow_html=True)

if page == "Control Room / Officer":
    with side_col:
        st.markdown('<div class="rc-panel"><h4>🔧 Operational Actions</h4>', unsafe_allow_html=True)
        for action in result["actions"]:
            level = status_color_level(action["type"]) if action["type"] != "Status" else "green"
            if level == "gray":
                level = "amber"  # non-Status actions default to amber, matching the old st.warning look
            st.markdown(
                f'<div style="margin-bottom:10px; display:flex; align-items:flex-start; gap:8px;">'
                f'{pill_badge(action["type"], level)}'
                f'<span style="font-size:0.85rem; color:#334155; line-height:1.4;">{action["message"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
# SECOND ROW — WHY THIS PREDICTION + SEASONAL RISK (both views, full width,
# 50/50 split)
# =============================================================================
why_col, risk_col = st.columns(2)
with why_col:
    st.markdown('<div class="rc-panel"><h4>ℹ️ Why this prediction?</h4>', unsafe_allow_html=True)
    drivers = result["top_drivers"]
    st.write(f"Mainly driven by: **{drivers[0]['feature']}** ({drivers[0]['direction']} the delay)")
    if len(drivers) > 1:
        st.write(f"Also contributing: **{drivers[1]['feature']}**")
    st.write(f"Current weather: **{result['weather_label']}**")
    st.markdown('</div>', unsafe_allow_html=True)

with risk_col:
    st.markdown('<div class="rc-panel"><h4>🌫️ Seasonal Risk</h4>', unsafe_allow_html=True)
    with st.spinner(""):
        risk = api_risk(selected_train)
    st.markdown(pill_badge(risk["risk"], status_color_level(risk["risk"])), unsafe_allow_html=True)
    st.caption(risk.get("message", ""))
    st.markdown('</div>', unsafe_allow_html=True)

st.write("")

# =============================================================================
# DISRUPTION SIMULATOR (+ PASSENGER FEEDBACK ONLY IN PASSENGER VIEW)
# =============================================================================
if page == "Control Room / Officer":
    st.markdown('<div class="rc-panel"><h4>⚡ What-if Disruption Simulator</h4>', unsafe_allow_html=True)
    st.caption("What happens if there is an operating disruption?")
    max_bar = max(10.0, original_delay, predicted_delay)
    bars_html = mini_bar("Normal", original_delay, max_bar, "#2563eb")
    if disruption != "None":
        bars_html += mini_bar(disruption, predicted_delay, max_bar, "#dc2626")
    st.markdown(bars_html, unsafe_allow_html=True)
    if disruption != "None":
        delta = predicted_delay - original_delay
        direction = "increases" if delta >= 0 else "decreases"
        st.markdown(
            f'<div style="background:#FEE2E2; color:#991B1B; padding:10px 14px; border-radius:10px; margin-top:8px; font-size:0.85rem;">'
            f'The selected disruption {direction} the forecast by {abs(delta):.1f} minutes.</div>',
            unsafe_allow_html=True,
        )
    if result.get("disruption_shift"):
        shift = result["disruption_shift"]
        s_direction = "increased" if shift["shift"] > 0 else "decreased"
        st.info(f"**Disruption impact:** {shift['feature']}'s contribution to delay {s_direction} by {abs(shift['shift']):.1f} min due to the simulated event.")
    st.markdown('</div>', unsafe_allow_html=True)
else:
    sim_col, feedback_col = st.columns([1.3, 1])
    with sim_col:
        st.markdown('<div class="rc-panel"><h4>⚡ What-if Disruption Simulator</h4>', unsafe_allow_html=True)
        st.caption("What happens if there is an operating disruption?")
        max_bar = max(10.0, original_delay, predicted_delay)
        bars_html = mini_bar("Normal", original_delay, max_bar, "#2563eb")
        if disruption != "None":
            bars_html += mini_bar(disruption, predicted_delay, max_bar, "#dc2626")
        st.markdown(bars_html, unsafe_allow_html=True)
        if disruption != "None":
            delta = predicted_delay - original_delay
            direction = "increases" if delta >= 0 else "decreases"
            st.markdown(
                f'<div style="background:#FEE2E2; color:#991B1B; padding:10px 14px; border-radius:10px; margin-top:8px; font-size:0.85rem;">'
                f'The selected disruption {direction} the forecast by {abs(delta):.1f} minutes.</div>',
                unsafe_allow_html=True,
            )
        if result.get("disruption_shift"):
            shift = result["disruption_shift"]
            s_direction = "increased" if shift["shift"] > 0 else "decreased"
            st.info(f"**Disruption impact:** {shift['feature']}'s contribution to delay {s_direction} by {abs(shift['shift']):.1f} min due to the simulated event.")
        st.markdown('</div>', unsafe_allow_html=True)
    with feedback_col:
        st.markdown('<div class="rc-panel"><h4>📝 Passenger Feedback</h4>', unsafe_allow_html=True)
        st.caption("Record the actual delay experienced at this station.")
        actual_delay_input = st.number_input("Actual delay experienced (minutes)", value=0, key=f"fb_input_{fb_key}")
        if st.button("Submit actual delay"):
            st.session_state["feedback"][fb_key] = float(actual_delay_input)
            st.success("Actual delay recorded successfully!")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

# =============================================================================
# BOTTOM — OPERATING CONDITIONS (CURRENT SECTION)
# =============================================================================
cond = result.get("conditions", {})
weather_icon = WEATHER_ICONS.get(cond.get("weather"), "🌤️")
st.markdown('<div class="rc-panel"><h4>🌐 Operating Conditions (Current Section)</h4>'
    '<div class="rc-oc-grid">'
    + oc_item(weather_icon, "WEATHER", cond.get("weather", "--"), "purple")
    + oc_item("👁️", "VISIBILITY", f'{cond.get("visibility_m", "--")} m', "slate")
    + oc_item("💧", "RAINFALL", f'{cond.get("rainfall_mm", "--")} mm', "blue")
    + oc_item("🌡️", "TEMPERATURE", f'{cond.get("temperature_c", "--")} °C', "orange")
    + oc_item("🚗", "CONGESTION", f'{cond.get("congestion_score", "--")}', "red")
    + oc_item("⏱️", "SECTION TIME", f'{cond.get("section_time_min", "--")} min', "green")
    + '</div></div>', unsafe_allow_html=True)