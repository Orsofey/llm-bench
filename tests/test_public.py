import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import public_bench as pb


class PublicBenchmarkTests(unittest.TestCase):
    def test_open_datasets_and_counts(self):
        for key in ("mmlu_pro", "arc_agi_2", "livecodebench"):
            records = pb._read_json(pb.DATA_ROOT / pb.PUBLIC[key]["file"])
            self.assertEqual(len(records), pb.PUBLIC[key]["count"])
        mmlu = pb._read_json(pb.DATA_ROOT / "mmlu_pro.json")
        self.assertEqual(len({r["category"] for r in mmlu}), 14)
        self.assertTrue(all(len(r["choices"]) == 10 for r in mmlu))
        arc = pb._read_json(pb.DATA_ROOT / "arc_agi_2.json")
        self.assertTrue(all(r["train"] and isinstance(r["answer"], list) for r in arc))
        lcb = pb._read_json(pb.DATA_ROOT / "livecodebench.json")
        self.assertTrue(all(len(r["tests"]) == 6 and r["content"] for r in lcb))

    def test_open_tasks_build(self):
        with tempfile.TemporaryDirectory() as d:
            tasks = pb.tasks(["mmlu_pro", "arc_agi_2", "livecodebench"], d)
            self.assertEqual(len(tasks), 58)
            self.assertTrue(all(t["public"] for t in tasks))

    def test_choice_and_hle_checks(self):
        self.assertEqual(pb._choice_checker("J")("The answer is J."), (1.0, "ответ J"))
        self.assertEqual(pb._choice_checker("A", "ABCD")("Ответ: B")[0], 0.0)
        self.assertEqual(pb._hle_checker("1 250", "exactMatch")("Final answer: 1250")[0], 1.0)
        self.assertEqual(pb._hle_checker("C", "multipleChoice")("C")[0], 1.0)

    def test_arc_check(self):
        grid = [[0, 1], [2, 3]]
        self.assertEqual(pb._arc_checker(grid)(str(grid))[0], 1.0)
        self.assertEqual(pb._arc_checker(grid)("[[0, 1], [2, 2]]")[0], 0.0)

    def test_stdin_code_checker(self):
        record = {"tests": [{"input": "2 3\n", "output": "5\n"}, {"input": "10 -4\n", "output": "6\n"}]}
        code = "import sys\na,b=map(int,sys.stdin.read().split())\nprint(a+b)"
        score, note = pb._code_checker(record)(code)
        self.assertEqual(score, 1.0)
        self.assertIn("2/2", note)

    def test_embedded_stdin(self):
        test = {"input": "hello\n", "output": "HELLO\n"}
        with patch.object(pb.sys, "frozen", True, create=True):
            stdout, error = pb._run_program("import sys\nprint(sys.stdin.read().strip().upper())", test)
        self.assertIsNone(error)
        self.assertEqual(stdout.strip(), "HELLO")

    def test_status_and_estimate(self):
        with tempfile.TemporaryDirectory() as d:
            data = pb.status(d)
            self.assertEqual(data["total"], 118)
            self.assertGreaterEqual(data["cached"], 3)
            self.assertGreater(pb.estimate_tokens(["mmlu_pro"], d), 0)

    def test_gated_download_and_cache_mock(self):
        with tempfile.TemporaryDirectory() as d:
            def fake_rows(key, token, offset=0, length=100, where=None):
                self.assertEqual(token, "hf_test")
                if key == "gpqa":
                    return {"rows": [{"row_idx": i, "row": {"Question": f"Q{i}", "Correct Answer": "correct",
                        "Incorrect Answer 1": "a", "Incorrect Answer 2": "b", "Incorrect Answer 3": "c",
                        "Domain": "Physics"}} for i in range(40)]}
                return {"rows": [{"row_idx": i, "row": {"id": str(i), "question": f"H{i}", "answer": "42",
                    "answer_type": "exactMatch", "category": "Math", "image": None}} for i in range(35)]}
            with patch.object(pb, "_hf_rows", fake_rows):
                pb.download(["gpqa", "hle"], d, "hf_test")
            for key in ("gpqa", "hle"):
                records = pb._read_json(Path(d) / pb.PUBLIC[key]["file"])
                self.assertEqual(len(records), 30)
            gpqa = pb._read_json(Path(d) / "gpqa.json")
            self.assertTrue(all(len(r["choices"]) == 4 and r["answer"] in "ABCD" for r in gpqa))
            self.assertTrue(all(r["category"] == "Physics" for r in gpqa))
            hle = pb._read_json(Path(d) / "hle.json")
            self.assertTrue(all(r["answer"] == "42" for r in hle))
            self.assertTrue(pb.status(d)["benchmarks"][1]["cached"])
            # Повторный запуск использует кеш, токен больше не нужен.
            tasks = pb.tasks(["gpqa", "hle"], d)
            self.assertEqual(len(tasks), 60)

    def test_gated_requires_token(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(pb.PublicDataError, "Read-токен"):
                pb.download(["gpqa"], d, None)


if __name__ == "__main__":
    unittest.main()
