"""Thin wrapper over an OpenAI-compatible chat client: JSON helper + usage counters."""
import json
import logging
import re

log = logging.getLogger(__name__)


class LLM:
    def __init__(self, client):
        self.client = client
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def complete(
        self, model: str, messages: list[dict], temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        kwargs = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        resp = self.client.chat.completions.create(**kwargs)
        self.calls += 1
        usage = getattr(resp, "usage", None)
        if usage:
            self.prompt_tokens += usage.prompt_tokens or 0
            self.completion_tokens += usage.completion_tokens or 0
        return (resp.choices[0].message.content or "").strip()

    def json(self, model: str, messages: list[dict], default: dict | None = None,
             max_tokens: int = 600) -> dict:
        """Ask for JSON and parse the first {...} block; return `default` if unparseable.

        Output is capped (max_tokens) so a model that rambles cannot stall a request, and an
        LLM/network failure degrades to `default` instead of raising.
        """
        try:
            text = self.complete(model, messages, temperature=0.0, max_tokens=max_tokens)
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
