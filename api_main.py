"""
RailCast API — FastAPI backend
================================
Wraps the exact model artifacts your Streamlit app already loads
(xgb_model.pkl, residual_model.pkl, feature_columns.pkl, residual_features.pkl,
demo_data.csv). Put this file in the SAME folder as those 5 files.

You normally do NOT run this file directly anymore — use run_all.py, which
starts this API in the background and then launches the dashboard, all in
one terminal. (You can still run it standalone with
`uvicorn api_main:app --port 8000` for debugging, e.g. via /docs.)

Endpoints:
    GET  /                         -> health check
    POST /predict                  -> single-station prediction (now includes clock-time ETA + conditions)
    GET  /train/{train_id}/eta     -> full multi-station cascading forecast (#1), each row now has an "eta"
    GET  /train/{train_id}/actions -> operational actions for current state
    GET  /train/{train_id}/risk    -> seasonal risk advisory
    POST /simulate/start           -> start the replay-as-live-feed simulator (#3)
    POST /simulate/stop            -> stop it
    GET  /simulate/state           -> current simulated positions of all trains (#3)
    GET  /simulate/state/{train_id}-> current simulated position of one train
"""

import threading
import time
from typing import Optional, List, Dict, Any

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Load model artifacts — identical to what app.py already does
# ---------------------------------------------------------------------------
xgb_model = joblib.load("xgb_model.pkl")
residual_model = joblib.load("residual_model.pkl")
feature_columns = joblib.load("feature_columns.pkl")
residual_features = joblib.load("residual_features.pkl")
demo_data = pd.read_csv("demo_data.csv")
# ---------------------------------------------------------------------------
# Seasonal risk: computed from actual historical delay-by-month in demo_data,
# instead of hardcoded month lists. Falls back to the fog-belt heuristic when
# a month has too few samples to trust.
# ---------------------------------------------------------------------------
MIN_SAMPLES_PER_MONTH = 5

def _build_monthly_delay_table(df: pd.DataFrame):
    if "date" not in df.columns or "delay_minutes" not in df.columns:
        return {}, None, None
    dates = pd.to_datetime(df["date"], errors="coerce")
    valid = df.loc[dates.notna()].copy()
    valid["month"] = dates[dates.notna()].dt.month
    monthly_avg = valid.groupby("month")["delay_minutes"].agg(["mean", "count"])
    monthly_avg = monthly_avg[monthly_avg["count"] >= MIN_SAMPLES_PER_MONTH]
    if monthly_avg.empty:
        return {}, None, None
    low_cut = monthly_avg["mean"].quantile(0.33)
    high_cut = monthly_avg["mean"].quantile(0.66)
    return monthly_avg["mean"].to_dict(), low_cut, high_cut

MONTHLY_DELAY_TABLE, DELAY_LOW_CUT, DELAY_HIGH_CUT = _build_monthly_delay_table(demo_data)

XGB_MAE = 7.88

readable_names = {
    "rainfall_mm": "rainfall", "visibility_m": "low visibility / fog",
    "temperature_c": "temperature", "congestion_score": "congestion on this stretch",
    "historical_section_time": "typically slow section", "distance_to_next": "distance to next station",
    "station_sequence": "position along the route", "hour": "time of day", "day_of_week": "day of week",
}

DISRUPTION_FEATURE_MAP = {
    "Fog": "visibility_m", "Heavy Rain / Storm": "rainfall_mm",
    "Speed Restriction": "historical_section_time", "Track Congestion Spike": "congestion_score",
}

app = FastAPI(title="RailCast API", version="1.1")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# =============================================================================
# NEW: clock-time ETA helper — turns "sch_arr + predicted delay" into an
# actual time like "06:04 PM", which is what the dashboard's headline
# ETA card now shows instead of just "+4 min".
# =============================================================================
def compute_arrival_time(sch_arr: Any, delay_minutes: float) -> str:
    if sch_arr in (None, "--", "") or pd.isna(sch_arr):
        return "--"
    try:
        base = pd.to_datetime(str(sch_arr))
    except Exception:
        return "--"
    arrival = base + pd.Timedelta(minutes=float(delay_minutes))
    return arrival.strftime("%H:%M")


