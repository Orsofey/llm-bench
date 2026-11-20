"""
Пакетная проверка ключей: по очереди проверяет каждый ключ из списка
(работает ли, та ли модель, честно ли считаются токены, качество) и собирает таблицу.

Формат строки (разделители «;», «|» или табуляция, всё кроме ключа — необязательно):
    [адрес API ;] ключ [; продавец [; цена ₽ [; объём токенов]]]
Примеры:
    sk-ant-api03-...
    sk-xxxx ; ShopName ; 150 ; 1 млн
    https://api.example.ru/v1 | kl_live_... | Магазин | 99 | 500к
"""
import json, re, time
from pathlib import Path

import bench

# ключи с известным сервисом: адрес подставляется сам
KEY_SERVICES = [
    (r"^sk-ant-api", "anthropic", "https://api.anthropic.com", "Anthropic"),
    (r"^sk-or-", "openai", "https://openrouter.ai/api/v1", "OpenRouter"),
    (r"^AIza", "openai", "https://generativelanguage.googleapis.com/v1beta/openai", "Gemini"),
    (r"^sk-(proj|svcacct|admin)-", "openai", "https://api.openai.com/v1", "OpenAI"),
    (r"^gsk_", "openai", "https://api.groq.com/openai/v1", "Groq"),
    (r"^xai-", "openai", "https://api.x.ai/v1", "xAI"),
]
TYPICAL_REQUEST = 2000  # токенов в обычном запросе — для оценки доли скрытой инструкции


def mask(key):
    key = key or ""
    return key if len(key) <= 12 else f"{key[:7]}…{key[-4:]}"


def parse_volume(s):
    """'1 млн' / '500к' / '1.4m' / '1000000' → число токенов."""
    if not s:
        return None
    t = s.strip().lower().replace(" ", "").replace(",", ".")
    m = re.match(r"^(\d+(?:\.\d+)?)(млн|m|kk|м|тыс|к|k)?", t)
    if not m:
        return None
    n = float(m[1])
    mult = {"млн": 1e6, "m": 1e6, "kk": 1e6, "м": 1e6, "тыс": 1e3, "к": 1e3, "k": 1e3}.get(m[2] or "", 1)
    return int(n * mult)


def parse_price(s):
    m = re.search(r"\d+(?:[.,]\d+)?", s or "")
    return float(m[0].replace(",", ".")) if m else None


def parse_lines(text, default_base=""):
    items, errors = [], []
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in re.split(r"\s*[;|\t]\s*", line)]
        base = parts.pop(0) if re.match(r"^https?://", parts[0]) else ""
        if not parts or not parts[0]:
            errors.append(f"строка {n}: нет ключа")
            continue
        key = parts[0]
        if " " in key:
            errors.append(f"строка {n}: в ключе пробел — разделяйте поля «;»")
            continue
        items.append({"line": n, "key": key, "base_url": base or default_base,
                      "seller": parts[1] if len(parts) > 1 else "",
                      "price": parse_price(parts[2]) if len(parts) > 2 else None,
                      "volume": parse_volume(parts[3]) if len(parts) > 3 else None})
    return items, errors


def resolve_service(item):
    """→ (provider, base_url, название) или ошибка."""
    if item["base_url"]:
        return "auto", item["base_url"], re.sub(r"^https?://(api\.)?", "", item["base_url"]).split("/")[0]
    for rx, prov, base, name in KEY_SERVICES:
        if re.match(rx, item["key"]):
            return prov, base, name
    return None, None, "нужен адрес API: укажите его в общем поле или в начале строки"


def pick_model(provider, base, key, model, claimed):
    """Если модель не указана — выбираем из списка сервиса ту, что похожа на заявленную."""
    if model:
        return model, None
    try:
        if provider == "auto":
            found, _ = bench.detect(base, key, None, timeout=30)
            if not found:
                return None, "сервис не ответил ни по одному протоколу"
            provider, base = found["provider"], found["base_url"]
        ms = bench.Client(provider, base, key, None, 32, 30, retries=0).models() or []
    except Exception as e:
        return None, bench.explain(e, base)
    import verify
    fam = verify.family_of(claimed)
    chat = [m for m in ms if not re.search(r"embed|whisper|tts|dall-e|image|moderation|audio|realtime|transcri|rerank", m, re.I)]
    for m in chat:
        if fam and verify.family_of(m) == fam:
            return m, None
    return (chat[0], None) if chat else (None, "сервис не отдаёт список моделей — укажите модель")


