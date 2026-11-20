"""
Локальные модели: поиск запущенных серверов на компьютере (или в локальной сети)
и список их моделей. Все популярные программы отдают OpenAI-совместимый API.
"""
import ipaddress, json, urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

# название, порт, путь API, где скачать
SERVERS = [
    ("Ollama", 11434, "/v1", "ollama.com"),
    ("LM Studio", 1234, "/v1", "lmstudio.ai"),
    ("llama.cpp / LocalAI", 8080, "/v1", "github.com/ggml-org/llama.cpp"),
    ("vLLM", 8000, "/v1", "docs.vllm.ai"),
    ("Jan", 1337, "/v1", "jan.ai"),
    ("text-generation-webui", 5000, "/v1", "github.com/oobabooga/text-generation-webui"),
    ("KoboldCpp", 5001, "/v1", "github.com/LostRuins/koboldcpp"),
    ("GPT4All", 4891, "/v1", "gpt4all.io"),
    ("SGLang", 30000, "/v1", "github.com/sgl-project/sglang"),
    ("TabbyAPI / Aphrodite", 2242, "/v1", "github.com/theroyallab/tabbyAPI"),
]

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def is_local(url):
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "host.docker.internal") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private or ip.is_link_local
    except ValueError:
        return False


def urlopen(req, timeout):
    """Локальные адреса — напрямую, мимо системного прокси (иначе VPN/прокси ломают доступ к localhost)."""
    url = req.full_url if hasattr(req, "full_url") else req
    return (_NO_PROXY.open if is_local(url) else urllib.request.urlopen)(req, timeout=timeout)


def _get(url, timeout):
    with urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer local"}), timeout) as r:
        return json.loads(r.read())


def probe(host, name, port, path, site, timeout=1.5):
    base = f"http://{host}:{port}{path}"
    try:
        d = _get(base + "/models", timeout)
        models = [m.get("id") for m in d.get("data", []) if m.get("id")]
    except Exception:
        models = None
    if models is None and name == "Ollama":  # старые версии Ollama без /v1/models
        try:
            models = [m["name"] for m in _get(f"http://{host}:{port}/api/tags", timeout).get("models", [])]
        except Exception:
            return None
    if models is None:
        return None
    return {"name": name, "base_url": base, "port": port, "models": models, "site": site}


def scan(host="127.0.0.1", extra_ports=()):
    targets = list(SERVERS) + [(f"Порт {p}", int(p), "/v1", "") for p in extra_ports if str(p).isdigit()]
    with ThreadPoolExecutor(len(targets)) as ex:
        found = [r for r in ex.map(lambda t: probe(host, *t), targets) if r]
    # один порт — один сервер (8080 у llama.cpp и LocalAI общий)
    seen, out = set(), []
    for f in found:
        if f["port"] not in seen:
            seen.add(f["port"])
            out.append(f)
    return {"host": host, "found": out, "checked": [{"name": n, "port": p, "site": s} for n, p, _, s in SERVERS]}