# =============================================================================
# CORE MODEL FUNCTIONS (ported 1:1 from app.py — behaviour is unchanged)
# =============================================================================
def apply_disruption(row: pd.Series, disruption: str):
    sim_row = row.copy()
    note, label = "", row.get("weather_condition_passenger", "Clear")
    if disruption == "Fog":
        sim_row["visibility_m"] = 150
        sim_row["temperature_c"] = sim_row["temperature_c"] - 3
        note, label = "Visibility dropped to 150m (dense fog conditions)", "Foggy"
    elif disruption == "Heavy Rain / Storm":
        sim_row["rainfall_mm"] = 80
        note, label = "Rainfall spiked to 80mm (storm-level rainfall)", "Heavy Rain / Storm"
    elif disruption == "Speed Restriction":
        sim_row["historical_section_time"] = sim_row["historical_section_time"] * 1.5
        note, label = "Section running time increased 50% (temporary speed restriction)", "Speed Restriction in effect"
    elif disruption == "Signal Halt / Unscheduled Stoppage":
        sim_row["delay_minutes"] = sim_row["delay_minutes"] + 25
        note, label = "Train held 25 extra minutes at a signal", "Signal Halt in effect"
    elif disruption == "Track Congestion Spike":
        sim_row["congestion_score"] = 0.95
        note, label = "Downstream section congestion spiked to near-maximum", "Track Congestion Spike"
    elif disruption == "Unscheduled Maintenance Block":
        sim_row["delay_minutes"] = sim_row["delay_minutes"] + 45
        note, label = "Unscheduled maintenance block adding 45 minutes", "Maintenance Block in effect"
    return sim_row, note, label


def predict_delay(row: pd.Series) -> float:
    X = pd.DataFrame([row[feature_columns]]).apply(pd.to_numeric)
    return float(xgb_model.predict(X)[0])


def explain_row_detailed(row_before: pd.Series, row_after: pd.Series, disruption_feature: Optional[str] = None):
    def get_contribs(row):
        row_df = row[residual_features].to_frame().T.apply(pd.to_numeric)
        dmat = xgb.DMatrix(row_df, feature_names=residual_features)
        return residual_model.get_booster().predict(dmat, pred_contribs=True)[0][:-1]

    contribs_after = get_contribs(row_after)
    top2_idx = np.argsort(np.abs(contribs_after))[::-1][:2]
    top_drivers = []
    for idx in top2_idx:
        feat = residual_features[idx]
        direction = "increasing" if contribs_after[idx] > 0 else "reducing"
        top_drivers.append({"feature": readable_names.get(feat, feat), "direction": direction})

    disruption_shift = None
    if disruption_feature and disruption_feature in residual_features:
        contribs_before = get_contribs(row_before)
        idx = residual_features.index(disruption_feature)
        shift = float(contribs_after[idx] - contribs_before[idx])
        disruption_shift = {"feature": readable_names.get(disruption_feature, disruption_feature), "shift": shift}

    return top_drivers, disruption_shift


def get_operational_actions(predicted_delay: float, next_station: str):
    actions = []
    if predicted_delay > 15:
        actions.append({"type": "Feeder Transport", "message": f"Notify feeder transport at {next_station}: {predicted_delay:.0f} min delay."})
    if predicted_delay > 10:
        actions.append({"type": "Crew", "message": f"Crew changeover at {next_station} may be impacted — notify scheduling desk."})
    if predicted_delay > 7:
        actions.append({"type": "Platform", "message": f"Delay risk at {next_station} — check for platform conflicts."})
    if predicted_delay > 4:
        actions.append({"type": "Cleaning", "message": f"Cleaning crew at {next_station}: adjust turnaround window."})
    if not actions:
        actions.append({"type": "Status", "message": "On schedule — no operational action needed."})
    return actions


FOG_BELT_LATITUDE = 24.0
FOG_SEASON_MONTHS = [12, 1]

def get_seasonal_risk_advisory(journey_stations_df: pd.DataFrame, journey_month: Optional[int] = None):
    if journey_month is None:
        journey_month = pd.Timestamp.now().month

    max_lat = journey_stations_df["latitude"].max()
    passes_fog_belt = pd.notna(max_lat) and max_lat >= FOG_BELT_LATITUDE
    in_fog_season = journey_month in FOG_SEASON_MONTHS

    if passes_fog_belt and in_fog_season:
        return {"risk": "Elevated", "message": "This route and month historically see denser fog and longer delays than usual."}

    avg_delay = MONTHLY_DELAY_TABLE.get(journey_month)
    if avg_delay is not None and DELAY_LOW_CUT is not None:
        if avg_delay >= DELAY_HIGH_CUT:
            return {"risk": "Elevated", "message": "This month has historically averaged higher delays than most other months on this route."}
        if avg_delay >= DELAY_LOW_CUT:
            return {"risk": "Moderate", "message": "This month has historically averaged somewhat higher delays than the yearly baseline."}
        return {"risk": "Low", "message": "This month has historically averaged delays around or below the yearly baseline."}

    if journey_month in [6, 7, 8, 9]:
        return {"risk": "Moderate", "message": "Monsoon-season months tend to see more rain-related delays across most routes."}
    return {"risk": "Low", "message": "No strong seasonal delay pattern found for this month on this route."}

