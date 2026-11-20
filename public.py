"""
Мини-версии публичных бенчмарков, которыми проверяют новые модели при выходе:
MMLU-Pro, GPQA Diamond, Humanity's Last Exam, ARC-AGI-2, LiveCodeBench.

Наборы скачиваются на этом компьютере (в репозиторий не кладутся — авторы GPQA и HLE
просят не публиковать вопросы) и кэшируются в data_cache/. Выборка фиксирована (seed),
поэтому разные ключи получают одни и те же вопросы и их можно честно сравнивать.

Баллы НЕ равны официальным: разработчики запускают модели с инструментами и своими промптами.
Смысл — сравнить ключ с эталоном официальной модели на одинаковых вопросах.
"""
import base64, io, json, pickle, random, re, subprocess, sys, tempfile, time, urllib.parse, urllib.request, zlib
from pathlib import Path

CACHE = Path(__file__).parent / "data_cache"
SEED = 2026
ROWS_API = "https://datasets-server.huggingface.co"

BENCHES = {
    "mmlu_pro": {"name": "MMLU-Pro", "default_n": 40, "gated": False, "out_tokens": 700,
                 "about": "Знания в 14 дисциплинах, 10 вариантов ответа", "site": "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro"},
    "gpqa": {"name": "GPQA Diamond", "default_n": 30, "gated": True, "out_tokens": 1200,
             "about": "Вопросы уровня аспирантуры: физика, химия, биология", "site": "https://huggingface.co/datasets/Idavidrein/gpqa"},
    "hle": {"name": "Humanity's Last Exam", "default_n": 30, "gated": True, "out_tokens": 2000,
            "about": "Самые сложные экспертные вопросы (только текстовые)", "site": "https://huggingface.co/datasets/cais/hle"},
    "arc_agi_2": {"name": "ARC-AGI-2", "default_n": 6, "gated": False, "out_tokens": 2500,
                  "about": "Абстрактные головоломки на сетках: найти закономерность", "site": "https://arcprize.org"},
    "livecodebench": {"name": "LiveCodeBench", "default_n": 12, "gated": False, "out_tokens": 1800,
                      "about": "Олимпиадные задачи, код запускается на тестах", "site": "https://livecodebench.github.io"},
}


class _SafeUnpickler(pickle.Unpickler):
    """Тесты LiveCodeBench упакованы в pickle. Разрешаем только простые типы — никакого кода."""
    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"запрещено в данных: {module}.{name}")


