# Plan quality (2026-11-27)

30 trip requests (`eval/scenarios.yaml`), run through the real planner (town search over Pinecone town profiles, LLM-proposed circuits checked in code; LLM planner, rule-based Critic and agents; place details from the bundled graph snapshot). Every check is computed in code from the saved plan; no LLM judge. Rates with 95% Wilson intervals, over the scenarios each check applies to.

| check | pass rate | scenarios |
|---|---|---|
| reaches the approval step | 100% (89-100%) | 30 |
| every place exists in our data | 100% (89-100%) | 30 |
| exact number of days | 100% (89-100%) | 30 |
| includes every named town | 100% (88-100%) | 28 |
| named towns offered first | 100% (88-100%) | 28 |
| stops and meals in that day's town | 100% (89-100%) | 30 |
| a stay every night | 100% (89-100%) | 30 |
| veg diet respected | 100% (57-100%) | 5 |
| budget fits or is flagged | 100% (44-100%) | 3 |
| health note above 2,500 m | 100% (34-100%) | 2 |
| LLM draft valid first try | 93% (79-98%) | 30 |
| no rule-based fallback needed | 100% (89-100%) | 30 |

**Cost and time per trip** (request to a plan ready for review, before the optional hotel research):

| | median | 90th percentile |
|---|---|---|
| agent time | 19 s | 29 s |
| LLM cost | ₹0.02 ($0.0003) | ₹0.04 |
| tokens | 2,746 | 4,567 |
| LLM calls | 4 | 13 |

Cost uses the per-model prices in `app/usage.py` (estimates; USD to INR at 88).

Failures:

- p08: LLM draft valid first try
- p27: LLM draft valid first try
