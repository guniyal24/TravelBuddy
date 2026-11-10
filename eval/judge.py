"""LLM-as-judge, two versions.

v1  one call to one model at temperature 0, filling several fields at once. Kept so its
    instability can be measured against v2 (eval/reliability.py).

v2  built from what the literature found to reduce judge variance and bias:
    * code first: anything checkable in code is (is a named place really in the answer? is it
      in our knowledge base?); the LLM judges only what code cannot
    * yes/no checklist items instead of open fields or scores (CheckEval, TICK)
    * reasoning before the verdict, several sampled verdicts per juror, majority vote
      (Wang et al., "Large Language Models are not Fair Evaluators": multiple evidence
      calibration)
    * a jury of three model families, majority vote (Verga et al., "Replacing Judges with
      Juries"); none from the generator's family, to avoid self-preference
    * pinned versions and a verdict cache keyed by (model, prompt version, input, sample),
      so re-running an eval reproduces it exactly even though models are not deterministic at
      temperature 0 (Atil et al., "Non-Determinism of 'Deterministic' LLM Settings")

Every verdict keeps its votes, so low-agreement items can be sent to a human.
"""
import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

from ingest.osm import normalize

JUDGE_VERSION = "v2.0"
CACHE_PATH = Path(__file__).resolve().parent / "results" / "judge_cache.sqlite"

# ---------------------------------------------------------------- v1 (baseline)
JUDGE_V1_SYSTEM = (
    "You evaluate a travel assistant's ANSWER to a QUESTION about Uttarakhand. Return JSON "
    'only: {"answers_question": bool, "declines": bool, "invents_specifics": bool, '
    '"named_places": [str]}. answers_question: the answer gives useful, on-topic content. '
    "declines: the answer says it lacks the information / cannot confirm. invents_specifics: "
    "the answer states specific names, prices, fares, timings or fees as fact. named_places: "
    "every specific hotel, restaurant, temple, ashram, attraction or dish named in the answer "
    "(NOT cities, rivers, states or generic words)."
)

# ---------------------------------------------------------------- v2 checklist
CHECKLIST = {
    "on_topic": "Is the ANSWER about what the QUESTION asks (the same place and the same "
                "topic), rather than about something else?",
    "concrete": "Does the ANSWER give concrete information that helps with this QUESTION, "
                "for example a named place, what it is, or how to get there?",
    "declines": "Does the ANSWER say that it does not have, or cannot confirm, the main "
                "information the QUESTION asks for?",
    "specifics": "Does the ANSWER state a specific price, fare, fee, phone number, date, "
                 "opening time or timetable as a fact?",
}
ITEMS = tuple(CHECKLIST)

