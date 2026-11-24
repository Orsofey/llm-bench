#!/usr/bin/env python3
"""Скачивает открытые источники и создаёт воспроизводимые мини-наборы LLM Bench.
GPQA и HLE намеренно не скачиваются: это gated-наборы, их получает приложение по токену пользователя.
"""
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public_data"
OUT.mkdir(exist_ok=True)
HF = "https://datasets-server.huggingface.co"
MMLU_CATEGORIES = ["math", "health", "physics", "business", "biology", "chemistry", "computer science",
                   "economics", "engineering", "philosophy", "other", "psychology", "history", "law"]
LETTERS = "ABCDEFGHIJ"


def get_json(url, timeout=120, retries=4):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LLM-Bench/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except Exception as e:
            last = e
            if attempt + 1 < retries:
                time.sleep(2 ** attempt * 2)
    raise last


def hf_rows(dataset, config, split, offset=0, length=100, where=None):
    params = {"dataset": dataset, "config": config, "split": split, "offset": offset, "length": length}
    endpoint = "filter" if where else "rows"
    if where:
        params["where"] = where
    return get_json(f"{HF}/{endpoint}?" + urllib.parse.urlencode(params))


def write(name, data):
    path = OUT / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name}: {len(data)} tasks, {path.stat().st_size:,} bytes")


def build_mmlu():
    selected = []
    for i, category in enumerate(MMLU_CATEGORIES):
        # В каждой дисциплине 3 вопроса; в history и law по 2, итого ровно 40.
        needed = 2 if i >= 12 else 3
        try:
            data = hf_rows("TIGER-Lab/MMLU-Pro", "default", "test", length=100,
                           where=f'"category"=\'{category}\'')
        except Exception as e:
            raise RuntimeError(f"MMLU-Pro category {category}: {e}")
        rows = [item for item in data.get("rows", []) if len(item.get("row", {}).get("options") or []) == 10][:needed]
        if len(rows) != needed:
            raise RuntimeError(f"MMLU-Pro category {category}: got {len(rows)} ten-option questions instead of {needed}")
        for item in rows:
            r = item["row"]
            selected.append({"id": f"mmlu_pro_{r['question_id']}", "question": r["question"],
                             "choices": r["options"], "answer": LETTERS[int(r["answer_index"])],
                             "category": category, "source_row": item["row_idx"]})
    assert len(selected) == 40, f"MMLU-Pro count: {len(selected)}"
    assert all(len(x["choices"]) == 10 for x in selected), [(x["id"], len(x["choices"])) for x in selected if len(x["choices"]) != 10]
    write("mmlu_pro.json", selected)


def build_arc():
    req = urllib.request.Request("https://api.github.com/repos/arcprize/ARC-AGI-2/contents/data/evaluation",
                                 headers={"User-Agent": "LLM-Bench/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        listing = json.load(response)
    # Равномерно по списку; берём только задания с одним тестовым входом для однозначного ответа.
    candidates = [listing[i] for i in (0, 20, 40, 60, 80, 100, 10, 30, 50, 70, 90, 110)]
    selected = []
    for item in candidates:
        raw = get_json(item["download_url"])
        if len(raw.get("test", [])) != 1:
            continue
        task_id = item["name"].removesuffix(".json")
        selected.append({"id": f"arc_agi_2_{task_id}", "train": raw["train"],
                         "test_input": raw["test"][0]["input"], "answer": raw["test"][0]["output"],
                         "source": item["html_url"]})
        if len(selected) == 6:
            break
    assert len(selected) == 6
    write("arc_agi_2.json", selected)


def build_lcb():
    # code_generation — официальный набор LiveCodeBench. Берём AtCoder-задачи через весь список.
    # Тесты: до 3 публичных + компактные скрытые, всего 6 на задачу.
    offsets = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110,
               120, 5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105, 115]
    raw_cache = ROOT / "build" / "lcb_raw"
    raw_cache.mkdir(parents=True, exist_ok=True)
    selected = []
    for offset in offsets:
        cache_file = raw_cache / f"{offset}.json"
        if cache_file.is_file():
            r = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            data = hf_rows("livecodebench/code_generation", "default", "test", offset=offset, length=1)
            r = data["rows"][0]["row"]
            cache_file.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        public = json.loads(r["public_test_cases"])[:3]
        needed_private = 6 - len(public)
        private_pool = json.loads(r["private_test_cases"])
        private = sorted(private_pool, key=lambda t: len(t.get("input", "")) + len(t.get("output", "")))[:needed_private]
        print(f"LCB {offset}: {r['question_title']} ({r['difficulty']}), tests {len(public)}+{len(private)}")
        if len(public) < 2 or len(private) < needed_private:
            continue
        tests = [{"input": t["input"], "output": t["output"], "visibility": "public" if i < len(public) else "hidden"}
                 for i, t in enumerate(public + private)]
        selected.append({"id": f"livecodebench_{r['platform']}_{r['question_id']}",
                         "title": r["question_title"], "content": r["question_content"],
                         "starter_code": r.get("starter_code") or "", "difficulty": r["difficulty"],
                         "contest_date": r["contest_date"], "platform": r["platform"],
                         "tests": tests, "source_row": offset,
                         "test_size": sum(len(t["input"]) + len(t["output"]) for t in tests)})
        print(f"LCB {offset}: {r['question_title']} ({r['difficulty']}), {len(r['private_test_cases']):,} raw private chars")
    selected = sorted(selected, key=lambda r: r["test_size"])[:12]
    for r in selected:
        r.pop("test_size")
    assert len(selected) == 12 and all(len(x["tests"]) == 6 for x in selected)
    write("livecodebench.json", selected)


def main():
    if "--lcb-only" not in sys.argv:
        build_mmlu()
        build_arc()
    build_lcb()
    manifest = {
        "version": 1,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": {
            "mmlu_pro": "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro",
            "arc_agi_2": "https://github.com/arcprize/ARC-AGI-2/tree/main/data/evaluation",
            "livecodebench": "https://huggingface.co/datasets/livecodebench/code_generation",
        },
        "note": "Fixed mini-subsets, not official leaderboard evaluation. GPQA/HLE are downloaded by the app locally after user authorization.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
