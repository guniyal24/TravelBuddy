"""Thin wrapper over an OpenAI-compatible chat client: JSON helper + usage counters.

`retries` adds exponential backoff for rate limits, timeouts and server errors. The API uses
the default 0 (fail fast, a traveller is waiting); batch jobs such as the evals use more.
"""
import json
import logging
import random
import re
import threading
import time

import openai

log = logging.getLogger(__name__)
RETRYABLE = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
             openai.InternalServerError)


class LLM:
    def __init__(self, client, retries: int = 0, backoff_s: float = 2.0):
        self.client = client
        self.retries, self.backoff_s = retries, backoff_s
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.retried = 0
        self._lock = threading.Lock()  # counters are shared by worker threads

    def _create(self, kwargs: dict):
        for attempt in range(self.retries + 1):
            try:
                return self.client.chat.completions.create(**kwargs)
            except RETRYABLE as exc:
                if attempt == self.retries:
                    raise
                wait = self.backoff_s * 2 ** attempt * (1 + random.random() / 2)
                log.warning("%s on %s; retry %d/%d in %.0fs", type(exc).__name__,
                            kwargs["model"], attempt + 1, self.retries, wait)
                with self._lock:
                    self.retried += 1
                time.sleep(wait)
        raise AssertionError("unreachable")

    def complete(
        self, model: str, messages: list[dict], temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        kwargs = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        resp = self._create(kwargs)
        usage = getattr(resp, "usage", None)
        with self._lock:
            self.calls += 1
            if usage:
                self.prompt_tokens += usage.prompt_tokens or 0
                self.completion_tokens += usage.completion_tokens or 0
        return (resp.choices[0].message.content or "").strip()

    def json(self, model: str, messages: list[dict], default: dict | None = None,
             max_tokens: int = 600, temperature: float = 0.0) -> dict:
        """Ask for JSON and parse the first {...} block; return `default` if unparseable.

        Output is capped (max_tokens) so a model that rambles cannot stall a request, and an
        LLM/network failure degrades to `default` instead of raising.
        """
        try:
            text = self.complete(model, messages, temperature=temperature, max_tokens=max_tokens)
        except Exception:  # timeout, rate limit, 5xx: log and let the caller use its fallback
            log.exception("LLM JSON call failed; using default")
            return default or {}
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            return json.loads(match.group(0)) if match else (default or {})
        except json.JSONDecodeError:
            log.warning("Unparseable JSON from LLM: %r", text[:200])
            return default or {}

    def snapshot(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens}