def forecast_full_journey(journey_df: pd.DataFrame, base_delay: float) -> pd.DataFrame:
    results = []
    current_delay = base_delay
    for step, row in enumerate(journey_df.itertuples(), start=1):
        input_row = row._asdict()
        input_row["delay_minutes"] = current_delay
        X_step = pd.DataFrame([{col: input_row[col] for col in feature_columns}]).apply(pd.to_numeric)
        predicted = float(xgb_model.predict(X_step)[0])
        width = XGB_MAE * (step ** 0.5)
        results.append({
            "station": input_row["station"], "next_station": input_row["next_station"],
            "sch_arr": input_row.get("sch_arr", "--"),
            "eta": compute_arrival_time(input_row.get("sch_arr"), predicted),
            "predicted_delay": predicted, "low": predicted - width, "high": predicted + width,
        })
        current_delay = predicted
    return pd.DataFrame(results)


# =============================================================================
# #2 — TRAIN-TO-TRAIN INTERACTION (network / conflict effect)
# =============================================================================
live_state: Dict[int, Dict[str, Any]] = {}
state_lock = threading.Lock()


def get_preceding_train_delay(train_id: int, station: str, next_station: str) -> Optional[float]:
    with state_lock:
        for other_id, state in live_state.items():
            if other_id == train_id:
                continue
            if state["station"] == station and state["next_station"] == next_station:
                return state["delay_minutes"]
    return None


def apply_network_effect(row: pd.Series, predicted_delay: float, train_id: int):
    preceding_delay = get_preceding_train_delay(train_id, row["station"], row["next_station"])
    if preceding_delay is None or preceding_delay <= 5:
        return predicted_delay, None

    network_bump = min(preceding_delay * 0.2, 15)  # capped so it can't dominate
    adjusted = predicted_delay + network_bump
    note = (f"A preceding train on this section is currently running "
            f"{preceding_delay:.0f} min late — adding {network_bump:.1f} min network effect.")
    return adjusted, note


# =============================================================================
# #3 — LIVE FEED SIMULATOR (replays demo_data as if time were moving)
# =============================================================================
_sim_thread: Optional[threading.Thread] = None
_sim_running = False
_sim_speed_seconds = 8  # advance one station every N seconds (slowed down — was causing extra load at 5s)


def _simulate_loop():
    global _sim_running
    trains = demo_data["train"].unique().tolist()
    cursors = {t: 0 for t in trains}
    journeys = {t: demo_data[demo_data["train"] == t].reset_index(drop=True) for t in trains}

    while _sim_running:
        with state_lock:
            for train_id in trains:
                journey = journeys[train_id]
                idx = cursors[train_id]
                if idx >= len(journey):
                    idx = 0  # loop the demo so the dashboard always has something live
                row = journey.iloc[idx]
                predicted = predict_delay(row)
                live_state[train_id] = {
                    "station": row["station"],
                    "next_station": row["next_station"],
                    "sch_arr": row.get("sch_arr", "--"),
                    "delay_minutes": float(predicted),
                    "updated_at": time.time(),
                }
                cursors[train_id] = idx + 1
        time.sleep(_sim_speed_seconds)


@app.post("/simulate/start")
def start_simulation(speed_seconds: int = 8):
    global _sim_thread, _sim_running, _sim_speed_seconds
    if _sim_running:
        return {"status": "already running"}
    _sim_speed_seconds = max(1, speed_seconds)
    _sim_running = True
    _sim_thread = threading.Thread(target=_simulate_loop, daemon=True)
    _sim_thread.start()
    return {"status": "started", "speed_seconds": _sim_speed_seconds}


@app.post("/simulate/stop")
def stop_simulation():
    global _sim_running
    _sim_running = False
    return {"status": "stopped"}


@app.get("/simulate/state")
def get_simulation_state():
    with state_lock:
        return {str(k): v for k, v in live_state.items()}


@app.get("/simulate/state/{train_id}")
def get_simulation_state_for_train(train_id: int):
    with state_lock:
        state = live_state.get(train_id)
    if state is None:
        raise HTTPException(404, f"No live state yet for train {train_id}. Call /simulate/start first.")
    return state


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================
class PredictRequest(BaseModel):
    train: int
    station: str
    date: Optional[str] = None
    disruption: Optional[str] = "None"


