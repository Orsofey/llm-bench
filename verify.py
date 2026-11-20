"""
Проверка подлинности ключа: та ли модель отвечает, что заявлена.

Сигналы (от сильного к слабому):
1. Отпечаток токенизатора — разница входных токенов между запросами с пробным текстом и без него.
   Скрытая инструкция сервиса при вычитании сокращается, остаётся «почерк» токенизатора семейства моделей.
2. Поведенческий отпечаток — распределение ответов на одинаковые вопросы при temperature=1
   (идея из работ по аудиту подмены моделей: model equality testing, RUT, API-TAIL).
3. Честность учёта токенов — соблюдение max_tokens и совпадение выходных токенов с ожидаемым.
4. Формат ответа API, скрытая инструкция, скорость, самоназвание (слабые сигналы).

Эталоны: снимаются с официального ключа и хранятся в results/references.json.
Эталоны GPT считаются локально, если установлен tiktoken (pip install tiktoken).
"""
import json, re, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

Q = "Ответь одним словом: ok"
PROBES = {
    "en": "The editor trimmed the interview, balanced the audio levels, and exported a vertical cut for social media. "
          "Meanwhile, the analytics dashboard showed that retention dropped sharply after the first seven seconds.",
    "ru": "Монтажёр вырезал паузы из интервью, выровнял громкость и сделал вертикальную версию для коротких роликов. "
          "Тем временем аналитика показала, что удержание резко падает после первых семи секунд.",
    "code": "def merge(a, b):\n    out = []\n    i = j = 0\n    while i < len(a) and j < len(b):\n"
            "        if a[i] <= b[j]:\n            out.append(a[i]); i += 1\n        else:\n            out.append(b[j]); j += 1\n"
            "    return out + a[i:] + b[j:]\n",
    "num": "3.14159265358979 2718281828459045 1618033988749894 00:01:02,500 --> 00:01:04,250 +7 (912) 345-67-89",
    "mix": "😀🚀🎬 你好世界 こんにちは ∑∫√∞ ®™© ẞßæø Ωμπ «ёлочки» — …",
}
PROBE_NAMES = {"en": "Английский", "ru": "Русский", "code": "Код", "num": "Числа", "mix": "Эмодзи/иероглифы"}

BEHAVIOR = [
    ("animal", "Назови одно случайное животное. Только одно слово, без точки."),
    ("number", "Назови случайное число от 1 до 50. Только число."),
    ("color", "Придумай один необычный цвет. Одно слово."),
]
BEHAVIOR_N = 8

FAMILY_RE = [("claude", r"claude|anthropic|opus|sonnet|haiku|fable"), ("gpt", r"gpt|openai|chatgpt|\bo\d|o200k|cl100k|codex"),
             ("gemini", r"gemini|gemma|google"), ("deepseek", r"deepseek"), ("grok", r"grok|xai"),
             ("qwen", r"qwen|qwq|alibaba"), ("llama", r"llama|meta"), ("mistral", r"mistral|mixtral"),
             ("kimi", r"kimi|moonshot"), ("glm", r"glm|zhipu"), ("gigachat", r"gigachat|sber"), ("yandex", r"yandex|alice")]
FAMILY_NAMES = {"claude": "Claude (Anthropic)", "gpt": "GPT (OpenAI)", "gemini": "Gemini (Google)", "deepseek": "DeepSeek",
                "grok": "Grok (xAI)", "qwen": "Qwen", "llama": "Llama", "mistral": "Mistral", "kimi": "Kimi", "glm": "GLM",
                "gigachat": "GigaChat", "yandex": "YandexGPT"}


def family_of(text):
    t = (text or "").lower()
    for fam, rx in FAMILY_RE:
        if re.search(rx, t):
            return fam
    return None


def probe_prompt(p):
    return p + "\n\n" + Q


# ---------------- эталоны ----------------
def builtin_refs():
    """Эталоны токенизаторов OpenAI, если на компьютере есть tiktoken."""
    try:
        import tiktoken
    except ImportError:
        return []
    out = []
    for enc_name, label in (("o200k_base", "OpenAI GPT-4o / 4.1 / o-серия / GPT-5 — токенизатор o200k"),
                            ("cl100k_base", "OpenAI GPT-4 / GPT-3.5 — токенизатор cl100k")):
        try:
            e = tiktoken.get_encoding(enc_name)
        except Exception:
            continue
        base = len(e.encode(Q))
        out.append({"name": label, "family": "gpt", "builtin": True,
                    "deltas": {k: len(e.encode(probe_prompt(p))) - base for k, p in PROBES.items()}})
    return out


