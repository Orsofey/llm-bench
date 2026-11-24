#!/usr/bin/env python3
"""Нативное Windows-окно LLM Bench на Edge WebView2."""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import app


def serve():
    """Фиксированный origin сохраняет настройки WebView между запусками."""
    try:
        srv = app.create_server()
    except OSError:
        srv = app.create_server(0)
    threading.Thread(target=srv.serve_forever, name="llm-bench-server", daemon=True).start()
    return srv


def smoke_test(path):
    srv = serve()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        with urllib.request.urlopen(base + "/api/env", timeout=10) as response:
            env = json.load(response)
        with urllib.request.urlopen(base + "/", timeout=10) as response:
            html = response.read().decode("utf-8")
        with urllib.request.urlopen(base + "/api/public/status", timeout=10) as response:
            public = json.load(response)
        python_score, python_note = app.bench.run_py(
            "def twice(x):\n    return x * 2\n", ["twice(4)==8", "twice('a')=='aa'"], timeout=5,
        )
        result = {"ok": "LLM Bench" in html and env.get("version") == "1.0.0" and python_score == 1.0
                          and public.get("total") == 118 and public.get("cached", 0) >= 3,
                  "port": srv.server_address[1], "platform": env.get("platform"),
                  "html_bytes": len(html.encode("utf-8")), "python_tests": python_note,
                  "public_cached": public.get("cached")}
        Path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        srv.shutdown()
        srv.server_close()


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--smoke-test":
        smoke_test(sys.argv[2])
        return
    srv = serve()
    try:
        import webview
        storage = app.DATA_DIR / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        webview.create_window(
            "LLM Bench — Orsofey",
            f"http://127.0.0.1:{srv.server_address[1]}",
            width=1440, height=940, min_size=(360, 640),
            background_color="#07070d",
        )
        webview.start(private_mode=False, storage_path=str(storage), debug=False)
    except Exception:
        import traceback
        app.DATA_DIR.mkdir(parents=True, exist_ok=True)
        details = traceback.format_exc()
        (app.DATA_DIR / "desktop-error.log").write_text(details, encoding="utf-8")
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "Не удалось запустить окно LLM Bench. Подробности: " + str(app.DATA_DIR / "desktop-error.log"),
                "LLM Bench", 0x10,
            )
        else:
            print(details, file=sys.stderr)
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    main()
