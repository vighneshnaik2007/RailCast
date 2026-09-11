"""
run_all.py — starts everything with ONE command, in ONE terminal.

Usage (from inside your eta-dashboard folder, with your venv active):
    python run_all.py

What it does:
    1. Starts api_main.py's FastAPI app with uvicorn, in a background thread
       (no --reload, no second window — this is what removes the second
       PowerShell you had to keep open).
    2. Polls http://localhost:8000/ until the API responds (avoids the
       dashboard loading before the model has finished loading).
    3. Runs `streamlit run dashboard_app.py` in THIS terminal, in the
       foreground, so Ctrl+C here shuts down both cleanly.
"""

import subprocess
import sys
import threading
import time

import requests
import uvicorn

from api_main import app as fastapi_app

API_HOST = "127.0.0.1"
API_PORT = 8000


def _run_api():
    uvicorn.run(fastapi_app, host=API_HOST, port=API_PORT, log_level="warning")


def _wait_for_api(timeout_seconds: int = 20) -> bool:
    url = f"http://{API_HOST}:{API_PORT}/"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    print("Starting RailCast API in the background...")
    api_thread = threading.Thread(target=_run_api, daemon=True)
    api_thread.start()

    if not _wait_for_api():
        print("API didn't come up in time — check for errors above (e.g. a missing .pkl file).")
        sys.exit(1)

    print(f"API is up at http://{API_HOST}:{API_PORT}  (docs at /docs)")
    print("Launching the RailCast dashboard...\n")

    # Runs in THIS terminal, in the foreground, so you see Streamlit's own logs
    # and Ctrl+C stops both the dashboard and (since the API thread is a daemon)
    # the API too.
    subprocess.run([sys.executable, "-m", "streamlit", "run", "dashboard_app.py"])


if __name__ == "__main__":
    main()