"""Обновляемый каталог LLM: Models.dev + Artificial Analysis + LMArena + свои прогоны."""
import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MODELS_DEV = "https://models.dev/api.json"
AA_LIST = "https://artificialanalysis.ai/api/v2/language/models"
AA_FREE = "https://artificialanalysis.ai/api/v2/language/models/free"
ARENA_CSV = "https://raw.githubusercontent.com/kevinschaul/lmarena-leaderboard-history/main/history.csv"
CACHE_TTL = 24 * 3600

COUNTRY = {
    "openai": "us", "anthropic": "us", "google": "us", "meta": "us", "xai": "us", "microsoft": "us",
    "amazon": "us", "nvidia": "us", "ibm": "us", "databricks": "us", "perplexity": "us", "snowflake": "us",
    "salesforce": "us", "together": "us", "fireworks": "us", "groq": "us", "cerebras": "us", "cloudflare": "us",
    "reka": "us", "poolside": "us", "cursor": "us", "nomic": "us", "ai2": "us", "allenai": "us",
    "alibaba": "cn", "deepseek": "cn", "zhipuai": "cn", "z-ai": "cn", "zai": "cn", "moonshotai": "cn",
    "moonshot": "cn", "tencent": "cn", "bytedance": "cn", "bytedance-seed": "cn", "baidu": "cn",
    "xiaomi": "cn", "minimax": "cn", "stepfun": "cn", "meituan": "cn", "inclusionai": "cn", "huawei": "cn",
    "openbmb": "cn", "internlm": "cn", "01-ai": "cn", "01ai": "cn", "ant-group": "cn", "antgroup": "cn",
    "iflytek": "cn", "sensetime": "cn", "baichuan": "cn", "modelscope": "cn", "lingyi": "cn",
    "sber": "ru", "gigachat": "ru", "yandex": "ru", "yandexgpt": "ru", "tbank": "ru",
    "mistral": "fr", "mistralai": "fr", "aleph-alpha": "de", "black-forest-labs": "de", "stability-ai": "gb",
    "swiss-ai": "ch", "lightonai": "fr", "open-eu": "eu", "nebius": "nl", "nscale": "gb", "scml": "gb",
    "cohere": "ca", "ai21": "il", "ai21-labs": "il", "upstage": "kr", "naver": "kr", "lg": "kr",
    "sakana": "jp", "preferred-networks": "jp", "stockmark": "jp", "cyberagent": "jp", "rinna": "jp",
    "tii": "ae", "inception": "ae", "g42": "ae", "core42": "ae", "silo-ai": "fi", "huggingface": "us",
}
REGION = {"us": "США", "cn": "Китай", "ru": "Россия", "ca": "Канада", "il": "Израиль", "kr": "Корея",
          "jp": "Япония", "ae": "ОАЭ", "fi": "Европа", "gb": "Европа", "fr": "Европа", "de": "Европа",
          "ch": "Европа", "nl": "Европа", "eu": "Европа", "es": "Европа", "it": "Европа", "se": "Европа",
          "dk": "Европа", "no": "Европа", "at": "Европа", "be": "Европа", "pt": "Европа", "ie": "Европа"}
COUNTRY_NAMES = {"us": "США", "cn": "Китай", "ru": "Россия", "ca": "Канада", "il": "Израиль", "kr": "Корея",
                 "jp": "Япония", "ae": "ОАЭ", "fr": "Франция", "de": "Германия", "gb": "Великобритания",
                 "ch": "Швейцария", "nl": "Нидерланды", "fi": "Финляндия", "eu": "Европа"}
