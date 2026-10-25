"""LLM access for the RAG app: Gemini (default) or Groq, through their OpenAI-compatible endpoints.

* Provider is chosen by model name ("gemini-..." -> Gemini, anything else -> Groq), so the web app, the evaluator and the
  one-off vision captioning can use different providers side by side.
* Several API keys per provider are rotated automatically on quota / overload errors.
* A model that is overloaded (503) or out of quota (429) is put on a short cooldown and the next model in the chain is
  used instead of waiting.
* Calls are paced against a rolling 60 s window (tokens and requests) kept in a small JSON file guarded by a lock file,
  so separate processes (API server, evaluator, ingestion) share one budget.
"""
from __future__ import annotations
import os, re, time, json, random
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, APIStatusError, APIConnectionError, APITimeoutError
from .common import ROOT, CACHE

load_dotenv(ROOT / ".env")


def _keys(*names: str) -> list[str]:
    return [os.environ[n].strip() for n in names if os.environ.get(n, "").strip()]


PROVIDERS = {
    "gemini": dict(base="https://generativelanguage.googleapis.com/v1beta/openai/",
                   keys=_keys("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"),
                   tpm=int(os.getenv("GEMINI_TPM", "200000")), rpm=int(os.getenv("GEMINI_RPM", "10")),
                   default="gemini-flash-lite-latest", fallbacks=["gemini-3.1-flash-lite", "gemini-3.5-flash"],
                   timeout=40),
    "groq": dict(base="https://api.groq.com/openai/v1", keys=_keys("GROQ_API_KEY"),
                 tpm=int(os.getenv("GROQ_TPM", "8000")), rpm=None,
                 default="openai/gpt-oss-120b", fallbacks=["openai/gpt-oss-20b", "qwen/qwen3.8-27b"], timeout=45),
}
PROVIDER = os.getenv("LLM_PROVIDER") or ("gemini" if PROVIDERS["gemini"]["keys"] else "groq")
GEMINI_MODELS = ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-flash-latest"]


def provider_of(model: str) -> str:
    return "gemini" if model.startswith("gemini") else "groq"


_env_model = os.getenv("LLM_MODEL", "")
LLM_MODEL = _env_model if _env_model and provider_of(_env_model) == PROVIDER else PROVIDERS[PROVIDER]["default"]
_fb_env = os.getenv("LLM_FALLBACKS")
LLM_FALLBACKS = [m.strip() for m in _fb_env.split(",") if m.strip()] if _fb_env is not None else PROVIDERS[PROVIDER]["fallbacks"]
VISION_MODEL = os.getenv("VISION_MODEL", "qwen/qwen3.8-27b")
LAST_MODEL = ""                                        # model that produced the most recent answer


class LLMUnavailable(RuntimeError):
    """No model could answer right now (overloaded / rate-limited / out of quota); the caller may retry later."""


_clients: dict = {}
_cool: dict = {}                                       # (provider, key index, model) -> time when usable again


def _client(prov: str, key_idx: int) -> OpenAI:
    k = (prov, key_idx)
    if k not in _clients:
        from openai import DefaultHttpxClient, _base_client
        h = _base_client.httpx2                        # the HTTP library the OpenAI SDK is built on
        cfg = PROVIDERS[prov]
        # No keep-alive reuse and a bounded timeout: a bad pooled connection must fail fast, not hang.
        http = DefaultHttpxClient(limits=h.Limits(max_keepalive_connections=0), timeout=h.Timeout(cfg["timeout"], connect=10))
        _clients[k] = OpenAI(api_key=cfg["keys"][key_idx], base_url=cfg["base"], http_client=http, max_retries=0)
    return _clients[k]


# ---------------------------------------------------------------- shared rolling budget (tokens + requests)
_WINDOW = CACHE / "tpm_window.json"
_LOCK = CACHE / "tpm_window.lock"


