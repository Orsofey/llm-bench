import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import app
import bench
import verify


class CoreTests(unittest.TestCase):
    def test_extract_json(self):
        self.assertEqual(bench.extract_json('```json\n{"keep":[3,6]}\n```'), {"keep": [3, 6]})
        self.assertEqual(bench.extract_json('prefix [{"tool":"open_app"}] suffix'), [{"tool": "open_app"}])

    def test_python_subprocess(self):
        score, note = bench.run_py("def twice(x):\n    return x * 2\n", ["twice(4)==8", "twice('a')=='aa'"])
        self.assertEqual(score, 1.0)
        self.assertIn("2/2", note)

    def test_python_android_embedded(self):
        with patch.dict(os.environ, {"LLM_BENCH_PLATFORM": "android"}):
            score, note = bench.run_py("def twice(x):\n    return x * 2\n", ["twice(4)==8", "twice('a')=='aa'"])
            self.assertEqual(score, 1.0)
            self.assertIn("2/2", note)
            score, note = bench.run_py("while True:\n    pass\n", ["True"], timeout=0.05)
            self.assertEqual(score, 0.0)
            self.assertEqual(note, "таймаут")

    def test_frozen_exe_uses_embedded_python(self):
        with patch.object(bench.sys, "frozen", True, create=True):
            score, note = bench.run_py("def add(a, b):\n    return a + b\n", ["add(2, 3)==5"])
        self.assertEqual(score, 1.0)
        self.assertIn("1/1", note)

    def test_fingerprint_similarity(self):
        ref = {k: 50 for k in verify.PROBES}
        similarity, match = verify.fp_similarity(ref, ref)
        self.assertEqual(similarity, 1.0)
        self.assertTrue(match)

    def test_local_server(self):
        with tempfile.TemporaryDirectory() as d:
            old_results = app.RESULTS
            app.RESULTS = Path(d) / "results"
            srv = app.create_server(0)
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{srv.server_address[1]}"
                with urllib.request.urlopen(base + "/api/env", timeout=5) as response:
                    env = json.load(response)
                with urllib.request.urlopen(base + "/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                with urllib.request.urlopen(base + "/api/public/status", timeout=5) as response:
                    public = json.load(response)
                self.assertEqual(env["version"], "1.0.0")
                self.assertIn("AI model intelligence", html)
                self.assertIn("Orsofey", html)
                self.assertEqual(public["total"], 118)
                self.assertEqual(len(public["benchmarks"]), 5)
            finally:
                srv.shutdown()
                srv.server_close()
                app.RESULTS = old_results


if __name__ == "__main__":
    unittest.main()
