#!/usr/bin/env python3
"""Локальный веб-интерфейс LLM Bench: python app.py → http://127.0.0.1:8787"""
import json, os, shutil, sys, threading, time, uuid, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import batch
import local
import bench
import verify

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"
PORT = int(os.environ.get("LLM_BENCH_PORT", 8787))
_WATCH = [Path(__file__).parent / n for n in ("bench.py", "verify.py", "app.py", "batch.py", "local.py", "public.py")]
_STARTED = {str(f): f.stat().st_mtime for f in _WATCH if f.exists()}
RUNS = {}  # id -> {"events": [], "status": "running|done|error", "cancel": Event}


def env_info():
    return {"claude_cli": bool(shutil.which("claude")), "codex_cli": bool(shutil.which("codex")),
            "ffmpeg": bool(bench.FFMPEG and bench.FFPROBE),
            "categories": sorted({t["cat"] for t in bench.TASKS} | {"context"}),
            "tiktoken": bool(verify.builtin_refs()),
            # код обновили (git pull), а сервер работает на старом — нужен перезапуск
            "stale": any(f.exists() and f.stat().st_mtime != _STARTED.get(str(f)) for f in _WATCH)}


def check_key(cfg):
    res = {}
    if cfg["provider"] == "auto":
        found, tries = bench.detect(cfg.get("base_url"), cfg.get("key"), cfg.get("model"))
        res["tries"] = tries
        if not found:
            return {**res, "ok": False, "error": "Не удалось подобрать протокол"}
        res["detected"] = found
        cfg = {**cfg, **found}
    cl = bench.Client(cfg["provider"], cfg.get("base_url"), cfg.get("key"), cfg.get("model"), 64, 60, auth=cfg.get("auth"), retries=0)
    try:
        res["models"] = cl.models()
    except Exception as e:
        res["models_error"] = bench.explain(e, cl.base)
    if cfg.get("model") or cfg["provider"] in bench.CLI_PROVIDERS:
        try:
            r = cl.chat("Ответь одним словом: ok", max_tokens=32)
            res.update(ok=True, ping_sec=r["sec"], reply=r["text"][:60], served_model=r["served_model"])
        except Exception as e:
            res.update(ok=False, error=bench.explain(e, cl.base))
    else:
        res["ok"] = "models" in res
    return res


def start_run(cfg, job="run"):
    rid = uuid.uuid4().hex[:8]
    run = {"events": [], "status": "running", "cancel": threading.Event()}
    RUNS[rid] = run

    def emit(ev):
        ev["t"] = time.time()
        run["events"].append(ev)

    def worker():
        try:
            if job == "batch":
                fn = batch.run_batch(cfg, RESULTS, emit, run["cancel"])
            else:
                fn = bench.run_benchmark({**cfg, "out": str(RESULTS)}, emit, run["cancel"])
            run["status"] = "done" if fn else "error"
        except Exception as e:
            emit({"type": "error", "message": str(e)[:400]})
            run["status"] = "error"

    threading.Thread(target=worker, daemon=True).start()
    return rid


def list_results():
    out = []
    for f in sorted(RESULTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or "summary" not in d:
            continue
        out.append({"file": f.name, "label": d.get("label"), "date": d.get("date"), "provider": d.get("provider"),
                    "summary": d.get("summary"), "health": d.get("health"), "tokens": d.get("tokens"),
                    "claimed": d.get("claimed"), "verdict": ((d.get("verify") or {}).get("verdict") or {}).get("level"),
                    "has_fp": bool(((d.get("verify") or {}).get("fingerprint") or {}).get("deltas")),
                    "tasks": {t["id"]: t["score"] for t in d.get("tasks", [])}})
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _local_only(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        ok = host in ("127.0.0.1", "localhost") and (not origin or urlparse(origin).hostname in ("127.0.0.1", "localhost"))
        if not ok:
            self._json({"error": "forbidden"}, 403)
        return ok

    def _json(self, data, code=200):
        b = json.dumps(data, ensure_ascii=False).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass  # вкладку закрыли или перезагрузили

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self._local_only():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            b = (ROOT / "web" / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        elif u.path == "/api/env":
            self._json(env_info())
        elif u.path == "/api/run":
            run = RUNS.get(q.get("id"))
            if not run:
                return self._json({"error": "not found"}, 404)
            since = int(q.get("since", 0))
            self._json({"status": run["status"], "events": run["events"][since:], "next": len(run["events"])})
        elif u.path == "/api/results":
            self._json(list_results())
        elif u.path == "/api/local/scan":
            host = (q.get("host") or "127.0.0.1").strip()
            if not local.is_local(f"http://{host}/"):
                return self._json({"error": "Можно сканировать только этот компьютер или локальную сеть"}, 400)
            self._json(local.scan(host, [p for p in (q.get("ports") or "").split(",") if p.strip()]))
        elif u.path == "/api/public":
            import public
            self._json({"benches": public.BENCHES,
                        "cached": sorted(f.stem for f in public.CACHE.glob("*.json")) if public.CACHE.exists() else []})
        elif u.path == "/api/batch/last":
            self._json(batch.last_batch(RESULTS) or {})
        elif u.path == "/api/catalog":
            self._json(bench.catalog(int(q.get("ctx", 80000))))
        elif u.path == "/api/refs":
            self._json([{k: r.get(k) for k in ("name", "family", "model", "date", "builtin", "deltas", "summary", "tok_per_sec")}
                        for r in verify.load_refs(RESULTS)])
        elif u.path == "/api/result":
            f = RESULTS / Path(q.get("file", "")).name
            self._json(json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {"error": "not found"})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._local_only():
            return
        u, body = urlparse(self.path), self._body()
        if u.path == "/api/check":
            self._json(check_key(body))
        elif u.path == "/api/batch":
            items, errors = batch.parse_lines(body.get("text"), body.get("base_url") or "")
            if not items:
                return self._json({"error": "Нет ни одного ключа. " + "; ".join(errors)}, 400)
            self._json({"id": start_run(body, "batch"), "count": len(items)})
        elif u.path == "/api/run":
            self._json({"id": start_run(body)})
        elif u.path == "/api/cancel":
            run = RUNS.get(body.get("id"))
            if run:
                run["cancel"].set()
            self._json({"ok": bool(run)})
        elif u.path == "/api/refs/add":
            f = RESULTS / Path(body.get("file", "")).name
            try:
                run = json.loads(f.read_text(encoding="utf-8"))
                verify.save_ref(RESULTS, run, (body.get("name") or run.get("model") or "эталон").strip())
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
        elif u.path == "/api/refs/delete":
            verify.delete_ref(RESULTS, body.get("name", ""))
            self._json({"ok": True})
        elif u.path == "/api/delete":
            f = RESULTS / Path(body.get("file", "")).name
            if f.is_file():
                f.unlink()
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    RESULTS.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}"
    print(f"LLM Bench: {url}  (Ctrl+C — выход)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
