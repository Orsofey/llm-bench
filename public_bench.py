"""Реальные мини-наборы публичных бенчмарков и их локальная проверка.

Открытые мини-наборы лежат в public_data/. GPQA и HLE скачиваются напрямую
с Hugging Face по токену пользователя и сохраняются локально без токена.
"""
import contextlib
import hashlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import bench

DATA_ROOT = Path(__file__).resolve().parent / "public_data"
HF_HOST = "https://datasets-server.huggingface.co"
PUBLIC = {
    "mmlu_pro": {
        "name": "MMLU-Pro", "count": 40, "file": "mmlu_pro.json", "requires_hf": False,
        "description": "Знания в 14 дисциплинах, 10 вариантов ответа", "short": "MMLU",
        "out_tokens": 50, "dataset": "TIGER-Lab/MMLU-Pro", "config": "default", "split": "test",
    },
    "gpqa": {
        "name": "GPQA Diamond", "count": 30, "file": "gpqa.json", "requires_hf": True,
        "description": "Вопросы уровня аспирантуры: физика, химия, биология", "short": "GPQA",
        "out_tokens": 1800, "dataset": "Idavidrein/gpqa", "config": "gpqa_diamond", "split": "train",
    },
    "hle": {
        "name": "Humanity's Last Exam", "count": 30, "file": "hle.json", "requires_hf": True,
        "description": "Сложные экспертные вопросы, только текстовые", "short": "HLE",
        "out_tokens": 3000, "dataset": "cais/hle", "config": "default", "split": "test",
    },
    "arc_agi_2": {
        "name": "ARC-AGI-2", "count": 6, "file": "arc_agi_2.json", "requires_hf": False,
        "description": "Абстрактные головоломки на сетках: найти закономерность", "short": "ARC",
        "out_tokens": 2000, "dataset": "arcprize/ARC-AGI-2", "config": "evaluation", "split": "test",
    },
    "livecodebench": {
        "name": "LiveCodeBench", "count": 12, "file": "livecodebench.json", "requires_hf": False,
        "description": "Олимпиадные задачи, код запускается на тестах", "short": "LCB",
        "out_tokens": 4000, "dataset": "livecodebench/code_generation", "config": "default", "split": "test",
    },
}
ORDER = list(PUBLIC)
_STDIO_LOCK = threading.Lock()


class PublicDataError(RuntimeError):
    pass


def _read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("ожидался JSON-массив")
        return data
    except Exception as e:
        raise PublicDataError(f"Повреждён файл данных {Path(path).name}: {e}")


def _cache_path(cache_dir, key):
    return Path(cache_dir) / PUBLIC[key]["file"]


def status(cache_dir):
    out = {"benchmarks": [], "total": 0, "cached": 0}
    for key, spec in PUBLIC.items():
        packaged = DATA_ROOT / spec["file"]
        cached = _cache_path(cache_dir, key)
        path = cached if spec["requires_hf"] and cached.is_file() else packaged
        available = path.is_file()
        count = 0
        if available:
            try:
                count = len(_read_json(path))
            except PublicDataError:
                available = False
        out["benchmarks"].append({"id": key, "name": spec["name"], "description": spec["description"],
                                  "count": spec["count"], "actual_count": count, "requires_hf": spec["requires_hf"],
                                  "cached": available, "source": "кеш" if path == cached and available else "встроено"})
        out["total"] += spec["count"]
        out["cached"] += int(available)
    return out


