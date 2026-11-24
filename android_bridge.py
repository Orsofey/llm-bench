"""Мост Chaquopy: локальный HTTP-движок внутри Android-приложения."""
import os
import threading

_server = None
_port = None


def start(data_dir):
    global _server, _port
    if _server is not None:
        return _port
    os.environ["LLM_BENCH_PLATFORM"] = "android"
    os.environ["LLM_BENCH_DATA_DIR"] = str(data_dir)
    os.environ.pop("LLM_BENCH_PORT", None)
    import app
    try:
        _server = app.create_server()
    except OSError:
        _server = app.create_server(0)
    _port = _server.server_address[1]
    threading.Thread(target=_server.serve_forever, name="llm-bench-android", daemon=True).start()
    return _port
