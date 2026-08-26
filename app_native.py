"""
app_native.py — Windrose as a real desktop app.

Runs the same server in a background thread and opens a native macOS window
around it (pywebview / WKWebView) instead of a browser tab. Requires:

    venv/bin/pip install pywebview

Then launch via Windrose.app, or:  venv/bin/python app_native.py
"""
import threading, time, urllib.request

import app as ledger

def _serve():
    ledger.app.run(host="127.0.0.1", port=ledger.PORT, threaded=True,
                   debug=False, use_reloader=False)

ledger.start_background()
threading.Thread(target=_serve, daemon=True).start()

_url = f"http://127.0.0.1:{ledger.PORT}"

for _ in range(240):
    try:
        urllib.request.urlopen(f"{_url}/api/status", timeout=1)
        break
    except Exception:
        time.sleep(0.5)

import webview  # pywebview
webview.create_window(f"Windrose v{ledger.LEDGER_VERSION}",
                      _url,
                      width=1480, height=940, min_size=(1000, 700))
webview.start()
