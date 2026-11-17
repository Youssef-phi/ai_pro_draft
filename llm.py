"""One LLM client for every agent.

Fallback chain: Hack Club AI -> NVIDIA Build -> local Ollama (always last, needs no key).
Only allow-listed open-weight models are called. Every call returns the real model,
provider, token counts and cost so the decision log can record them.

Rules the client enforces:
  * 402 (provider daily limit) -> fall back and tell the founder.
  * 429 -> honour Retry-After, then fall back.
  * 403 -> stop and tell the founder; never retried.
  * Our own daily budget cap stops metered spending before the provider does.
The API key is sent only in the Authorization header to the provider. It is never
logged, never written to disk and never sent to the browser.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

import config


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    pass


class ProviderForbidden(LLMError):
    pass


class ModelNotAllowed(LLMError):
    pass


@dataclass
class LLMResult:
    data: dict
    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    cost_estimated: bool = False


def extract_json(text: str) -> dict:
    """Pull one JSON object out of a model reply (tolerates code fences and think blocks)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model reply contained no JSON object")
        obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("model reply was not a JSON object")
    return obj


class Budget:
    """Running total of metered spend for the current UTC day (Hack Club resets at 00:00 UTC)."""

    def __init__(self, path: Path, cap: float):
        self.path, self.cap, self._lock = path, cap, threading.Lock()

    @staticmethod
    def _today() -> str:
        return dt.datetime.now(dt.timezone.utc).date().isoformat()

    def spent(self) -> float:
        try:
            state = json.loads(self.path.read_text())
            return float(state["spent"]) if state.get("date") == self._today() else 0.0
        except (OSError, ValueError, KeyError):
            return 0.0

    def add(self, usd: float) -> None:
        with self._lock:
            total = self.spent() + usd
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"date": self._today(), "spent": round(total, 6)}))

    def remaining(self) -> float:
        return self.cap - self.spent()


