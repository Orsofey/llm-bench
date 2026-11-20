"""
Сквозной тест без сети и ключей: поднимает фейковый OpenAI-совместимый сервис
и прогоняет бенчмарк целиком (подлинность + все задачи + сохранение отчёта + пакет).
Запуск: python tests/smoke_test.py
"""
import json, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import batch, bench  # noqa: E402


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, d, code=200):
        b = json.dumps(d).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send({"data": [{"id": "fake-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        p = body["messages"][0]["content"]
        self._send({"model": "fake-model", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": len(p) // 4 + 5, "completion_tokens": 1}})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/v1"
    with tempfile.TemporaryDirectory() as out:
        events = []
        fn = bench.run_benchmark({"provider": "openai", "base_url": base, "key": "k", "model": "fake-model",
                                  "ctx_chars": 3000, "workers": 4, "out": out, "save_ref": "Fake (официальный)"}, events.append)
        errors = [e for e in events if e["type"] == "error"]
        assert fn and not errors, f"прогон упал: {errors}"
        rep = json.loads(Path(fn).read_text(encoding="utf-8"))
        assert len(rep["tasks"]) == len(bench.TASKS) + 1, "не все задачи в отчёте"
        assert rep["verify"]["fingerprint"]["ok"], "отпечаток не снят"
        assert rep["tokens"]["requests"] > 0, "не посчитаны запросы"
        assert (Path(out) / "references.json").exists(), "эталон не сохранён"

        events = []
        import threading as th
        bfn = batch.run_batch({"text": f"{base} ; secret_key_123456789 ; Shop ; 100 ; 1 млн", "model": "fake-model",
                               "claimed": "Fake", "depth": "full"}, out, events.append, th.Event())
        rows = json.loads(Path(bfn).read_text(encoding="utf-8"))["rows"]
        assert rows[0]["status"] == "ok", rows[0]
        assert rows[0]["verdict"] == "ok", f"эталон не опознан: {rows[0].get('verdict_text')}"
        assert "secret_key_123456789" not in Path(bfn).read_text(encoding="utf-8"), "в отчёте полный ключ"
    srv.shutdown()
    print("OK: прогон, подлинность, эталон и пакетная проверка работают")


if __name__ == "__main__":
    main()