JUDGE_V2_SYSTEM = (
    "You check a travel assistant's ANSWER to a traveller's QUESTION about Uttarakhand, India. "
    "The ANSWER may be in English, Hindi or Hinglish; judge it by meaning. Answer each "
    "checklist question with \"yes\" or \"no\" only, judging only what the ANSWER says (do not "
    "use your own knowledge of whether it is true). Think first, briefly.\n\nCHECKLIST:\n"
    + "\n".join(f"- {k}: {v}" for k, v in CHECKLIST.items())
    + "\n- named_places: list every specific hotel, restaurant, cafe, temple, ashram, "
    "attraction, trek or dish the ANSWER names, copied exactly as written (not towns, rivers, "
    "states or generic words like \"the market\").\n\n"
    'Return JSON only: {"reasoning": "<one or two sentences>", '
    + ", ".join(f'"{k}": "yes|no"' for k in ITEMS)
    + ', "named_places": ["..."]}'
)
PROMPT_HASH = hashlib.sha256(JUDGE_V2_SYSTEM.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- knowledge base checks
def in_kb(place: str, kb: dict) -> bool:
    """Is a named place in our data: an entity name (fuzzy) or mentioned in a description."""
    p = normalize(place)
    if not p:
        return True  # nothing meaningful to check
    if f" {p} " in kb["text"]:
        return True
    for n in kb["names"]:
        if p == n or SequenceMatcher(None, p, n).ratio() >= 0.85:
            return True
        if min(len(p), len(n)) >= 5 and (p in n or n in p):
            return True
    return False


def appears_in(name: str, answer: str) -> bool:
    """Code check on the judge: a 'named place' must actually be in the answer text. Stops a
    juror's hallucinated extraction from counting as an ungrounded place."""
    n, a = normalize(name), " " + normalize(answer) + " "
    if not n:
        return False
    if f" {n} " in a:
        return True
    words = a.split()
    size = len(n.split())
    return any(SequenceMatcher(None, n, " ".join(words[i:i + size])).ratio() >= 0.85
               for i in range(max(0, len(words) - size + 1)))


# ---------------------------------------------------------------- cache
class VerdictCache:
    """Raw juror verdicts on disk, keyed by everything that determines them."""

    def __init__(self, path: Path | str | None = CACHE_PATH):
        self._lock = threading.Lock()
        self._db = None
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(path), check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS v (k TEXT PRIMARY KEY, data TEXT)")

    @staticmethod
    def key(*parts) -> str:
        return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        if self._db is None:
            return None
        with self._lock:
            row = self._db.execute("SELECT data FROM v WHERE k=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, data: dict) -> None:
        if self._db is None:
            return
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO v VALUES (?, ?)", (key, json.dumps(data)))


# ---------------------------------------------------------------- judges
def _yes(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v.startswith("yes"):
            return True
        if v.startswith("no"):
            return False
    return None


def _majority(votes: list[bool | None]) -> bool | None:
    valid = [v for v in votes if v is not None]
    if not valid:
        return None
    yes = sum(valid)
    return yes * 2 > len(valid) if yes * 2 != len(valid) else None  # a tie is no verdict


def _derive(items: dict, ungrounded: list[str]) -> dict:
    """The headline metrics, from checklist items plus code checks."""
    declines = bool(items["declines"])
    return {
        "answers_question": bool(items["on_topic"]) and bool(items["concrete"]),
        "declines": declines,
        "invents": (bool(items["specifics"]) or bool(ungrounded)) and not declines,
    }


def judge_v1(llm, model: str, question: str, answer: str, kb: dict) -> dict:
    user = f"QUESTION: {question}\n\nANSWER: {answer}"
    res = llm.json(model, [{"role": "system", "content": JUDGE_V1_SYSTEM},
                           {"role": "user", "content": user}], default={})
    places = [p for p in (res.get("named_places") or []) if isinstance(p, str)]
    ungrounded = [p for p in places if not in_kb(p, kb)]
    return {"answers_question": bool(res.get("answers_question")),
            "declines": bool(res.get("declines")),
            "invents": bool(res.get("invents_specifics")) and not bool(res.get("declines")),
            "specifics": bool(res.get("invents_specifics")),
            "named_places": places, "ungrounded_places": ungrounded, "version": "v1"}


class JuryJudge:
    def __init__(self, llm, jury: list[str], samples: int = 3, temperature: float = 0.7,
                 cache: VerdictCache | None = None, workers: int = 3):
        self.llm, self.jury, self.samples, self.temperature = llm, jury, samples, temperature
        self.cache = cache if cache is not None else VerdictCache(None)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="juror")

    def _one(self, model: str, sample: int, question: str, answer: str) -> dict:
        key = VerdictCache.key(JUDGE_VERSION, PROMPT_HASH, model, self.temperature, sample,
                               question, answer)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        raw = self.llm.json(model, [
            {"role": "system", "content": JUDGE_V2_SYSTEM},
            {"role": "user", "content": f"QUESTION: {question}\n\nANSWER: {answer}"}],
            default={}, max_tokens=500, temperature=self.temperature)
        verdict = {k: _yes(raw.get(k)) for k in ITEMS}
        verdict["named_places"] = [p for p in (raw.get("named_places") or [])
                                   if isinstance(p, str)][:30]
        if any(verdict[k] is not None for k in ITEMS):  # do not cache a failed call
            self.cache.put(key, verdict)
        return verdict

    def __call__(self, question: str, answer: str, kb: dict) -> dict:
        jobs = {(m, s): self._pool.submit(self._one, m, s, question, answer)
                for m in self.jury for s in range(self.samples)}
        raw = {k: f.result() for k, f in jobs.items()}
        items, votes, agreement = {}, {}, {}
        for item in ITEMS:
            per_juror = {m: _majority([raw[(m, s)][item] for s in range(self.samples)])
                         for m in self.jury}
            final = _majority(list(per_juror.values()))
            all_votes = [raw[(m, s)][item] for m in self.jury for s in range(self.samples)]
            valid = [v for v in all_votes if v is not None]
            items[item] = bool(final)
            votes[item] = per_juror
            agreement[item] = sum(v == bool(final) for v in valid) / len(valid) if valid else 0.0
        # Names: union over every sample, but only names that really occur in the answer.
        seen, places = set(), []
        for v in raw.values():
            for p in v["named_places"]:
                key = normalize(p)
                if key and key not in seen and appears_in(p, answer):
                    seen.add(key)
                    places.append(p)
        ungrounded = [p for p in places if not in_kb(p, kb)]
        failed = sum(1 for verdict in raw.values() if all(verdict[i] is None for i in ITEMS))
        return {**_derive(items, ungrounded), "items": items, "votes": votes,
                "agreement": agreement, "named_places": places,
                "ungrounded_places": ungrounded, "version": JUDGE_VERSION,
                "failed_calls": failed, "complete": failed == 0}
