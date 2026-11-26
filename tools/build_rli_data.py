#!/usr/bin/env python3
"""Собирает текстово-проверяемые RLI-задачи и входные данные из официального public set."""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://huggingface.co/datasets/cais/rli-public-set/resolve/main/"


def download(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "LLM-Bench/1.2"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def main():
    records = []
    for task_id, title in (("public_003", "Object Merging Game"), ("public_009", "World Happiness Dashboard")):
        brief = download(f"{task_id}/project/brief.md").decode("utf-8")
        record = {"id": f"rli_{task_id}", "title": title, "brief": brief, "deliverable": "html",
                  "source": f"https://huggingface.co/datasets/cais/rli-public-set/tree/main/{task_id}"}
        if task_id == "public_009":
            raw = download(f"{task_id}/project/inputs/DataForFigure2.1WHR2021C2.xls")
            try:
                import xlrd
            except ImportError as e:
                raise RuntimeError("Для чтения официального XLS нужен xlrd: .venv\\Scripts\\python.exe -m pip install xlrd") from e
            book = xlrd.open_workbook(file_contents=raw)
            sheet = book.sheet_by_index(0)
            headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
            rows = []
            for row in range(1, sheet.nrows):
                item = {headers[col]: sheet.cell_value(row, col) for col in range(sheet.ncols)}
                rows.append(item)
            record["data"] = {"columns": headers, "rows": rows}
            record["source_file"] = f"{task_id}/project/inputs/DataForFigure2.1WHR2021C2.xls"
        records.append(record)
    out = ROOT / "public_data" / "rli.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out}: {len(records)} tasks, {out.stat().st_size:,} bytes")
    for r in records:
        print(r["title"], len(r.get("data", {}).get("rows", [])))


if __name__ == "__main__":
    main()