def refs_path(results_dir):
    return Path(results_dir) / "references.json"


def load_refs(results_dir, with_builtin=True):
    p = refs_path(results_dir)
    user = []
    if p.is_file():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            user = []
    return user + (builtin_refs() if with_builtin else [])


def save_ref(results_dir, run, name):
    """run — JSON отчёта прогона. Берём из него отпечатки, качество и скорость."""
    v = run.get("verify") or {}
    if not (v.get("fingerprint") or {}).get("deltas"):
        raise ValueError("В этом прогоне нет отпечатка токенизатора")
    refs = [r for r in load_refs(results_dir, False) if r.get("name") != name]
    refs.append({"name": name, "family": family_of(name) or family_of(run.get("model")), "model": run.get("model"),
                 "date": run.get("date"), "deltas": v["fingerprint"]["deltas"],
                 "behavior": (v.get("behavior") or {}).get("dist"), "summary": run.get("summary"),
                 "tok_per_sec": (run.get("health") or {}).get("tok_per_sec"), "source_file": run.get("file")})
    p = refs_path(results_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(refs, ensure_ascii=False, indent=1), encoding="utf-8")
    return refs


def delete_ref(results_dir, name):
    refs = [r for r in load_refs(results_dir, False) if r.get("name") != name]
    refs_path(results_dir).write_text(json.dumps(refs, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------- сравнение ----------------
def fp_similarity(a, b):
    """(похожесть 0..1, совпадает ли). Допуск ±2 токена или 3% на пробу — граница склейки токенов."""
    keys = [k for k in PROBES if a.get(k) is not None and b.get(k) is not None]
    if not keys:
        return 0.0, False
    errs = [abs(a[k] - b[k]) / max(b[k], 1) for k in keys]
    match = all(abs(a[k] - b[k]) <= max(2, 0.03 * b[k]) for k in keys)
    return round(max(0.0, 1 - sum(errs) / len(errs)), 3), match


def behavior_similarity(a, b):
    """1 − расстояние полной вариации, усреднённое по вопросам."""
    sims = []
    for k in (a or {}):
        if k not in (b or {}):
            continue
        da, db = a[k], b[k]
        na, nb = sum(da.values()) or 1, sum(db.values()) or 1
        keys = set(da) | set(db)
        tvd = 0.5 * sum(abs(da.get(x, 0) / na - db.get(x, 0) / nb) for x in keys)
        sims.append(1 - tvd)
    return round(sum(sims) / len(sims), 3) if sims else None


# ---------------- замеры ----------------
def _norm(t):
    return re.sub(r"[^\wё-]", "", (t or "").strip().lower())[:40] or "∅"


def tokenizer_fingerprint(cl):
    base = cl.chat(Q, max_tokens=8)
    if base["in"] is None:
        return {"ok": False, "error": "Сервис не сообщает число токенов (usage) — отпечаток снять нельзя"}
    with ThreadPoolExecutor(len(PROBES)) as ex:
        res = dict(zip(PROBES, ex.map(lambda p: cl.chat(probe_prompt(p), max_tokens=8), PROBES.values())))
    deltas = {k: (r["in"] - base["in"]) if r["in"] is not None else None for k, r in res.items()}
    # скрытая инструкция ≈ вход базового запроса − собственная длина вопроса (по скорости токенизации русского)
    ru_rate = deltas["ru"] / len(PROBES["ru"] + "\n\n") if deltas.get("ru") else 0.3
    own = round(len(Q) * ru_rate) + 8
    return {"ok": True, "base_in": base["in"], "deltas": deltas, "overhead": max(0, base["in"] - own),
            "chars_per_token_ru": round(1 / ru_rate, 2) if ru_rate else None, "meta": base.get("meta")}


def behavior_fingerprint(cl):
    dist = {}

    def one(q):
        try:
            return _norm(cl.chat(q, max_tokens=60, temperature=1)["text"])
        except Exception:
            return None

    with ThreadPoolExecutor(6) as ex:
        for key, q in BEHAVIOR:
            answers = [a for a in ex.map(one, [q] * BEHAVIOR_N) if a]
            d = {}
            for a in answers:
                d[a] = d.get(a, 0) + 1
            dist[key] = d
    uniq = sum(len(d) for d in dist.values()) / max(1, sum(sum(d.values()) for d in dist.values()))
    return {"dist": dist, "diversity": round(uniq, 2)}


def honesty_checks(cl, fp):
    out = {}
    # 1) соблюдение max_tokens
    try:
        r = cl.chat("Напиши подробный рассказ о море на 400 слов.", max_tokens=40)
        est = round(len(r["text"]) / (fp.get("chars_per_token_ru") or 3.5)) if r["text"] else 0
        out["max_tokens"] = {"limit": 40, "reported_out": r["out"], "estimated_out": est,
                             "ok": (r["out"] is None or r["out"] <= 44) and est <= 60}
    except Exception as e:
        out["max_tokens"] = {"error": str(e)[:200]}
    # 2) честность выходных токенов: модель повторяет текст, длину которого в токенах мы уже знаем
    try:
        exp = (fp.get("deltas") or {}).get("ru")
        r = cl.chat("Повтори дословно текст между <t> и </t>, без кавычек, тегов и любых других слов.\n<t>"
                    + PROBES["ru"] + "</t>", max_tokens=400)
        same = re.sub(r"\s+", " ", r["text"]).strip().strip("«»\"") == PROBES["ru"]
        ratio = round(r["out"] / exp, 2) if (r["out"] and exp) else None
        out["output_tokens"] = {"expected": exp, "reported_out": r["out"], "ratio": ratio, "exact_copy": same,
                                "ok": ratio is None or not same or ratio <= 1.25}
    except Exception as e:
        out["output_tokens"] = {"error": str(e)[:200]}
    return out


def api_format(meta, provider):
    """Признаки «родного» ответа API. Перепродавцы часто собирают ответ сами."""
    if not meta:
        return {}
    if provider == "anthropic":
        return {"id": meta.get("id"), "native": str(meta.get("id", "")).startswith("msg_") and meta.get("type") == "message",
                "details": "id msg_…, type=message" if str(meta.get("id", "")).startswith("msg_") else "нестандартный id"}
    native = str(meta.get("id", "")).startswith("chatcmpl-") and bool(meta.get("system_fingerprint"))
    return {"id": meta.get("id"), "native": native,
            "details": ("id chatcmpl-…, есть system_fingerprint" if native else
                        "нет system_fingerprint/нестандартный id — норма для не-OpenAI сервисов")}


# ---------------- вердикт ----------------
def verdict(result, refs, claimed, self_identity=None, served_model=None):
    checks, fp = [], result.get("fingerprint") or {}
    claimed_fam = family_of(claimed)
    matches = []
    if fp.get("ok"):
        for r in refs:
            sim, match = fp_similarity(fp["deltas"], r["deltas"])
            bsim = behavior_similarity((result.get("behavior") or {}).get("dist"), r.get("behavior"))
            matches.append({"name": r["name"], "family": r.get("family"), "builtin": r.get("builtin", False),
                            "similarity": sim, "match": match, "behavior_similarity": bsim, "deltas": r["deltas"]})
        matches.sort(key=lambda m: (-m["match"], -m["similarity"]))
    best = matches[0] if matches else None
    exact = [m for m in matches if m["match"]]
    claimed_refs = [m for m in matches if claimed_fam and m["family"] == claimed_fam]

    # токенизатор
    if not fp.get("ok"):
        checks.append(("bad", "Отпечаток токенизатора", fp.get("error", "не снят")))
    elif not refs:
        checks.append(("info", "Отпечаток токенизатора", "Снят, но сравнить не с чем: сохраните эталон с официального ключа"))
    elif exact:
        fams = sorted({FAMILY_NAMES.get(m["family"], m["family"] or "?") for m in exact})
        lvl = "ok" if (not claimed_fam or any(m["family"] == claimed_fam for m in exact)) else "bad"
        checks.append((lvl, "Отпечаток токенизатора", f"Совпадает с эталоном «{exact[0]['name']}» ({', '.join(fams)})"))
    else:
        checks.append(("warn", "Отпечаток токенизатора",
                       f"Ни с одним эталоном не совпадает. Ближе всего «{best['name']}» — {round(best['similarity'] * 100)}%"))

    # поведение
    if best and best.get("behavior_similarity") is not None:
        b = best["behavior_similarity"]
        checks.append(("ok" if b >= 0.5 else "warn", "Поведение (ответы при temperature=1)",
                       f"Похожесть на «{best['name']}»: {round(b * 100)}%"))

    # скрытая инструкция
    ov = fp.get("overhead")
    if ov is not None:
        if ov > 150:
            checks.append(("warn", "Скрытая инструкция сервиса",
                           f"≈{ov} токенов добавляется к каждому запросу — вы за них платите, и они меняют поведение модели"))
        else:
            checks.append(("ok", "Скрытая инструкция сервиса", f"Не обнаружена (≈{ov} токенов служебных)"))

    # честность
    h = result.get("honesty") or {}
    mt = h.get("max_tokens") or {}
    if "ok" in mt:
        checks.append(("ok" if mt["ok"] else "bad", "Соблюдение max_tokens",
                       f"лимит 40, сервис насчитал {mt.get('reported_out')}, по тексту ≈{mt.get('estimated_out')}"))
    ot = h.get("output_tokens") or {}
    if ot.get("ratio") is not None and ot.get("exact_copy"):
        checks.append(("ok" if ot["ok"] else "bad", "Учёт выходных токенов",
                       f"ожидалось {ot['expected']}, сервис насчитал {ot['reported_out']} (×{ot['ratio']})"))

    # формат API
    af = result.get("api_format") or {}
    if af:
        checks.append(("ok" if af.get("native") else "info", "Формат ответа API", af.get("details", "")))

    # самоназвание и имя модели в ответе
    for label, val in (("Модель в ответе сервера", served_model), ("Как модель себя называет", self_identity)):
        f = family_of(val)
        if val and claimed_fam:
            lvl = "warn" if f and f != claimed_fam else "info"
            checks.append((lvl, label, f"{val[:120]} (слабый сигнал)"))

    # итог
    if not fp.get("ok"):
        level, text = "unknown", "Нельзя проверить: сервис не сообщает число токенов."
    elif exact and claimed_fam and not any(m["family"] == claimed_fam for m in exact):
        level = "fake"
        text = (f"Подмена: заявлено {FAMILY_NAMES.get(claimed_fam, claimed)}, а токенизатор совпадает с "
                f"«{exact[0]['name']}».")
    elif exact and (not claimed_fam or any(m["family"] == claimed_fam for m in exact)):
        level = "ok"
        text = f"Токенизатор совпадает с эталоном «{exact[0]['name']}»."
        if any(c[0] == "bad" for c in checks):
            level, text = "warn", text + " Но есть нарушения учёта токенов — см. ниже."
    elif claimed_fam and claimed_refs:
        level = "fake"
        text = f"Не совпадает с эталоном {FAMILY_NAMES.get(claimed_fam)} — вероятно, другая модель."
    else:
        level = "unknown"
        text = ("Нет эталона для заявленной модели. Прогоните официальный ключ этой модели с галочкой «Сохранить как эталон»."
                if claimed_fam else "Укажите заявленную модель и сохраните эталон с официального ключа, чтобы сравнить.")
    return {"level": level, "text": text, "claimed_family": claimed_fam,
            "checks": [{"level": l, "name": n, "text": t} for l, n, t in checks],
            "matches": [{k: v for k, v in m.items() if k != "deltas"} | {"deltas": m["deltas"]} for m in matches[:5]]}


def run_verify(cl, provider, results_dir, claimed=None, behavior=True, health=None, emit=lambda ev: None):
    res = {}
    emit({"type": "activity", "text": "Снимаю отпечаток токенизатора: 6 запросов с пробными текстами"})
    try:
        res["fingerprint"] = tokenizer_fingerprint(cl)
    except Exception as e:
        res["fingerprint"] = {"ok": False, "error": str(e)[:300]}
    fp = res["fingerprint"]
    res["api_format"] = api_format(fp.get("meta"), provider)
    if fp.get("ok"):
        emit({"type": "activity", "text": "Проверяю честность учёта токенов и соблюдение max_tokens"})
        res["honesty"] = honesty_checks(cl, fp)
    if behavior:
        emit({"type": "activity", "text": f"Снимаю поведенческий отпечаток: {len(BEHAVIOR) * BEHAVIOR_N} коротких ответов при temperature=1"})
        try:
            res["behavior"] = behavior_fingerprint(cl)
        except Exception as e:
            res["behavior"] = {"error": str(e)[:200]}
    health = health or {}
    res["verdict"] = verdict(res, load_refs(results_dir), claimed or cl.model,
                             health.get("self_identity"), health.get("served_model"))
    fp.pop("meta", None)
    return res