class _FileLock:
    def __enter__(self):
        CACHE.mkdir(exist_ok=True)
        deadline = time.time() + 10
        while True:
            try:
                self.fd = os.open(_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:                                    # stale lock from a crashed process
                    if time.time() - _LOCK.stat().st_mtime > 5:
                        _LOCK.unlink()
                except OSError:
                    pass
                if time.time() > deadline:
                    self.fd = None
                    return self                         # give up on locking rather than block forever
                time.sleep(0.05)

    def __exit__(self, *a):
        try:
            if self.fd is not None:
                os.close(self.fd)
                _LOCK.unlink()
        except Exception:
            pass


def _acquire(prov: str, key_idx: int, model: str, tokens: int, max_wait: float | None = None):
    """Block until the call fits the rolling 60 s token and request budget (or raise if the wait would exceed max_wait)."""
    cfg = PROVIDERS[prov]
    tpm_budget = int(cfg["tpm"] * 0.9)
    rpm_budget = max(1, int(cfg["rpm"] * 0.9)) if cfg["rpm"] else None
    tokens = min(tokens, tpm_budget)
    bucket = f"{prov}:{key_idx}:{model}"
    waited = 0.0
    while True:
        wait = 0.0
        with _FileLock():
            now = time.time()
            try:
                entries = [e for e in json.loads(_WINDOW.read_text()) if now - e[0] < 60]
            except Exception:
                entries = []
            mine = [e for e in entries if e[1] == bucket]
            fits_tokens = sum(e[2] for e in mine) + tokens <= tpm_budget
            fits_requests = rpm_budget is None or len(mine) < rpm_budget
            if fits_tokens and fits_requests:
                entries.append([now, bucket, tokens])
                _WINDOW.write_text(json.dumps(entries))
                return now, bucket
            wait = 60 - (now - min(e[0] for e in mine)) + 0.2
        if max_wait is not None and waited + wait > max_wait:
            raise LLMUnavailable(f"The model is at its rate limit. Try again in about {int(wait) + 1} seconds.")
        time.sleep(max(0.3, wait))
        waited += max(0.3, wait)


def _settle(stamp: float, bucket: str, actual: int):
    """Replace the up-front estimate with what the call really used, freeing budget for the next request."""
    with _FileLock():
        try:
            entries = json.loads(_WINDOW.read_text())
            for e in entries:
                if e[0] == stamp and e[1] == bucket:
                    e[2] = actual
            _WINDOW.write_text(json.dumps(entries))
        except Exception:
            pass


def _log_error(model: str, e: Exception):
    """Keep the provider's real error message: 'rate-limited' alone hides which limit was hit."""
    try:
        h = getattr(getattr(e, "response", None), "headers", {}) or {}
        info = {k: v for k, v in h.items() if "ratelimit" in k.lower() or k.lower() == "retry-after"}
        with open(CACHE / "llm_errors.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "model": model, "err": type(e).__name__, "msg": str(e)[:400], "headers": info}) + "\n")
    except Exception:
        pass


def _estimate_tokens(messages, max_tokens: int) -> int:
    chars = 0
    for m in messages:
        c = m["content"]
        chars += len(c) if isinstance(c, str) else sum(len(p.get("text", "")) + (1200 if p.get("type") == "image_url" else 0) for p in c)
    return int(chars / 3.6) + max_tokens


def _is_thinking(model: str) -> bool:
    """Gemini non-lite models 'think' first; their hidden tokens count against max_tokens."""
    return model.startswith("gemini") and "lite" not in model


def available_models() -> list[str]:
    return GEMINI_MODELS if PROVIDER == "gemini" else [LLM_MODEL] + LLM_FALLBACKS


def chat(messages, model: str | None = None, max_tokens: int = 900, temperature: float = 0.0,
         reasoning_effort: str | None = None, retries: int = 6, max_wait: float | None = None,
         fallbacks: list[str] | None = None) -> str:
    """One completion. `model` is tried first, then the fallbacks; every model is tried with every API key."""
    global LAST_MODEL
    if max_wait is not None:                            # interactive call: fail fast instead of retrying for minutes
        retries = min(retries, 3)
    first = model or LLM_MODEL
    chain = [first] + [m for m in (LLM_FALLBACKS if fallbacks is None else fallbacks) if m != first]
    attempt = 0
    boost = 1
    while attempt < retries:
        now = time.time()
        combos = [(m, k) for m in chain for k in range(len(PROVIDERS[provider_of(m)]["keys"]))
                  if _cool.get((provider_of(m), k, m), 0) < now]
        if not combos:
            soon = min((v for v in _cool.values() if v > now), default=now + 30) - now
            if max_wait is not None or attempt + 1 >= retries:
                raise LLMUnavailable(f"All models are busy or at their quota right now. Try again in about {int(soon) + 1} seconds.")
            attempt += 1
            time.sleep(min(30, soon + 0.5))
            continue
        cur, key_idx = combos[0]
        prov = provider_of(cur)
        kw = {}
        mt = max_tokens * boost
        if prov == "groq" and reasoning_effort and cur.startswith("openai/gpt-oss"):
            kw["extra_body"] = {"reasoning_effort": reasoning_effort}
        if _is_thinking(cur):
            kw["reasoning_effort"] = "low"
            mt += 1500                                  # room for the hidden thinking tokens
        stamp, bucket = _acquire(prov, key_idx, cur, _estimate_tokens(messages, mt), max_wait)
        try:
            r = _client(prov, key_idx).chat.completions.create(model=cur, messages=messages, max_tokens=mt,
                                                               temperature=temperature, **kw)
            if getattr(r, "usage", None) and r.usage.total_tokens:
                _settle(stamp, bucket, int(r.usage.total_tokens))
            text = (r.choices[0].message.content or "").strip()
            if not text and r.choices[0].finish_reason == "length":
                boost *= 2                              # truncated before any answer text: retry with more room
                attempt += 1
                continue
            LAST_MODEL = cur
            return text
        except RateLimitError as e:
            _log_error(cur, e)
            msg = str(e)
            per_day = "tokens per day" in msg or "(TPD)" in msg or "PerDay" in msg or "per day" in msg.lower()
            _cool[(prov, key_idx, cur)] = time.time() + (600 if per_day else 60)    # next key / model takes over
        except APIStatusError as e:
            _log_error(cur, e)
            if e.status_code in (500, 502, 503, 504):
                _cool[(prov, key_idx, cur)] = time.time() + 30                      # overloaded: try another model/key
                attempt += 1
            elif e.status_code in (401, 403):
                _cool[(prov, key_idx, cur)] = time.time() + 3600                    # bad / disabled key
            else:
                raise
        except (APIConnectionError, APITimeoutError) as e:
            _log_error(cur, e)
            _cool[(prov, key_idx, cur)] = time.time() + 20
            attempt += 1
    raise LLMUnavailable("The language model is busy or unreachable right now. Please try again shortly.")
