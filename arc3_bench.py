"""ARC-AGI-3: интерактивные среды через официальный ARC REST API без зависимостей."""
import http.cookiejar
import json
import re
import urllib.error
import urllib.request

import bench

BASE_URL = "https://arcprize.org"
MAX_ACTIONS = 20
_COOKIES = http.cookiejar.CookieJar()


def _request(method, path, api_key, payload=None):
    headers = {"X-API-Key": api_key, "Accept": "application/json", "User-Agent": "LLM-Bench/1.3"}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_COOKIES))
    try:
        with opener.open(req, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"ARC API {method} {path}: HTTP {e.code}. {body}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise RuntimeError(f"ARC API {method} {path}: {e}")


def _api_key(user_key=None):
    return user_key or _request("GET", "/api/games/anonkey", "").get("api_key", "")


def list_games(arc_api_key=None, limit=3):
    key = _api_key(arc_api_key)
    games = _request("GET", "/api/games", key)
    return [{"game_id": g.get("game_id", ""), "title": g.get("title", "")} for g in games[:limit]]


def _frame(obs):
    state = obs.get("state", "NOT_PLAYED")
    return {
        "frame": obs.get("frame") or [],
        "state": state.get("name") if isinstance(state, dict) else str(state),
        "levels_completed": obs.get("levels_completed", 0),
        "win_levels": obs.get("win_levels", 0),
        "available_actions": obs.get("available_actions") or [],
        "guid": obs.get("guid"),
    }


def _parse_action(text):
    data = bench.extract_json(text)
    if isinstance(data, dict):
        name = str(data.get("action") or data.get("name") or data.get("tool") or "").upper()
        args = data.get("data") or data.get("args") or {}
    else:
        match = re.search(r"\b(RESET|ACTION[1-7])\b", text.upper())
        name, args = (match.group(1) if match else ""), {}
    if not isinstance(args, dict):
        args = {}
    return name, args


def _score_details(scorecard, last_frame):
    official = float(scorecard.get("score", 0.0) or 0.0)
    levels, total = 0, last_frame["win_levels"]
    for environment in scorecard.get("environments", []):
        runs = environment.get("runs") or []
        if runs:
            levels = max((r.get("levels_completed", 0) for r in runs), default=levels)
            total = max((r.get("level_count", total) for r in runs), default=total)
    ratio = levels / total if total else official / 100
    return official, levels, total, ratio


def run_task(cl, game_id, emit, arc_api_key=None):
    """Играет среду через официальный API и возвращает (score 0..1, заметка)."""
    key = _api_key(arc_api_key)
    card = _request("POST", "/api/scorecard/open", key,
                    {"source_url": "https://github.com/Orsofey/llm-bench", "tags": ["llm-bench", cl.model or "model"]})
    card_id = card["card_id"]
    metadata = _request("GET", f"/api/games/{game_id}", key)
    game_id = metadata.get("game_id", game_id)
    history, actions = [], 0
    obs = _request("POST", "/api/cmd/RESET", key, {"card_id": card_id, "game_id": game_id})
    try:
        while actions < MAX_ACTIONS:
            frame = _frame(obs)
            if frame["state"] in ("WIN", "GAME_OVER"):
                break
            available = [f"ACTION{i}" for i in frame["available_actions"]]
            if not available:
                break
            prompt = (
                "You are playing an ARC-AGI-3 interactive game. Choose EXACTLY ONE next action.\n"
                "Return only JSON: {\"action\":\"ACTION1\",\"data\":{}}. For ACTION6 use coordinates "
                "{\"action\":\"ACTION6\",\"data\":{\"x\":0,\"y\":0}}.\n"
                "Available actions: " + ", ".join(available) + ".\n"
                "The grid is a 64x64 matrix of integers 0..15. Learn transitions and achieve WIN with few actions.\n"
                f"Game: {game_id}\nCurrent state: {frame['state']}\nLevels completed: {frame['levels_completed']} / {frame['win_levels']}\n"
                + ("Recent actions: " + " → ".join(history[-4:]) + "\n" if history else "")
                + "Latest frame:\n" + json.dumps(frame["frame"], ensure_ascii=False)
            )
            response = cl.chat(prompt, max_tokens=1200)
            name, args = _parse_action(response["text"])
            if name not in available:
                name = available[0]
                args = {}
            if name == "ACTION6":
                try:
                    args = {"x": int(args.get("x", 0)), "y": int(args.get("y", 0))}
                except (TypeError, ValueError):
                    args = {"x": 0, "y": 0}
            else:
                args = {}
            payload = {"game_id": game_id, "guid": frame["guid"],
                       "reasoning": json.dumps({"model": cl.model, "response": response["text"][:500]}, ensure_ascii=False)}
            if name != "RESET":
                payload.update(args)
            obs = _request("POST", f"/api/cmd/{name}", key, payload)
            actions += 1
            history.append(name)
            current = _frame(obs)
            emit({"type": "activity", "text": f"ARC-AGI-3 {game_id}: {name} · {current['levels_completed']}/{current['win_levels']} уровней · {actions}/{MAX_ACTIONS}"})
    finally:
        scorecard = _request("POST", "/api/scorecard/close", key, {"card_id": card_id})
    official, levels, total, ratio = _score_details(scorecard, _frame(obs))
    score = min(1.0, max(official / 100, ratio))
    return score, f"официальный score {official:.1f} · уровней {levels}/{total} · действий {actions} (mini cap {MAX_ACTIONS})"