def _get(url, token=None, timeout=60, tries=4):
    import local
    headers = {"User-Agent": "llm-bench"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for i in range(tries):
        try:
            with local.urlopen(urllib.request.Request(url, headers=headers), timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError("нет доступа: набор закрытый — нужен токен Hugging Face и принятые условия набора") from None
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(4 * (i + 1))
                continue
            raise RuntimeError(f"Hugging Face ответил {e.code}") from None


def _rows(dataset, config, split, offset, length, token=None, where=None):
    q = {"dataset": dataset, "config": config, "split": split, "offset": offset, "length": length}
    if where:
        q["where"] = where
    url = f"{ROWS_API}/{'filter' if where else 'rows'}?" + urllib.parse.urlencode(q)
    d = json.loads(_get(url, token))
    return [r["row"] for r in d.get("rows", [])], d.get("num_rows_total", 0)


def _cached(name, n, loader):
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{name}_{n}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    items = loader()
    f.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return items


# ---------------- загрузчики ----------------
def load_mmlu_pro(n, token=None):
    def load():
        rnd = random.Random(SEED)
        _, total = _rows("TIGER-Lab/MMLU-Pro", "default", "test", 0, 1)
        pool = []
        for off in sorted(rnd.sample(range(0, max(total - 100, 1)), 4)):
            pool += _rows("TIGER-Lab/MMLU-Pro", "default", "test", off, 100)[0]
        pick = random.Random(SEED).sample(pool, min(n, len(pool)))
        return [{"id": f"mmlu_pro_{r['question_id']}", "question": r["question"], "options": r["options"],
                 "answer": r["answer"], "category": r.get("category")} for r in pick]
    return _cached("mmlu_pro", n, load)


def load_gpqa(n, token=None):
    def load():
        rows, total = _rows("Idavidrein/gpqa", "gpqa_diamond", "train", 0, 100, token)
        if total > 100:
            rows += _rows("Idavidrein/gpqa", "gpqa_diamond", "train", 100, 100, token)[0]
        rnd = random.Random(SEED)
        out = []
        for i, r in enumerate(rnd.sample(rows, min(n, len(rows)))):
            correct = r["Correct Answer"].strip()
            opts = [correct] + [r[f"Incorrect Answer {k}"].strip() for k in (1, 2, 3)]
            random.Random(SEED + i).shuffle(opts)
            out.append({"id": f"gpqa_{r.get('Record ID') or i}", "question": r["Question"].strip(), "options": opts,
                        "answer": "ABCD"[opts.index(correct)], "category": r.get("High-level domain")})
        return out
    return _cached("gpqa", n, load)


def load_hle(n, token=None):
    def load():
        rows = []
        try:  # только текстовые вопросы
            for off in (0, 100, 200, 300):
                rows += _rows("cais/hle", "default", "test", off, 100, token, where="\"image\"=''")[0]
        except RuntimeError:
            raise
        rows = [r for r in rows if not r.get("image")]
        # без судьи-модели честно проверяются: выбор варианта и короткий точный ответ
        rows = [r for r in rows if r.get("answer_type") == "multipleChoice" or len(str(r.get("answer", ""))) <= 40]
        pick = random.Random(SEED).sample(rows, min(n, len(rows)))
        return [{"id": f"hle_{r['id']}", "question": r["question"], "answer": str(r["answer"]).strip(),
                 "answer_type": r.get("answer_type"), "category": r.get("category")} for r in pick]
    return _cached("hle", n, load)


def load_arc(n, token=None):
    def load():
        listing = json.loads(_get("https://api.github.com/repos/arcprize/ARC-AGI-2/contents/data/evaluation"))
        names = sorted(f["name"] for f in listing if f["name"].endswith(".json"))
        tasks = []
        for name in random.Random(SEED).sample(names, min(len(names), n * 4)):
            d = json.loads(_get(f"https://raw.githubusercontent.com/arcprize/ARC-AGI-2/main/data/evaluation/{name}"))
            cells = sum(len(g) * len(g[0]) for p in d["train"] + d["test"] for g in (p["input"], p.get("output") or [[0]]))
            tasks.append({"id": "arc_" + name[:-5], "train": d["train"], "test": d["test"], "cells": cells})
        # самые компактные — иначе одна задача съедает десятки тысяч токенов
        return sorted(tasks, key=lambda t: t["cells"])[:n]
    return _cached("arc_agi_2", n, load)


def _lcb_tests(row):
    tests = json.loads(row["public_test_cases"] or "[]")
    try:
        raw = zlib.decompress(base64.b64decode(row["private_test_cases"]))
        priv = _SafeUnpickler(io.BytesIO(raw)).load()
        tests += json.loads(priv) if isinstance(priv, str) else []
    except Exception:
        pass
    return tests[:12]


def load_lcb(n, token=None):
    def load():
        url = "https://huggingface.co/datasets/livecodebench/code_generation_lite/resolve/main/test6.jsonl"
        import local
        rows, buf = [], b""
        with local.urlopen(urllib.request.Request(url, headers={"User-Agent": "llm-bench"}), 120) as r:
            while len(rows) < n * 5:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf and len(rows) < n * 5:
                    line, buf = buf.split(b"\n", 1)
                    rows.append(json.loads(line))
        rnd = random.Random(SEED)
        by = {d: [x for x in rows if x["difficulty"] == d] for d in ("easy", "medium", "hard")}
        per = {"easy": n // 3, "medium": n // 3, "hard": n - 2 * (n // 3)}
        pick = [x for d, k in per.items() for x in rnd.sample(by[d], min(k, len(by[d])))]
        return [{"id": f"lcb_{x['question_id']}", "title": x["question_title"], "question": x["question_content"],
                 "starter": x.get("starter_code") or "", "difficulty": x["difficulty"], "platform": x["platform"],
                 "tests": _lcb_tests(x)} for x in pick]
    return _cached("livecodebench", n, load)


LOADERS = {"mmlu_pro": load_mmlu_pro, "gpqa": load_gpqa, "hle": load_hle, "arc_agi_2": load_arc, "livecodebench": load_lcb}


# ---------------- проверки ----------------
def _final_letter(t, letters):
    m = re.findall(r"(?:ответ|answer)\s*[:：]?\s*\**\(?([%s])\)?" % letters, t, re.I)
    if m:
        return m[-1].upper()
    m = re.findall(r"\b([%s])\b" % letters, t.strip()[-40:])
    return m[-1].upper() if m else None


def chk_choice(answer, letters):
    def f(t):
        got = _final_letter(t, letters)
        return float(got == answer), f"ответ {got or '—'}, верно {answer}"
    return f


def _norm(s):
    s = str(s).strip().lower().strip("$ .").replace("\\,", "").replace(",", ".")
    return re.sub(r"\s+", " ", re.sub(r"\\(text|mathrm)\{([^}]*)\}", r"\2", s))


def chk_exact(answer):
    def f(t):
        m = re.findall(r"(?:ответ|answer)\s*[:：]\s*(.+)", t, re.I)
        got = (m[-1] if m else t.strip().splitlines()[-1] if t.strip() else "").strip().strip("*")
        a, g = _norm(answer), _norm(got)
        ok = a == g
        if not ok:
            try:
                ok = abs(float(a) - float(g)) <= 1e-6 * max(1, abs(float(a)))
            except ValueError:
                ok = False
        return float(ok), f"ответ «{got[:40]}», верно «{answer[:40]}»"
    return f


def _grid_from(t):
    m = re.findall(r"\[\s*\[[\d,\s\[\]]*\]\s*\]", t)
    for cand in reversed(m):
        try:
            g = json.loads(cand)
            if isinstance(g, list) and g and all(isinstance(r, list) for r in g):
                return g
        except Exception:
            continue
    return None


def chk_arc(expected):
    def f(t):
        g = _grid_from(t)
        return float(g == expected), "сетка совпала" if g == expected else ("сетка не найдена" if g is None else "сетка неверная")
    return f


LCB_HARNESS = r'''
import sys, json
_src = open(sys.argv[1], encoding="utf-8").read()
_ns = {"__name__": "__lcb__"}
exec(compile("from typing import *\nimport collections, heapq, math, itertools, functools, bisect\n" + _src, "solution", "exec"), _ns)
_sol = _ns["Solution"]()
_m = getattr(_sol, sys.argv[2])
_args = [json.loads(x) for x in sys.stdin.read().split("\n") if x.strip()]
print(json.dumps(_m(*_args)))
'''


def chk_lcb(item):
    def f(t):
        from bench import extract_code
        code = extract_code(t)
        tests = item["tests"]
        if not tests:
            return 0.0, "нет тестов"
        method = re.search(r"def (\w+)\(self", item["starter"] or "")
        ok = 0
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "sol.py"
            src.write_text(code, encoding="utf-8")
            harness = Path(d) / "h.py"
            harness.write_text(LCB_HARNESS, encoding="utf-8")
            deadline = time.time() + 60
            for tc in tests:
                if time.time() > deadline:
                    break
                try:
                    if tc.get("testtype") == "functional" and method:
                        r = subprocess.run([sys.executable, "-I", str(harness), str(src), method.group(1)], input=tc["input"],
                                           capture_output=True, text=True, timeout=6, cwd=d)
                        good = r.returncode == 0 and json.loads(r.stdout.strip() or "null") == json.loads(tc["output"])
                    else:
                        r = subprocess.run([sys.executable, "-I", str(src)], input=tc["input"], capture_output=True, text=True, timeout=6, cwd=d)
                        good = r.returncode == 0 and r.stdout.split() == tc["output"].split()
                except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
                    good = False
                ok += good
        return ok / len(tests), f"тесты {ok}/{len(tests)} · {item['difficulty']}"
    return f


# ---------------- задачи для бенчмарка ----------------
THINK = "Рассуждай кратко. В последней строке напиши только «Ответ: X»."


def _grid_txt(g):
    return json.dumps(g).replace("], [", "],\n [")


def to_tasks(bench, items):
    tasks = []
    info = BENCHES[bench]
    for it in items:
        if bench in ("mmlu_pro", "gpqa"):
            letters = "ABCDEFGHIJ"[:len(it["options"])]
            opts = "\n".join(f"{letters[i]}) {o}" for i, o in enumerate(it["options"]))
            prompt = f"{it['question']}\n\n{opts}\n\n{THINK.replace('X', 'буква варианта')}"
            check = chk_choice(it["answer"], letters)
        elif bench == "hle":
            if it.get("answer_type") == "multipleChoice":
                letters = "ABCDEFGHIJKLMNOP"
                prompt = f"{it['question']}\n\n{THINK.replace('X', 'буква варианта')}"
                check = chk_choice(it["answer"].strip().upper()[:1], letters)
            else:
                prompt = f"{it['question']}\n\n{THINK.replace('X', 'точный короткий ответ')}"
                check = chk_exact(it["answer"])
        elif bench == "arc_agi_2":
            ex = "\n\n".join(f"Пример {i + 1}\nВход:\n{_grid_txt(p['input'])}\nВыход:\n{_grid_txt(p['output'])}" for i, p in enumerate(it["train"]))
            prompt = (f"Найди правило, по которому вход превращается в выход, и примени его к тесту. Числа — цвета клеток.\n\n{ex}\n\n"
                      f"Тест\nВход:\n{_grid_txt(it['test'][0]['input'])}\n\n"
                      "В конце выведи только итоговую сетку в формате JSON: [[...],[...]].")
            check = chk_arc(it["test"][0]["output"])
        else:  # livecodebench
            if it["starter"]:
                fmt = f"Используй заготовку и верни полный класс:\n```python\n{it['starter']}\n```"
            else:
                fmt = "Программа читает ввод из stdin и печатает ответ в stdout."
            prompt = (f"{it['question']}\n\n{fmt}\n\nНапиши решение на Python 3. Верни только код в одном блоке ```python```.")
            check = chk_lcb(it)
        tasks.append({"id": it["id"], "cat": bench, "prompt": prompt, "check": check,
                      "max_tokens": max(info["out_tokens"] * 3, 4000),
                      "desc": f"{info['name']}" + (f" · {it.get('category')}" if it.get("category") else "")
                              + (f" · {it.get('difficulty')}" if it.get("difficulty") else "")})
    return tasks


def build(selected, token=None, emit=lambda ev: None):
    """selected: {bench: n}. → (задачи, предупреждения)."""
    tasks, warns = [], []
    for bench, n in selected.items():
        if bench not in BENCHES or not n:
            continue
        info = BENCHES[bench]
        if info["gated"] and not token:
            warns.append(f"{info['name']}: набор закрытый — вставьте токен Hugging Face и примите условия на {info['site']}")
            continue
        emit({"type": "activity", "text": f"Загружаю {info['name']}: {n} заданий (один раз, дальше из кэша)"})
        try:
            items = LOADERS[bench](int(n), token)
        except Exception as e:
            warns.append(f"{info['name']}: не удалось загрузить — {str(e)[:200]}")
            continue
        tasks += to_tasks(bench, items)
    return tasks, warns


def estimate(selected):
    """Грубая оценка токенов на прогон без учёта скрытой инструкции сервиса."""
    per_in = {"mmlu_pro": 350, "gpqa": 450, "hle": 600, "arc_agi_2": 6000, "livecodebench": 900}
    out = {}
    for b, n in selected.items():
        if b in BENCHES and n:
            out[b] = int(n) * (per_in[b] + BENCHES[b]["out_tokens"])
    return out
