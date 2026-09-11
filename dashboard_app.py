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
    .stApp { background-color: #F1F5F9; }
    section[data-testid="stSidebar"] { background-color: #0B1220; }
    section[data-testid="stSidebar"] * { color: #E7EBF5 !important; }

    .rc-logo { font-size: 1.3rem; font-weight: 800; color: white; }
    .rc-nav-item { padding: 8px 12px; border-radius: 8px; margin-bottom: 4px; color: #94A3B8; font-size: 0.92rem; }
    .rc-nav-active { background: #2563EB; color: white !important; font-weight: 600; }
    .rc-mae { font-size: 1.4rem; font-weight: 800; color: white; }

    .rc-hero {
        border-radius: 16px; padding: 26px 30px; margin-bottom: 16px;
        background: linear-gradient(120deg, #0B1220 0%, #1E3A8A 55%, #2563EB 100%);
        color: white; position: relative; overflow: hidden;
    }
    .rc-hero h1 { margin: 0; font-size: 1.7rem; font-style: italic; }
    .rc-tricolor { height: 4px; width: 90px; margin: 6px 0 8px 0;
        background: linear-gradient(90deg, #FF9933 33%, #FFFFFF 33%, #FFFFFF 66%, #138808 66%); border-radius: 2px; }
    .rc-hero p { margin: 0; color: #CBD5E1; font-style: italic; font-size: 0.95rem; }

    .rc-card { border-radius: 14px; padding: 16px 18px; color: white; min-height: 96px; }
    .rc-card .rc-label { font-size: 0.75rem; opacity: 0.9; letter-spacing: 0.03em; margin-bottom: 6px; }
    .rc-card .rc-value { font-size: 1.55rem; font-weight: 800; }
    .rc-card .rc-sub { font-size: 0.72rem; opacity: 0.9; margin-top: 3px; }

    .rc-blue   { background: linear-gradient(135deg, #3b82f6, #2563eb); }
    .rc-green  { background: linear-gradient(135deg, #22c55e, #16a34a); }
    .rc-orange { background: linear-gradient(135deg, #fb923c, #ea580c); }
    .rc-purple { background: linear-gradient(135deg, #a78bfa, #7c3aed); }
    .rc-red    { background: linear-gradient(135deg, #f87171, #dc2626); }
    .rc-gray   { background: linear-gradient(135deg, #94a3b8, #64748b); }

    .rc-highlight { border: 3px solid #FACC15; box-shadow: 0 0 0 4px rgba(250,204,21,0.25), 0 4px 14px rgba(0,0,0,0.15); }

    .rc-panel { background: white; border-radius: 14px; padding: 16px 18px; box-shadow: 0 1px 3px rgba(20,20,50,0.06); margin-bottom: 14px; }
    .rc-panel h4 { margin-top: 0; margin-bottom: 10px; }

    .rc-badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 600; }
    .rc-badge-live { background: #dcfce7; color: #166534; }
    .rc-badge-delay { background: #fee2e2; color: #991b1b; }

    .rc-progress-track { background: #E2E8F0; border-radius: 999px; height: 8px; width: 100%; }
    .rc-progress-fill { background: #22c55e; border-radius: 999px; height: 8px; }

    .rc-bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 0.82rem; }
    .rc-bar-label { width: 60px; color: #475569; }
    .rc-bar-track { flex: 1; background: #E2E8F0; border-radius: 6px; height: 14px; position: relative; }
    .rc-bar-fill { height: 14px; border-radius: 6px; }
    .rc-bar-value { width: 46px; text-align: right; font-weight: 600; color: #0F172A; }

    .rc-oc-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; text-align: center; }
    .rc-oc-item { background: #F8FAFC; border-radius: 10px; padding: 10px 6px; }
    .rc-oc-item .rc-oc-icon { font-size: 1.2rem; }
    .rc-oc-item .rc-oc-label { font-size: 0.68rem; color: #64748B; margin: 4px 0 2px 0; }
    .rc-oc-item .rc-oc-value { font-weight: 700; color: #0F172A; font-size: 0.88rem; }

    div[data-testid="stMetricValue"] { font-size: 1.4rem; }
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
def metric_card(label, value, sub="", css="rc-blue", highlight=False):
    classes = f"rc-card {css}" + (" rc-highlight" if highlight else "")
    sub_html = f'<div class="rc-sub">{sub}</div>' if sub else ""
    return f'<div class="{classes}"><div class="rc-label">{label}</div><div class="rc-value">{value}</div>{sub_html}</div>'


def status_card(status, sub, css="rc-green", progress_pct=0):
    sub_html = f'<div class="rc-sub">{sub}</div>' if sub else ""
    bar = (f'<div class="rc-progress-track" style="margin-top:8px;">'
           f'<div class="rc-progress-fill" style="width:{progress_pct}%;"></div></div>')
    return f'<div class="rc-card {css}"><div class="rc-label">STATUS</div><div class="rc-value">{status}</div>{sub_html}{bar}</div>'


def mini_bar(label, minutes, max_minutes, color):
    pct = 0 if max_minutes <= 0 else min(100, (minutes / max_minutes) * 100)
    return (f'<div class="rc-bar-row"><div class="rc-bar-label">{label}</div>'
            f'<div class="rc-bar-track"><div class="rc-bar-fill" style="width:{pct}%; background:{color};"></div></div>'
            f'<div class="rc-bar-value">{minutes:.0f} min</div></div>')


def oc_item(icon, label, value):
    return f'<div class="rc-oc-item"><div class="rc-oc-icon">{icon}</div><div class="rc-oc-label">{label}</div><div class="rc-oc-value">{value}</div></div>'


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
    st.markdown('<div class="rc-nav-item rc-nav-active">🏠 Dashboard</div>', unsafe_allow_html=True)
    page = st.radio("Dashboard view", ["Passenger View", "Control Room / Officer"], label_visibility="collapsed")
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

with st.spinner(""):
    result = api_predict(selected_train, current_station, disruption, current_date)
    forecast = api_eta(selected_train, current_station, current_date)

live_state = api_live_state().get(str(selected_train)) if live_on else None

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
    st.markdown(metric_card("SCHEDULED ARRIVAL", result["sch_arr"], current_station, "rc-blue"), unsafe_allow_html=True)
with c2:
    st.markdown(metric_card(
        "RAILCAST PREDICTED ARRIVAL", result["predicted_eta"],
        f"+{predicted_delay:.0f} min delay", "rc-green", highlight=True
    ), unsafe_allow_html=True)
with c3:
    if actual_delay is not None:
        actual_eta = compute_eta_client(result["sch_arr"], actual_delay)
        st.markdown(metric_card("ACTUAL ARRIVAL", actual_eta, f"+{actual_delay:.0f} min delay", "rc-orange"), unsafe_allow_html=True)
    else:
        st.markdown(metric_card("ACTUAL ARRIVAL", "--", "Awaiting passenger feedback", "rc-gray"), unsafe_allow_html=True)
with c4:
    if actual_delay is not None:
        error_min = abs(predicted_delay - actual_delay)
        st.markdown(metric_card("PREDICTION ERROR", f"{error_min:.0f} min", "Our prediction vs actual", "rc-purple"), unsafe_allow_html=True)
    else:
        st.markdown(metric_card("PREDICTION ERROR", "--", "Our prediction vs actual", "rc-gray"), unsafe_allow_html=True)
with c5:
    # Judged by actual delay when we have it, so this card and the Actual
    # Arrival card are never contradicting each other.
    effective_delay = actual_delay if actual_delay is not None else predicted_delay
    is_delayed = effective_delay >= 10
    css = "rc-red" if is_delayed else "rc-green"
    status_text = "DELAYED" if is_delayed else "ON TIME"
    if effective_delay <= 0:
        status_msg = "Train is running on schedule."
    elif effective_delay < 10:
        status_msg = "Train is running with a small delay."
    else:
        status_msg = "Train is running behind schedule."
    progress_pct = round(min(100, ((row_index + 1) / max(1, len(journey_df))) * 100))
    sub = f"{status_msg} Currently at: {current_station} → Next: {result['next_station']}"
    st.markdown(status_card(status_text, sub, css, progress_pct), unsafe_allow_html=True)

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
map_col, timeline_col, side_col = st.columns([2, 2, 1.5])

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
    st.dataframe(forecast[display_cols].round(1), hide_index=True, use_container_width=True)
    st.caption("Confidence range widens with each station further into the journey — cascading uncertainty.")
    st.markdown('</div>', unsafe_allow_html=True)

with side_col:
    if page == "Control Room / Officer":
        st.markdown('<div class="rc-panel"><h4>🔧 Operational Actions</h4>', unsafe_allow_html=True)
        for action in result["actions"]:
            if action["type"] == "Status":
                st.success(f"**{action['type']}**: {action['message']}")
            else:
                st.warning(f"**{action['type']}**: {action['message']}")
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
    st.write(f"**{risk['risk']}**")
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
    + oc_item(weather_icon, "WEATHER", cond.get("weather", "--"))
    + oc_item("👁️", "VISIBILITY", f'{cond.get("visibility_m", "--")} m')
    + oc_item("💧", "RAINFALL", f'{cond.get("rainfall_mm", "--")} mm')
    + oc_item("🌡️", "TEMPERATURE", f'{cond.get("temperature_c", "--")} °C')
    + oc_item("🚗", "CONGESTION", f'{cond.get("congestion_score", "--")}')
    + oc_item("⏱️", "SECTION TIME", f'{cond.get("section_time_min", "--")} min')
    + '</div></div>', unsafe_allow_html=True)