def estimate_tokens(keys, cache_dir):
    """Грубая верхняя оценка input + резерв ответа; фактический расход виден после прогона."""
    total = 0
    for key in keys:
        spec = PUBLIC[key]
        path = _cache_path(cache_dir, key) if spec["requires_hf"] else DATA_ROOT / spec["file"]
        if spec["requires_hf"] and not path.is_file():
            path = DATA_ROOT / spec["file"]
        input_tokens = 0
        if path.is_file():
            try:
                for r in _read_json(path):
                    input_tokens += max(1, len(_prompt(key, r)) // 4)
            except PublicDataError:
                pass
        if not input_tokens:
            input_tokens = spec["count"] * 700
        total += input_tokens + spec["count"] * spec["out_tokens"]
    return round(total + (2500 if keys else 0))


def _stable_sample(records, count, salt):
    def digest(r):
        identity = str(r.get("id") or r.get("Question") or r.get("question") or r)
        return hashlib.sha256((salt + identity).encode("utf-8", errors="replace")).hexdigest()
    return sorted(records, key=digest)[:count]


def _atomic_write(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _hf_rows(key, token, offset=0, length=100, where=None):
    spec = PUBLIC[key]
    params = {"dataset": spec["dataset"], "config": spec["config"], "split": spec["split"],
              "offset": offset, "length": length}
    if where:
        params["where"] = where
    url = HF_HOST + ("/filter?" if where else "/rows?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "LLM-Bench/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        if e.code in (401, 403):
            raise PublicDataError(
                f"Hugging Face не открыл доступ к {spec['name']} ({e.code}). Проверьте Read-токен и примите условия: "
                f"https://huggingface.co/datasets/{spec['dataset']}"
            )
        if e.code == 404:
            raise PublicDataError(f"Набор {spec['dataset']} или его split не найден. {body}")
        raise PublicDataError(f"Hugging Face: HTTP {e.code}. {body}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise PublicDataError(f"Не удалось связаться с Hugging Face: {e}")


def _download_gpqa(cache_dir, token):
    rows = _hf_rows("gpqa", token, length=100).get("rows", [])
    records = []
    for item in rows:
        r = item.get("row", {})
        question = str(r.get("Question") or "").strip()
        correct = str(r.get("Correct Answer") or "").strip()
        wrong = [str(r.get(f"Incorrect Answer {i}") or "").strip() for i in range(1, 4)]
        if not question or not correct or not all(wrong):
            continue
        records.append({"id": f"gpqa_{item.get('row_idx', len(records))}", "question": question,
                        "correct": correct, "wrong": wrong,
                        "category": r.get("Domain") or r.get("High-level domain") or "science"})
    if len(records) < PUBLIC["gpqa"]["count"]:
        raise PublicDataError(f"GPQA: получено только {len(records)} пригодных вопросов")
    selected = []
    for r in _stable_sample(records, PUBLIC["gpqa"]["count"], "llm-bench-gpqa-v1"):
        choices = [r["correct"], *r["wrong"]]
        random.Random(int(hashlib.sha256(r["id"].encode()).hexdigest()[:12], 16)).shuffle(choices)
        selected.append({"id": r["id"], "question": r["question"], "choices": choices,
                         "answer": "ABCD"[choices.index(r["correct"])], "category": r["category"]})
    _atomic_write(_cache_path(cache_dir, "gpqa"), selected)


def _download_hle(cache_dir, token):
    rows = None
    try:
        rows = _hf_rows("hle", token, length=100, where='"image" IS NULL').get("rows", [])
    except PublicDataError:
        rows = None
    if rows is None:
        rows = []
        for offset in range(0, 1000, 100):
            page = _hf_rows("hle", token, offset=offset, length=100)
            rows.extend(page.get("rows", []))
            if offset + 100 >= int(page.get("num_rows_total") or 0):
                break
    records = []
    for item in rows:
        r = item.get("row", {})
        if r.get("image") or r.get("image_preview"):
            continue
        question = str(r.get("question") or "").strip()
        answer = str(r.get("answer") or "").strip()
        if not question or not answer:
            continue
        identity = str(r.get("id") or hashlib.sha256(question.encode()).hexdigest()[:16])
        records.append({"id": f"hle_{identity}", "question": question, "answer": answer,
                        "answer_type": r.get("answer_type") or "exactMatch",
                        "category": r.get("category") or r.get("subject") or "text"})
    if len(records) < PUBLIC["hle"]["count"]:
        raise PublicDataError("HLE: недостаточно текстовых вопросов в ответе Hugging Face")
    selected = _stable_sample(records, PUBLIC["hle"]["count"], "llm-bench-hle-text-v1")
    _atomic_write(_cache_path(cache_dir, "hle"), selected)


def download(keys, cache_dir, hf_token):
    """Скачивает только выбранные gated-наборы; открытые уже встроены."""
    for key in keys:
        if key not in PUBLIC:
            raise PublicDataError(f"Неизвестный бенчмарк: {key}")
        spec = PUBLIC[key]
        if not spec["requires_hf"] or _cache_path(cache_dir, key).is_file():
            continue
        if not hf_token:
            raise PublicDataError(
                f"Для {spec['name']} нужен Hugging Face Read-токен. Зарегистрируйтесь, примите условия "
                f"https://huggingface.co/datasets/{spec['dataset']} и вставьте токен."
            )
        if key == "gpqa":
            _download_gpqa(cache_dir, hf_token)
        elif key == "hle":
            _download_hle(cache_dir, hf_token)
    return status(cache_dir)


def _records(key, cache_dir, hf_token):
    spec = PUBLIC[key]
    path = _cache_path(cache_dir, key) if spec["requires_hf"] else DATA_ROOT / spec["file"]
    if spec["requires_hf"] and not path.is_file():
        download([key], cache_dir, hf_token)
    records = _read_json(path)
    if len(records) != spec["count"]:
        raise PublicDataError(f"{spec['name']}: ожидалось {spec['count']} заданий, найдено {len(records)}. "
                              "Удалите повреждённый кеш и скачайте набор снова.")
    return records


def _choice(text, letters):
    matches = re.findall(r"(?<![A-Za-z])([" + re.escape(letters) + r"])(?![A-Za-z])", (text or "").upper())
    return matches[-1] if matches else None


def _choice_checker(answer, letters="ABCDEFGHIJ"):
    def check(text):
        got = _choice(text, letters)
        return float(got == answer), (f"ответ {got}" if got else "буква ответа не найдена")
    return check


def _norm(text):
    text = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    text = re.sub(r"\\(?:text|mathrm|operatorname)\s*\{([^{}]*)\}", r"\1", text)
    text = text.replace("$", "").replace("\\", "").replace("−", "-")
    text = re.sub(r"(?<=\d)[\s,](?=\d)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n\"'`.;:!?{ }()[]")


def _hle_checker(expected, answer_type):
    def check(text):
        expected_n = _norm(expected)
        candidates = [text]
        lines = [line for line in str(text or "").strip().splitlines() if line.strip()]
        if lines:
            candidates.append(lines[-1])
        candidates.append(re.split(r"(?:final answer|ответ)\s*[:：]", str(text or ""), flags=re.I)[-1])
        if answer_type == "multipleChoice" and len(expected_n) == 1 and expected_n.isalpha():
            got = _choice(text, "ABCDEFGHIJ")
            return float(got == expected_n.upper()), "ответ не совпал" if got else "буква ответа не найдена"
        ok = any(_norm(c) == expected_n for c in candidates)
        if not ok:
            try:
                nums = [float(_norm(c)) for c in candidates]
                ok = any(v == float(expected_n) for v in nums)
            except (ValueError, TypeError):
                pass
        return float(ok), "ответ совпал" if ok else "ответ не совпал (строгая проверка)"
    return check


def _arc_checker(expected):
    def check(text):
        got = bench.extract_json(text)
        if isinstance(got, dict):
            got = got.get("output") or got.get("grid") or got.get("answer")
        return float(got == expected), "сетка совпала" if got == expected else "сетка не совпала"
    return check


def _output_norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip())


def _run_embedded_program(code, test, timeout):
    box = {}

    class BenchTimeout(BaseException):
        pass

    def worker():
        deadline = time.monotonic() + timeout

        def trace(frame, event, arg):
            if time.monotonic() > deadline:
                raise BenchTimeout()
            return trace

        old_stdin = sys.stdin
        try:
            sys.settrace(trace)
            sys.stdin = io.StringIO(test["input"])
            with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                exec(compile(code, "<livecodebench>", "exec"), {"__name__": "__main__"})
            box["stdout"] = stdout.getvalue()
            box["stderr"] = stderr.getvalue()
        except BenchTimeout:
            box["error"] = "таймаут"
        except Exception as e:
            box["error"] = str(e)[:160]
        finally:
            sys.settrace(None)
            sys.stdin = old_stdin

    thread = threading.Thread(target=worker, name="lcb-program", daemon=True)
    thread.start()
    thread.join(timeout + 0.5)
    if thread.is_alive():
        return None, "таймаут"
    return box.get("stdout"), box.get("error")


def _run_program(code, test, timeout=10):
    if os.environ.get("LLM_BENCH_PLATFORM") == "android" or getattr(sys, "frozen", False):
        with _STDIO_LOCK:
            return _run_embedded_program(code, test, timeout)
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "solution.py"
        script.write_text(code, encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, "-I", str(script)], input=test["input"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=d)
        except subprocess.TimeoutExpired:
            return None, "таймаут"
        return r.stdout, (r.stderr.strip().splitlines() or [None])[-1] if r.returncode else None


def _code_checker(record):
    def check(text):
        code = bench.extract_code(text).strip()
        if not code:
            return 0.0, "код не найден"
        tests = record["tests"]
        passed = 0
        last = ""
        for test in tests:
            stdout, error = _run_program(code, test)
            if error:
                last = error
                break
            if _output_norm(stdout) == _output_norm(test["output"]):
                passed += 1
            else:
                last = "неверный вывод"
                break
        note = f"тесты {passed}/{len(tests)} (публичные + скрытые)"
        return passed / len(tests), note + (f" · {last}" if last and passed < len(tests) else "")
    return check


def _prompt(key, r):
    if key in ("mmlu_pro", "gpqa"):
        letters = "ABCDEFGHIJ"[:len(r["choices"])]
        options = "\n".join(f"{letters[i]}. {value}" for i, value in enumerate(r["choices"]))
        return (f"Answer the following question. Reply with ONLY one letter from {letters[0]} to {letters[-1]}, "
                f"without explanation.\n\nQuestion:\n{r['question']}\n\nOptions:\n{options}")
    if key == "hle":
        return ("Answer with ONLY the final answer, without explanation or introductory text. "
                "Preserve exact mathematical notation when needed.\n\n" + r["question"])
    if key == "arc_agi_2":
        examples = "\n\n".join(f"Example {i+1}\nInput:\n{json.dumps(p['input'])}\nOutput:\n{json.dumps(p['output'])}"
                               for i, p in enumerate(r["train"]))
        return ("Infer the transformation from the examples. Return ONLY the output grid for the test input "
                "as a JSON array of arrays of integers 0..9. No explanation, no code block.\n\n"
                + examples + "\n\nTest input:\n" + json.dumps(r["test_input"]))
    if key == "livecodebench":
        starter = ("\nStarter code (optional):\n```python\n" + r["starter_code"] + "\n```") if r.get("starter_code") else ""
        return ("Solve this competitive programming problem in Python 3. Read from standard input and write to standard output. "
                "Return ONLY one complete program in one ```python code block, without explanations, tests or example usage.\n\n"
                + r["content"] + starter)
    raise KeyError(key)


def _task(key, r, index):
    if key in ("mmlu_pro", "gpqa"):
        letters = "ABCDEFGHIJ"[:len(r["choices"])]
        check = _choice_checker(r["answer"], letters)
        detail = f"{r.get('category', 'science')} · {len(r['choices'])} вариантов"
    elif key == "hle":
        check = _hle_checker(r["answer"], r.get("answer_type") or "exactMatch")
        detail = f"{r.get('category', 'text')} · текстовый ответ"
    elif key == "arc_agi_2":
        check = _arc_checker(r["answer"])
        detail = "точное совпадение сетки"
    else:
        check = _code_checker(r)
        detail = f"{r.get('difficulty', 'task')} · {len(r['tests'])} тестов"
    return {"id": f"{key}_{index+1:03d}", "cat": key, "prompt": _prompt(key, r),
            "desc": f"{PUBLIC[key]['short']} · {detail}", "check": check, "public": True}


def tasks(keys, cache_dir, hf_token=None, emit=lambda ev: None):
    out = []
    for key in keys:
        if key not in PUBLIC:
            raise PublicDataError(f"Неизвестный публичный бенчмарк: {key}")
        emit({"type": "activity", "text": f"Подготавливаю {PUBLIC[key]['name']} ({PUBLIC[key]['count']} заданий)"})
        records = _records(key, cache_dir, hf_token)
        out.extend(_task(key, r, i) for i, r in enumerate(records))
    return out