# =============================================================================
# ENDPOINTS
# =============================================================================
@app.get("/")
def health():
    return {"status": "ok", "model_mae_minutes": XGB_MAE, "trains_available": int(demo_data["train"].nunique())}


@app.post("/predict")
def predict(req: PredictRequest):
    train_rows = demo_data[demo_data["train"] == req.train].reset_index(drop=True)
    if train_rows.empty:
        raise HTTPException(404, f"Train {req.train} not found in demo_data.")
    match = train_rows[train_rows["station"] == req.station]
    if req.date and "date" in match.columns:
        date_match = match[match["date"].astype(str) == str(req.date)]
        if not date_match.empty:
            match = date_match
    if match.empty:
        raise HTTPException(404, f"Station {req.station} not on train {req.train}'s route.")
    current_row = match.iloc[0]

    sim_row, disruption_note, weather_label = apply_disruption(current_row, req.disruption or "None")

    original_pred = predict_delay(current_row)
    predicted = predict_delay(sim_row)

    # #2 — network effect from any preceding train on the same section
    predicted, network_note = apply_network_effect(sim_row, predicted, req.train)

    top_drivers, disruption_shift = explain_row_detailed(
        current_row, sim_row, DISRUPTION_FEATURE_MAP.get(req.disruption or "None")
    )

    sch_arr = current_row.get("sch_arr", "--")

    return {
        "train": req.train,
        "station": req.station,
        "next_station": current_row["next_station"],
        "sch_arr": sch_arr,
        "original_predicted_delay": round(original_pred, 1),
        "predicted_delay": round(predicted, 1),
        # NEW — actual clock-time ETA, this is what the headline dashboard card shows now
        "original_eta": compute_arrival_time(sch_arr, original_pred),
        "predicted_eta": compute_arrival_time(sch_arr, predicted),
        "confidence_range_minutes": XGB_MAE,
        "disruption_note": disruption_note,
        "network_note": network_note,
        "weather_label": weather_label,
        "top_drivers": top_drivers,
        "disruption_shift": disruption_shift,
        "actions": get_operational_actions(predicted, current_row["next_station"]),
        # NEW — feeds the bottom "Operating Conditions" strip
        "conditions": {
            "weather": weather_label,
            "visibility_m": sim_row.get("visibility_m"),
            "rainfall_mm": sim_row.get("rainfall_mm"),
            "temperature_c": sim_row.get("temperature_c"),
            "congestion_score": sim_row.get("congestion_score"),
            "section_time_min": sim_row.get("historical_section_time"),
        },
    }


@app.get("/train/{train_id}/eta")
def train_eta(train_id: int, from_station: Optional[str] = None, date: Optional[str] = None):
    train_rows = demo_data[demo_data["train"] == train_id].reset_index(drop=True)
    if train_rows.empty:
        raise HTTPException(404, f"Train {train_id} not found.")
    if date and "date" in train_rows.columns:
        date_rows = train_rows[train_rows["date"].astype(str) == str(date)].reset_index(drop=True)
        if not date_rows.empty:
            train_rows = date_rows
    if from_station:
        idx_matches = train_rows.index[train_rows["station"] == from_station]
        if len(idx_matches) == 0:
            raise HTTPException(404, f"Station {from_station} not on this route.")
        start_idx = idx_matches[0]
    else:
        start_idx = 0

    journey = train_rows.iloc[start_idx:]
    base_delay = float(journey.iloc[0]["delay_minutes"])
    forecast = forecast_full_journey(journey, base_delay)
    return forecast.to_dict(orient="records")


@app.get("/train/{train_id}/actions")
def train_actions(train_id: int, station: str):
    train_rows = demo_data[demo_data["train"] == train_id]
    row = train_rows[train_rows["station"] == station]
    if row.empty:
        raise HTTPException(404, "Not found")
    row = row.iloc[0]
    predicted = predict_delay(row)
    return get_operational_actions(predicted, row["next_station"])


@app.get("/train/{train_id}/risk")
def train_risk(train_id: int, journey_month: Optional[int] = None):
    train_rows = demo_data[demo_data["train"] == train_id]
    if train_rows.empty:
        raise HTTPException(404, "Not found")
    return get_seasonal_risk_advisory(train_rows, journey_month)


@app.get("/trains")
def list_trains():
    return sorted(demo_data["train"].unique().tolist())


@app.get("/train/{train_id}/journey")
def train_journey(train_id: int):
    rows = demo_data[demo_data["train"] == train_id]
    if rows.empty:
        raise HTTPException(404, "Not found")
    cols = ["station", "next_station", "sch_arr", "date", "latitude", "longitude", "delay_minutes"]
    return rows[[c for c in cols if c in rows.columns]].to_dict(orient="records")