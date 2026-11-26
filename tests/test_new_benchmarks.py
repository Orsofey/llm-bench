import unittest
from unittest.mock import patch

import arc3_bench
import public_bench as pb
import rli_bench


class NewBenchmarkTests(unittest.TestCase):
    def test_new_public_status(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            status = pb.status(d)
            self.assertEqual(status["total"], 123)
            self.assertEqual(len(status["benchmarks"]), 7)
            arc = next(b for b in status["benchmarks"] if b["id"] == "arc_agi_3")
            rli = next(b for b in status["benchmarks"] if b["id"] == "rli")
            self.assertTrue(arc["requires_arc"])
            self.assertTrue(arc["cached"])
            self.assertTrue(rli["cached"])

    def test_arc_action_parser(self):
        self.assertEqual(arc3_bench._parse_action('{"action":"ACTION6","data":{"x":4,"y":5}}'), ("ACTION6", {"x": 4, "y": 5}))
        self.assertEqual(arc3_bench._parse_action("ACTION2"), ("ACTION2", {}))

    def test_arc_interactive_driver(self):
        responses = {
            ("GET", "/api/games/anonkey"): {"api_key": "anon"},
            ("GET", "/api/games/ls20"): {"game_id": "ls20", "title": "LS20"},
            ("POST", "/api/scorecard/open"): {"card_id": "card"},
            ("POST", "/api/cmd/RESET"): {"game_id": "ls20", "guid": "g", "state": "NOT_FINISHED", "frame": [], "levels_completed": 0, "win_levels": 2, "available_actions": [1]},
            ("POST", "/api/cmd/ACTION1"): {"game_id": "ls20", "guid": "g", "state": "WIN", "frame": [], "levels_completed": 2, "win_levels": 2, "available_actions": [1]},
            ("POST", "/api/scorecard/close"): {"score": 90.0, "environments": [{"id": "ls20", "runs": [{"score": 90.0, "levels_completed": 2, "level_count": 2}]}]},
        }

        def fake_request(method, path, api_key, payload=None):
            return responses[(method, path)]

        class Client:
            model = "mock"

            def chat(self, prompt, max_tokens=None):
                return {"text": "ACTION1"}

        with patch.object(arc3_bench, "_request", fake_request):
            score, note = arc3_bench.run_task(Client(), "ls20", lambda ev: None)
        self.assertEqual(score, 1.0)
        self.assertIn("90.0", note)

    def test_rli_static_and_judge(self):
        record = {"id": "rli_public_003", "title": "Game", "brief": "Make a game", "data": {}}
        html = "<!doctype html><html><body><div id='score'>Score</div><canvas></canvas><script>merge(); gravity(); next(); gameOver(); restart(); touch(); audio();</script><style>@media</style></body></html>"
        static, _ = rli_bench._static(record, html)
        self.assertEqual(static, 1.0)

        class Client:
            def __init__(self):
                self.calls = 0

            def chat(self, prompt, max_tokens=None):
                self.calls += 1
                return {"text": html if self.calls == 1 else '{"score":90,"reason":"ok"}'}

        score, note = rli_bench.run_task(Client(), record, lambda ev: None)
        self.assertAlmostEqual(score, 0.93)
        self.assertIn("LLM-judge 90/100", note)

    def test_driver_usage(self):
        import bench
        import tempfile
        html = "<!doctype html><html><body><div id='score'>Score</div><canvas></canvas><script>merge(); gravity(); next(); gameOver(); restart(); touch(); audio();</script><style>@media</style></body></html>"

        class Client:
            model = "mock"

            def __init__(self):
                self.calls = 0
                self.usage = {"requests": 0, "in": 0, "out": 0, "sec": 0.0, "errors": 0}

            def chat(self, prompt, max_tokens=None):
                self.calls += 1
                self.usage["requests"] += 1
                self.usage["in"] += 100
                self.usage["out"] += 50
                self.usage["sec"] += 1.0
                return {"text": html if self.calls == 1 else '{"score":90,"reason":"ok"}', "in": 100, "out": 50, "sec": 1.0, "served_model": "mock"}

        with tempfile.TemporaryDirectory() as d:
            task = pb.tasks(["rli"], d)[0]
            result = bench.run_task(Client(), task, 1)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(result["in"], 200)
        self.assertEqual(result["out"], 100)
        self.assertAlmostEqual(result["score"], 0.93, places=2)

    def test_new_tasks_build(self):
        import tempfile
        games = [{"game_id": "a", "title": "A"}, {"game_id": "b", "title": "B"}, {"game_id": "c", "title": "C"}]
        with tempfile.TemporaryDirectory() as d, patch("arc3_bench.list_games", return_value=games):
            tasks = pb.tasks(["arc_agi_3", "rli"], d)
            self.assertEqual(len(tasks), 5)
            self.assertTrue(all(t["driver"] for t in tasks))


if __name__ == "__main__":
    unittest.main()
