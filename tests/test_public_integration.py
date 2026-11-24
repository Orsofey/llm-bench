import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bench
import public_bench as pb


class PublicIntegrationTests(unittest.TestCase):
    def test_full_open_public_run_with_mock_llm(self):
        mmlu = pb._read_json(pb.DATA_ROOT / "mmlu_pro.json")
        arc = pb._read_json(pb.DATA_ROOT / "arc_agi_2.json")
        lcb = pb._read_json(pb.DATA_ROOT / "livecodebench.json")

        class Mock(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, data):
                body = json.dumps(data, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/v1/models":
                    self.reply({"data": [{"id": "mock-public"}]})
                else:
                    self.send_error(404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                request = json.loads(self.rfile.read(n))
                prompt = request["messages"][-1]["content"]
                answer = "ok"
                hit = next((r for r in mmlu if r["question"] in prompt), None)
                if hit:
                    answer = hit["answer"]
                else:
                    hit = next((r for r in arc if json.dumps(r["test_input"]) in prompt), None)
                    if hit:
                        answer = json.dumps(hit["answer"])
                    else:
                        hit = next((r for r in lcb if r["content"] in prompt), None)
                        if hit:
                            cases = {t["input"]: t["output"] for t in hit["tests"]}
                            answer = "```python\nimport sys\ncases=" + repr(cases) + "\nsys.stdout.write(cases.get(sys.stdin.read(), ''))\n```"
                self.reply({"id": "chatcmpl-mock", "object": "chat.completion", "model": "mock-public",
                            "choices": [{"message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 10}})

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                events = []
                result = bench.run_benchmark({
                    "provider": "openai", "base_url": f"http://127.0.0.1:{srv.server_address[1]}/v1",
                    "key": "test", "model": "mock-public", "public": ["mmlu_pro", "arc_agi_2", "livecodebench"],
                    "out": str(Path(d) / "results"), "verify": False, "skip_health": True,
                    "workers": 1, "max_tokens": 1000, "tag": "integration",
                }, events.append)
                self.assertIsNotNone(result, events[-3:])
                report = json.loads(Path(result).read_text(encoding="utf-8"))
                self.assertEqual(len(report["tasks"]), 58)
                self.assertEqual(report["summary"]["mmlu_pro"], 100.0)
                self.assertEqual(report["summary"]["arc_agi_2"], 100.0)
                self.assertEqual(report["summary"]["livecodebench"], 100.0)
                self.assertEqual(report["summary"]["TOTAL"], 100.0)
                self.assertTrue(all(t["score"] == 1.0 for t in report["tasks"]))
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
