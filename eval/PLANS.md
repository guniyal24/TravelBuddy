# Plan quality (2026-11-10)

30 trip requests (`eval/scenarios.yaml`), run through the real planner (LLM planner, rule-based Critic and agents). Every check is computed in code from the saved plan; no LLM judge. Rates with 95% Wilson intervals, over the scenarios each check applies to.

| check | pass rate | scenarios |
|---|---|---|
| reaches the approval step | 100% (89-100%) | 30 |
| exact number of days | 100% (89-100%) | 30 |
| includes every named town | 100% (88-100%) | 28 |
| named towns offered first | 100% (88-100%) | 28 |
| stops and meals in that day's town | 100% (89-100%) | 30 |
| a stay every night | 100% (89-100%) | 30 |
| veg diet respected | 100% (57-100%) | 5 |
| budget fits or is flagged | 100% (44-100%) | 3 |
| health note above 2,500 m | 100% (34-100%) | 2 |
| LLM draft valid first try | 90% (74-97%) | 30 |
| no rule-based fallback needed | 100% (89-100%) | 30 |

Median time to a plan ready for review: 8 s (max 22 s); LLM calls per plan: 2.6.

Failures:

- p08: LLM draft valid first try
- p22: LLM draft valid first try
- p27: LLM draft valid first try
