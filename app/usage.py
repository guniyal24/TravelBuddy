"""Per-trip usage metering: LLM calls, tokens and estimated cost, per model.

A trip run opens a Meter (`with metered() as m:`); every LLM call made while it is open, in
any LangGraph node, Send task or thread started with `in_context`, is added to it. LangGraph
copies context variables into its own worker threads, but a plain ThreadPoolExecutor does not,
so our pools submit through `in_context` (tested in tests/test_usage.py).

Prices are estimates in USD per 1M tokens (DeepInfra list prices as reported by public price
trackers in Nov 2026, the higher figure where they disagree). Override with MODEL_PRICES
(JSON) when they change.
"""
import contextvars
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

DEFAULT_PRICES = {  # model: (input, output) USD per 1M tokens
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506": (0.08, 0.20),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.13, 0.39),
    "Qwen/Qwen2.5-72B-Instruct": (0.36, 0.40),
    "google/gemma-3-27b-it": (0.09, 0.16),
    "meta-llama/Meta-Llama-3.1-8B-Instruct": (0.03, 0.05),
}
FALLBACK_PRICE = (0.40, 0.40)  # unknown model: assume expensive rather than free
USD_TO_INR = float(os.getenv("USD_TO_INR", "88"))


def prices() -> dict[str, tuple[float, float]]:
    raw = os.getenv("MODEL_PRICES")
    if raw:
        try:
            return {**DEFAULT_PRICES, **{k: tuple(v) for k, v in json.loads(raw).items()}}
        except (ValueError, TypeError):
            pass
    return DEFAULT_PRICES


@dataclass
class Meter:
    started: float = field(default_factory=time.monotonic)
    calls: int = 0
    by_model: dict[str, list[int]] = field(default_factory=dict)  # model: [in, out, calls]
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        with self._lock:
            self.calls += 1
            row = self.by_model.setdefault(model, [0, 0, 0])
            row[0] += prompt_tokens or 0
            row[1] += completion_tokens or 0
            row[2] += 1

    def cost_usd(self) -> float:
        table = prices()
        total = 0.0
        for model, (pin, pout, _) in self.by_model.items():
            cin, cout = table.get(model, FALLBACK_PRICE)
            total += pin / 1e6 * cin + pout / 1e6 * cout
        return total

    def summary(self) -> dict:
        usd = self.cost_usd()
        return {"llm_calls": self.calls,
                "tokens_in": sum(r[0] for r in self.by_model.values()),
                "tokens_out": sum(r[1] for r in self.by_model.values()),
                "cost_usd": round(usd, 5), "cost_inr": round(usd * USD_TO_INR, 3),
                "seconds": round(time.monotonic() - self.started, 1),
                "by_model": {m: {"tokens_in": r[0], "tokens_out": r[1], "calls": r[2]}
                             for m, r in self.by_model.items()}}


_current: contextvars.ContextVar[Meter | None] = contextvars.ContextVar("meter", default=None)


@contextmanager
def metered(meter: Meter | None = None) -> Iterator[Meter]:
    m = meter or Meter()
    token = _current.set(m)
    try:
        yield m
    finally:
        _current.reset(token)


def record(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    m = _current.get()
    if m is not None:
        m.add(model, prompt_tokens, completion_tokens)


def in_context(fn: Callable) -> Callable:
    """Bind fn to the caller's context, for executor threads (which do not inherit it).

    Each call runs in its own copy: one Context object cannot be entered by two threads at
    once, and pool.map runs calls concurrently. The copies still share the same Meter object,
    so every thread's tokens land in the trip's meter."""
    ctx = contextvars.copy_context()
    return lambda *a, **kw: ctx.copy().run(fn, *a, **kw)