class LLMClient:
    def __init__(self, notify: Callable[[str, str], None] | None = None, http: httpx.Client | None = None):
        self.cfg = config.llm_settings()
        self.primary: str = self.cfg["primary"]
        self.notify = notify or (lambda level, message: None)
        self.http = http or httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0))
        self.budget = Budget(config.ROOT / "data" / "budget.json", self.cfg["daily_budget"])
        self._last_call: dict[str, float] = {}
        self._disabled: dict[str, str] = {}
        self._catalog: dict | None = None
        self._lock = threading.Lock()

    # ---- public -------------------------------------------------------------
    def describe(self) -> dict:
        """Safe to show in the UI: provider names and models only, never keys."""
        return {
            "primary": self.primary,
            "chain": [p for p in self.cfg["chain"] if p not in self._disabled],
            "models": {r: config.model_for(self.primary, r, self.primary)
                       for r in ("orchestrator", "researcher", "advocate", "critic", "chair")},
            "budget_cap_usd": self.budget.cap,
            "budget_spent_today_usd": round(self.budget.spent(), 4),
        }

    def chat_json(self, role: str, system: str, user: str, max_tokens: int = 1800,
                  temperature: float = 0.4) -> LLMResult:
        errors: list[str] = []
        for provider in self.cfg["chain"]:
            if provider in self._disabled:
                errors.append(f"{provider}: {self._disabled[provider]}")
                continue
            model = config.model_for(provider, role, self.primary)
            try:
                self._check_allowed(provider, model)
                if self.cfg["providers"][provider]["metered"] and self.budget.remaining() <= 0:
                    raise BudgetExceeded(f"our daily budget cap of ${self.budget.cap:.2f} is used up")
                return self._call(provider, model, system, user, max_tokens, temperature)
            except ProviderForbidden as exc:
                self._disabled[provider] = str(exc)
                self.notify("error", f"{provider} refused access (403). Stopping; not retrying. "
                                     "Check the key or account at the provider.")
                raise
            except BudgetExceeded as exc:
                self._disabled[provider] = str(exc)
                self.notify("warning", f"{provider}: {exc}. Falling back to the next free provider.")
                errors.append(f"{provider}: {exc}")
            except (LLMError, httpx.HTTPError, ValueError) as exc:
                self.notify("warning", f"{provider} ({model}) failed: {exc}. Trying the next provider.")
                errors.append(f"{provider}: {exc}")
        raise LLMError("All model providers failed: " + " | ".join(errors))

    # ---- internals ----------------------------------------------------------
    def _check_allowed(self, provider: str, model: str) -> None:
        if config.is_blocked(model):
            raise ModelNotAllowed(f"{model} is blocked (closed weights or expiring)")
        if model not in config.allowed_models(provider):
            raise ModelNotAllowed(f"{model} is not on the open-weight allow-list for {provider}")
        if provider == "hackclub":
            entry = self._hackclub_catalog().get(model)
            if entry is not None and not entry.get("hugging_face_id"):
                raise ModelNotAllowed(f"{model} has no hugging_face_id in the catalog (not open-weight)")

    def _hackclub_catalog(self) -> dict:
        if self._catalog is None:
            p = self.cfg["providers"]["hackclub"]
            try:
                r = self.http.get(p["base_url"] + "/models", timeout=15.0,
                                  headers={"Authorization": f"Bearer {p['key']}"} if p["key"] else {})
                items = r.json().get("data", []) if r.status_code == 200 else []
                self._catalog = {m["id"]: m for m in items if isinstance(m, dict) and "id" in m}
            except (httpx.HTTPError, ValueError):
                self._catalog = {}
        return self._catalog

    def _price(self, provider: str, model: str) -> tuple[float, float, bool]:
        """USD per 1M tokens (input, output) and whether the figure is an estimate."""
        if provider == "hackclub":
            pricing = (self._hackclub_catalog().get(model) or {}).get("pricing") or {}
            try:
                return float(pricing["prompt"]) * 1e6, float(pricing["completion"]) * 1e6, False
            except (KeyError, TypeError, ValueError):
                pass
        static = config.allowed_models(provider).get(model, {})
        pin, pout = static.get("in"), static.get("out")
        estimated = pin is None or pout is None
        return (config.FALLBACK_PRICE if pin is None else pin,
                config.FALLBACK_PRICE if pout is None else pout, estimated)

    def _throttle(self, provider: str) -> None:
        rpm = self.cfg["providers"][provider]["rpm"]
        if not rpm:
            return
        with self._lock:
            wait = self._last_call.get(provider, 0.0) + 60.0 / rpm - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call[provider] = time.monotonic()

    def _call(self, provider: str, model: str, system: str, user: str,
              max_tokens: int, temperature: float) -> LLMResult:
        reminder = ""
        last_error = "no attempt made"
        for attempt in range(3):
            self._throttle(provider)
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user + reminder}]
            if provider == "ollama":
                status, body, headers = self._post_ollama(model, messages, max_tokens, temperature)
            else:
                status, body, headers = self._post_openai(provider, model, messages, max_tokens, temperature)
            if status == 200:
                text, tin, tout = self._read(provider, body)
                try:
                    data = extract_json(text)
                except ValueError as exc:
                    last_error = str(exc)
                    reminder = "\n\nReply with ONE valid JSON object only. No prose, no code fences."
                    continue
                pin, pout, estimated = self._price(provider, model)
                cost = (tin * pin + tout * pout) / 1e6
                if self.cfg["providers"][provider]["metered"]:
                    self.budget.add(cost)
                return LLMResult(data, text, model, provider, tin, tout, cost, estimated)
            if status == 402:
                raise BudgetExceeded("the provider's daily spending limit is reached (402)")
            if status == 403:
                raise ProviderForbidden(f"{provider} returned 403")
            if status == 429:
                try:
                    retry_after = float(headers.get("retry-after", "5"))
                except ValueError:
                    retry_after = 5.0
                if retry_after > 30:
                    raise LLMError(f"rate limited; Retry-After is {retry_after:.0f}s")
                time.sleep(retry_after)
                last_error = "rate limited (429)"
                continue
            if status == 404 and provider == "ollama":
                raise LLMError(f"local model {model} is not downloaded yet (the first `docker compose up` "
                               "pulls it; wait for the model-pull job to finish)")
            if status >= 500:
                time.sleep(2 ** attempt)
                last_error = f"server error {status}"
                continue
            raise LLMError(f"HTTP {status}: {str(body)[:200]}")
        raise LLMError(f"gave up after 3 attempts: {last_error}")

    def _post_openai(self, provider, model, messages, max_tokens, temperature):
        p = self.cfg["providers"][provider]
        payload = {"model": model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
        headers = {"Authorization": f"Bearer {p['key']}"}
        r = self.http.post(p["base_url"] + "/chat/completions", json=payload, headers=headers)
        if r.status_code == 400 and "response_format" in r.text:
            payload.pop("response_format")
            r = self.http.post(p["base_url"] + "/chat/completions", json=payload, headers=headers)
        return r.status_code, self._body(r), r.headers

    def _post_ollama(self, model, messages, max_tokens, temperature):
        base = self.cfg["providers"]["ollama"]["base_url"].rstrip("/")
        payload = {"model": model, "messages": messages, "stream": False, "format": "json", "think": False,
                   "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 8192}}
        r = self.http.post(base + "/api/chat", json=payload)
        if r.status_code == 400 and "think" in r.text:
            payload.pop("think")
            r = self.http.post(base + "/api/chat", json=payload)
        return r.status_code, self._body(r), r.headers

    @staticmethod
    def _body(r: httpx.Response):
        try:
            return r.json()
        except ValueError:
            return r.text

    @staticmethod
    def _read(provider: str, body) -> tuple[str, int, int]:
        if not isinstance(body, dict):
            return str(body), 0, 0
        if provider == "ollama":
            return ((body.get("message") or {}).get("content", ""),
                    int(body.get("prompt_eval_count") or 0), int(body.get("eval_count") or 0))
        usage = body.get("usage") or {}
        choices = body.get("choices") or [{}]
        return ((choices[0].get("message") or {}).get("content") or "",
                int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