def run_batch(cfg, results_dir, emit, cancel):
    """cfg: text, base_url, model, claimed, depth ('verify' | 'full'), behavior, max_tokens, workers."""
    items, errors = parse_lines(cfg.get("text"), (cfg.get("base_url") or "").strip())
    for e in errors:
        emit({"type": "warning", "message": e})
    rows = []
    emit({"type": "batch_start", "items": [{"i": i, "seller": it["seller"], "key": mask(it["key"])} for i, it in enumerate(items)]})
    for i, it in enumerate(items):
        if cancel.is_set():
            break
        row = {"i": i, "line": it["line"], "key": mask(it["key"]), "seller": it["seller"], "price": it["price"],
               "volume": it["volume"], "status": "fail"}
        emit({"type": "batch_item", "i": i, "state": "running", "row": row})
        provider, base, service = resolve_service(it)
        row["service"] = service
        if not provider:
            row["error"] = service
            row["service"] = "—"
        else:
            model, err = pick_model(provider, base, it["key"], (cfg.get("model") or "").strip(), cfg.get("claimed") or "")
            if not model:
                row["error"] = err
            else:
                row["model"] = model
                captured = {}

                def sub_emit(ev, i=i):
                    t = ev["type"]
                    if t in ("error", "warning"):
                        captured.setdefault("messages", []).append(ev["message"])
                    if t == "activity":
                        emit({"type": "batch_activity", "i": i, "text": ev["text"]})
                    if t == "usage":
                        emit({"type": "batch_usage", "i": i, "requests": ev["requests"], "in": ev["in"], "out": ev["out"]})

                run_cfg = {"provider": provider, "base_url": base, "key": it["key"], "model": model,
                           "tag": it["seller"] or "пакет", "claimed": cfg.get("claimed") or model,
                           "only": ["hard"] if cfg.get("depth") == "full" else ["__none__"], "ctx_chars": 0,
                           "verify": True, "behavior": bool(cfg.get("behavior")), "repeat": 1,
                           "workers": int(cfg.get("workers") or 1), "max_tokens": int(cfg.get("max_tokens") or 2000),
                           "out": str(results_dir)}
                try:
                    fn = bench.run_benchmark(run_cfg, sub_emit, cancel)
                except Exception as e:
                    fn, captured["messages"] = None, [str(e)[:300]]
                if fn:
                    rep = json.loads(Path(fn).read_text(encoding="utf-8"))
                    ver, h = rep.get("verify") or {}, rep.get("health") or {}
                    vd, fp = ver.get("verdict") or {}, ver.get("fingerprint") or {}
                    hon = ver.get("honesty") or {}
                    row.update(status="ok", file=Path(fn).name, verdict=vd.get("level"), verdict_text=vd.get("text"),
                               best_match=((vd.get("matches") or [{}])[0]).get("name"),
                               overhead=fp.get("overhead"), ping=h.get("ping_sec"), tps=h.get("tok_per_sec"),
                               served=h.get("served_model"), score=(rep.get("summary") or {}).get("TOTAL"),
                               tokens=rep.get("tokens"), warnings=captured.get("messages", []),
                               max_tokens_ok=(hon.get("max_tokens") or {}).get("ok"),
                               out_tokens_ok=(hon.get("output_tokens") or {}).get("ok"))
                else:
                    row["error"] = "; ".join(captured.get("messages", [])) or "проверка не завершилась"
        # цена: за 1 млн по объёму пакета и за 1 млн «полезных» токенов с учётом скрытой инструкции
        if row.get("price") is not None and row.get("volume"):
            row["price_per_m"] = round(row["price"] / row["volume"] * 1e6, 2)
            if row.get("overhead"):
                useful = TYPICAL_REQUEST / (TYPICAL_REQUEST + row["overhead"])
                row["useful_share"] = round(useful, 2)
                row["price_per_m_useful"] = round(row["price_per_m"] / useful, 2)
        rows.append(row)
        emit({"type": "batch_item", "i": i, "state": "done", "row": row})

    out = Path(results_dir)
    out.mkdir(parents=True, exist_ok=True)
    fn = out / f"batch_{time.strftime('%Y%m%d_%H%M%S')}.json"
    fn.write_text(json.dumps({"type": "batch", "date": time.strftime("%Y-%m-%d %H:%M"), "claimed": cfg.get("claimed"),
                              "model": cfg.get("model"), "depth": cfg.get("depth"), "rows": rows},
                             ensure_ascii=False, indent=1), encoding="utf-8")
    emit({"type": "batch_done", "file": fn.name, "rows": rows, "cancelled": cancel.is_set()})
    return fn


def last_batch(results_dir):
    files = sorted(Path(results_dir).glob("batch_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return json.loads(files[0].read_text(encoding="utf-8")) if files else None
