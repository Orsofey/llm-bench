"""Remote Labor Index: реальные brief и статические + LLM-judge проверки."""
import json
import re

import bench


def _html(text):
    match = re.search(r"(?:<!doctype\s+html[^>]*>|<html\b[^>]*>)(.*)</html>", text, re.I | re.S)
    if match:
        return text[match.start():match.end()]
    return text


def _static(record, text):
    html = _html(text).lower()
    checks = []
    if record["id"] == "rli_public_003":
        rules = [
            (r"<html|doctype", "HTML-документ"),
            (r"score|счёт|счет", "счёт"),
            (r"merge|collision|contact", "слияние и коллизии"),
            (r"gravity|velocity|physics|fall|drop|matter", "физика падения"),
            (r"next|preview|indicator", "предпросмотр следующего"),
            (r"gameover|game.over|result|restart|reset|новая игра|new round", "финал и перезапуск"),
            (r"mouse|touch|pointer|click|tap", "мышь и touch"),
            (r"audio|sound|music|web audio", "звук"),
            (r"@media|responsive|viewport", "адаптивность"),
        ]
    else:
        rules = [
            (r"<html|doctype", "HTML-документ"),
            (r"svg|canvas|map|path", "карта"),
            (r"happiness|score|счаст", "метрика счастья"),
            (r"gradient|rgb|hsl|color", "градиент"),
            (r"hover|mouseenter|mouseover|tooltip", "подсказка"),
            (r"click|select|highlight", "выбор страны"),
            (r"chart|bar|spider|radar|plot", "дополнительный график"),
            (r"addEventListener|on\w+\s*=", "обработчики"),
            (r"@media|responsive|viewport", "адаптивность"),
        ]
    for pattern, _ in rules:
        checks.append(bool(re.search(pattern, html, re.I)))
    if record["id"] == "rli_public_009":
        rows = len((record.get("data") or {}).get("rows") or [])
        embedded = sum(name in html for name in ("afghanistan", "finland", "denmark", "canada", "russia", "china"))
        checks.extend([rows >= 100, embedded >= 3])
    return sum(checks) / len(checks), f"статические проверки {sum(checks)}/{len(checks)}"


def _worker_prompt(record):
    base = (
        "Complete this Remote Labor Index project as a single self-contained HTML document with inline CSS and JavaScript. "
        "Do not use external CDNs, images, imports, placeholders, TODO comments, or explanations outside HTML. "
        "Implement real interactions, not a static mockup. Return only the complete HTML.\n\n"
        + record["brief"]
    )
    data = record.get("data")
    if data:
        base += ("\n\nUse ALL of the following official records as the sole data source. Embed them in the JavaScript data array. "
                 "Do not invent other countries or values.\n" + json.dumps(data, ensure_ascii=False))
    return base


def run_task(cl, record, emit):
    emit({"type": "activity", "text": f"RLI {record['title']}: модель создаёт HTML-доставку"})
    response = cl.chat(_worker_prompt(record), max_tokens=16000)
    html = _html(response["text"])
    static, note = _static(record, html)
    judge_prompt = (
        "You are an impartial evaluator for the Remote Labor Index. Grade only against the official brief and actual deliverable. "
        "Return strict JSON: {\"score\": number 0..100, \"reason\": \"one short sentence in Russian\"}. "
        "Rubric: 40% real functionality, 25% completeness, 15% usability, 10% visual design, 10% technical quality. "
        "Penalize placeholders, non-working interactions, missing data and superficial static layouts.\n\nOFFICIAL BRIEF:\n"
        + record["brief"] + "\n\nDELIVERABLE:\n" + html[:180000]
    )
    emit({"type": "activity", "text": f"RLI {record['title']}: проверка LLM-judge"})
    try:
        judged = cl.chat(judge_prompt, max_tokens=1200)
        data = bench.extract_json(judged["text"])
        judge_score = float(data.get("score")) / 100 if isinstance(data, dict) and data.get("score") is not None else 0.0
        reason = str(data.get("reason") or "")[:160] if isinstance(data, dict) else ""
        score = 0.3 * static + 0.7 * max(0.0, min(1.0, judge_score))
        return score, f"{note} · LLM-judge {judge_score * 100:.0f}/100" + (f" · {reason}" if reason else "")
    except Exception as e:
        return static * 0.6, f"{note} · судья недоступен: {str(e)[:80]}"
