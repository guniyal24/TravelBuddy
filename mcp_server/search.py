"""Web search for the Concierge's travel-info agent, via the Tavily API (built for agents).

Optional: without TAVILY_API_KEY the tool reports itself unavailable and the agent is skipped.
Results are untrusted text from the open web; the caller treats them as data, cites the URL for
every claim, and verifies quotes in code (app/graph/concierge.py).
"""
import os
import threading
from datetime import date

import httpx
from dotenv import load_dotenv

load_dotenv(override=False)

API = "https://api.tavily.com/search"
MAX_SNIPPET_CHARS = 900
_lock = threading.Lock()
_usage = {"day": date.today(), "calls": 0}


def _take_quota() -> bool:
    with _lock:
        if _usage["day"] != date.today():
            _usage.update(day=date.today(), calls=0)
        if _usage["calls"] >= int(os.getenv("SEARCH_DAILY_CAP", "200")):
            return False
        _usage["calls"] += 1
        return True


def web_search(query: str, max_results: int = 5, client: httpx.Client | None = None) -> dict:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return {"available": False, "reason": "Web search is not configured."}
    if not _take_quota():
        return {"available": False, "reason": "Daily web searches are used up; try later."}
    body = {"query": query, "max_results": max(1, min(max_results, 8)),
            "search_depth": "basic", "include_answer": False, "topic": "general"}
    try:
        http = client or httpx.Client(timeout=20)
        r = http.post(API, json=body, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        results = r.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        return {"available": False, "reason": f"Web search failed ({type(exc).__name__})."}
    return {"available": True, "query": query, "results": [
        {"id": f"w{i + 1}", "title": x.get("title", ""), "url": x.get("url", ""),
         "text": " ".join((x.get("content") or "").split())[:MAX_SNIPPET_CHARS],
         "published": x.get("published_date")}
        for i, x in enumerate(results) if x.get("url")]}