SUPPLEMENTS = [
    {"id": "sber/gigachat-2-max", "name": "GigaChat 2.0 Max", "lab": "Sber", "provider": "sber",
     "description": "Флагманское семейство российской модели GigaChat 2.0. Версии и доступ зависят от кабинета Sber.",
     "source_url": "https://developers.sber.ru/docs/ru/gigachat/models", "country": "ru"},
    {"id": "sber/gigachat-2-pro", "name": "GigaChat 2.0 Pro", "lab": "Sber", "provider": "sber",
     "description": "Сбалансированное семейство GigaChat 2.0 для рабочих задач. Точные бенчмарки показываются только при наличии источника.",
     "source_url": "https://developers.sber.ru/docs/ru/gigachat/models", "country": "ru"},
    {"id": "sber/gigachat-2-lite", "name": "GigaChat 2.0 Lite", "lab": "Sber", "provider": "sber",
     "description": "Лёгкое семейство GigaChat 2.0 для быстрых и недорогих запросов.",
     "source_url": "https://developers.sber.ru/docs/ru/gigachat/models", "country": "ru"},
    {"id": "yandex/yandexgpt-pro", "name": "YandexGPT Pro", "lab": "Yandex", "provider": "yandex",
     "description": "Старшее семейство YandexGPT для сложных сценариев. Конкретная версия выбирается в Yandex Cloud.",
     "source_url": "https://cloud.yandex.ru/docs/yandexgpt/concepts/models", "country": "ru"},
    {"id": "yandex/yandexgpt-lite", "name": "YandexGPT Lite", "lab": "Yandex", "provider": "yandex",
     "description": "Быстрое и экономичное семейство YandexGPT. Конкретная версия выбирается в Yandex Cloud.",
     "source_url": "https://cloud.yandex.ru/docs/yandexgpt/concepts/models", "country": "ru"},
    {"id": "yandex/yandexgpt-32k", "name": "YandexGPT 32K", "lab": "Yandex", "provider": "yandex",
     "description": "Семейство YandexGPT с увеличенным контекстом до 32 тыс. токенов. Проверяйте доступную версию в кабинете.",
     "source_url": "https://cloud.yandex.ru/docs/yandexgpt/concepts/models", "country": "ru"},
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_json(url, token=None, timeout=60):
    headers = {"User-Agent": "LLM-Bench/1.1 (https://github.com/Orsofey/llm-bench)"}
    if token:
        headers["x-api-key"] = token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def get_text(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "LLM-Bench/1.1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_cache(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def country_for(lab, provider):
    lab, provider = str(lab or "").lower(), str(provider or "").lower()
    return COUNTRY.get(lab) or COUNTRY.get(provider) or COUNTRY.get(lab.replace("_", "-")) or COUNTRY.get(provider.replace("_", "-")) or "other"


def region_for(country):
    return REGION.get(country, "Другие")


def normalize_models_dev(raw):
    merged = {}
    for provider_id, provider in raw.items():
        for model_id, m in (provider.get("models") or {}).items():
            canonical = m.get("canonical_model_id") or f"{provider_id}/{model_id}"
            lab = canonical.split("/", 1)[0] if "/" in canonical else provider_id
            rec = merged.setdefault(canonical, {
                "id": canonical, "name": m.get("name") or model_id, "lab": lab,
                "provider": provider_id, "provider_name": provider.get("name") or provider_id,
                "description": m.get("description") or "", "family": m.get("family") or "",
                "release_date": m.get("release_date"), "last_updated": m.get("last_updated"),
                "open_weights": m.get("open_weights"), "reasoning": m.get("reasoning"),
                "tool_call": m.get("tool_call"), "structured_output": m.get("structured_output"),
                "temperature": m.get("temperature"), "modalities": m.get("modalities") or {},
                "context": (m.get("limit") or {}).get("context"), "output_limit": (m.get("limit") or {}).get("output"),
                "cost": m.get("cost") or {}, "providers": [], "source_url": f"https://models.dev/models/{canonical}",
                "type": m.get("type") or "chat", "country": country_for(lab, provider_id),
            })
            rec["providers"].append({"id": provider_id, "name": provider.get("name") or provider_id,
                                     "api": provider.get("api"), "doc": provider.get("doc")})
            if not rec.get("last_updated") or (m.get("last_updated") or "") > rec["last_updated"]:
                rec["last_updated"] = m.get("last_updated")
            if not rec.get("release_date") or (m.get("release_date") or "") < rec["release_date"]:
                rec["release_date"] = m.get("release_date")
            rec["country"] = country_for(lab, provider_id)
    out = []
    excluded_types = {"image", "audio", "speech", "video", "embedding", "moderation", "tts", "rerank"}
    excluded_names = re.compile(r"embed|whisper|tts|dall-e|image|moderation|audio|realtime|transcri|rerank|sora|veo|imagen|lyria", re.I)
    for rec in merged.values():
        outputs = (rec["modalities"].get("output") or [])
        if rec["type"] in excluded_types or (outputs and "text" not in outputs) or excluded_names.search(rec["id"]):
            continue
        rec["region"] = region_for(rec["country"])
        rec["country_name"] = COUNTRY_NAMES.get(rec["country"], rec["country"].upper())
        rec["benchmarks"] = {}
        out.append(rec)
    for item in SUPPLEMENTS:
        item = dict(item)
        item.update(release_date=None, last_updated=None, open_weights=False, reasoning=None, tool_call=None,
                    structured_output=None, temperature=None, modalities={"input": ["text"], "output": ["text"]},
                    context=None, output_limit=None, cost={}, providers=[{"id": item["provider"], "name": item["lab"]}],
                    type="chat", family="", provider_name=item["lab"], region=region_for(item["country"]),
                    country_name=COUNTRY_NAMES[item["country"]], benchmarks={})
        out.append(item)
    return out


def fetch_aa(key):
    pages, tier = [], None
    try:
        endpoint = AA_LIST
        for page in range(1, 20):
            data = get_json(endpoint + "?" + urllib.parse.urlencode({"page": page}), key)
            tier = data.get("tier")
            pages.extend(data.get("data") or [])
            if not (data.get("pagination") or {}).get("has_more"):
                break
    except urllib.error.HTTPError as e:
        if e.code != 403:
            raise
        pages, tier = [], "free"
        for page in range(1, 20):
            data = get_json(AA_FREE + "?" + urllib.parse.urlencode({"page": page}), key)
            pages.extend(data.get("data") or [])
            if not (data.get("pagination") or {}).get("has_more"):
                break
    out = {}
    for m in pages:
        ev = m.get("evaluations") or {}
        perf = m.get("performance_v3") or {}
        pricing = m.get("pricing") or {}
        record = {"aa_name": m.get("name"), "aa_slug": m.get("slug"), "openrouter_id": m.get("openrouter_api_id"),
                  "aa_intelligence": ev.get("artificial_analysis_intelligence_index"),
                  "aa_engineering": ev.get("artificial_analysis_engineering_index"),
                  "aa_economics": ev.get("artificial_analysis_economics_index"),
                  "aa_finance": ev.get("artificial_analysis_finance_and_accounting_index"),
                  "aa_strategy": ev.get("artificial_analysis_strategy_and_ops_index"),
                  "aa_legal": ev.get("artificial_analysis_legal_index"),
                  "aa_healthcare": ev.get("artificial_analysis_healthcare_and_medical_index"),
                  "gpqa": ev.get("gpqa_diamond"), "hle": ev.get("hle"),
                  "lcb": ev.get("scicode") if ev.get("scicode") is not None else ev.get("frontiercode_v2_0"),
                  "terminal_bench": ev.get("terminalbench_v4_1"), "frontier_code": ev.get("frontiercode_v2_0"),
                  "hle_diamond": ev.get("hle_diamond"), "aa_speed": perf.get("mean_output_tokens_per_second"),
                  "aa_first_answer": perf.get("mean_time_to_first_answer_token_seconds"),
                  "aa_price_input": pricing.get("price_1m_input_tokens"),
                  "aa_price_output": pricing.get("price_1m_output_tokens"), "tier": tier}
        keys = [k for k in (record["openrouter_id"], record["aa_name"], record["aa_slug"]) if k]
        for key_value in keys:
            out.setdefault(norm(key_value), record)
    return out, tier


def fetch_arena():
    text = get_text(ARENA_CSV)
    latest = {}
    for row in csv.DictReader(io.StringIO(text)):
        model = row.get("model")
        if not model:
            continue
        if model not in latest or (row.get("date") or "") > latest[model]["arena_date"]:
            latest[model] = {"arena": float(row["score"]), "arena_rank": int(row["rank"]),
                             "arena_votes": row.get("votes"), "arena_date": row.get("date"),
                             "arena_organization": row.get("organization")}
    return {norm(k): v for k, v in latest.items()}


def merge_benchmarks(models, aa, arena):
    for m in models:
        keys = [m["id"], m.get("name")]
        if m.get("openrouter_id"):
            keys.append(m["openrouter_id"])
        external = next((aa[norm(k)] for k in keys if k and norm(k) in aa), None)
        if external:
            m["benchmarks"].update(external)
        history = next((arena[norm(k)] for k in keys if k and norm(k) in arena), None)
        if history:
            m["benchmarks"].update(history)


def attach_own_results(models, results):
    by_model = {}
    for r in results:
        raw = r.get("model") or r.get("label")
        if raw:
            by_model.setdefault(norm(raw), r)
        if r.get("label"):
            by_model.setdefault(norm(r["label"]), r)
            without_tag = re.sub(r"\s*\[[^]]*\]\s*$", "", r["label"]).strip()
            by_model.setdefault(norm(without_tag), r)
    for m in models:
        candidates = [m["id"], m.get("name"), m["id"].split("/", 1)[-1]]
        own = next((by_model[norm(k)] for k in candidates if k and norm(k) in by_model), None)
        if own:
            m["own"] = own


def merge_all(raw_models, aa, arena, results):
    models = normalize_models_dev(raw_models)
    merge_benchmarks(models, aa, arena)
    attach_own_results(models, results)
    models.sort(key=lambda m: ((m["benchmarks"].get("aa_intelligence") is None),
                               -(m["benchmarks"].get("aa_intelligence") or 0), m["name"].lower()))
    return models


def catalog(results, aa_key=None, force=False):
    results = Path(results)
    cache = results.parent / "catalog_cache"
    models_path = cache / "models_dev.json"
    aa_path = cache / "artificial_analysis.json"
    arena_path = cache / "arena.json"
    meta_path = cache / "meta.json"
    meta = read_cache(meta_path, {}) or {}
    raw_models = read_cache(models_path)
    aa = read_cache(aa_path, {}) or {}
    arena = read_cache(arena_path, {}) or {}
    errors = []
    stale = force or not raw_models or (time.time() - float(meta.get("models_dev_fetched", 0)) > CACHE_TTL)
    if stale:
        try:
            raw_models = get_json(MODELS_DEV)
            atomic_write(models_path, raw_models)
            meta["models_dev_fetched"] = time.time()
            meta["models_dev_date"] = utc_now()
        except Exception as e:
            errors.append(f"Models.dev: {e}")
    if aa_key:
        try:
            aa, tier = fetch_aa(aa_key)
            atomic_write(aa_path, aa)
            meta["aa_fetched"] = time.time()
            meta["aa_date"] = utc_now()
            meta["aa_tier"] = tier
        except Exception as e:
            errors.append(f"Artificial Analysis: {e}")
    if force or not arena or (time.time() - float(meta.get("arena_fetched", 0)) > CACHE_TTL * 7):
        try:
            arena = fetch_arena()
            atomic_write(arena_path, arena)
            meta["arena_fetched"] = time.time()
            meta["arena_date"] = utc_now()
        except Exception as e:
            errors.append(f"LMArena: {e}")
    if not raw_models:
        return {"models": [], "sources": meta, "errors": errors + ["Каталог ещё не скачан и кеш отсутствует"]}
    atomic_write(meta_path, meta)
    from app import list_results
    return {"models": merge_all(raw_models, aa, arena, list_results()), "sources": meta, "errors": errors}
