# Judge reliability

Can the LLM judge in `eval/judge.py` be trusted? Two checks: does it give the same verdict when asked again (flip rate), and does it agree with a human (Cohen's kappa)? Regenerate with `python -m eval.reliability`.

<!-- flip:start -->
## Flip rate (2026-11-10)

The same 30 saved answers (mixed systems, random sample) judged 5 times, without cache. Share of answers whose verdict changed at least once. Lower is better.

| verdict | v1: one call, temperature 0 | v2: checklist jury |
|---|---|---|
| answers the question | 0% | 0% |
| declines | 0% | 0% |
| invents specifics | 3% | 3% |

v2 per checklist item:

| item | flip rate |
|---|---|
| on_topic | 23% |
| concrete | 0% |
| declines | 0% |
| specifics | 3% |

Judge v2.0; jury: Llama-3.3-70B-Instruct-Turbo, Qwen2.5-72B-Instruct, gemma-3-27b-it; 3 samples per juror at temperature 0.7. v1: Llama-3.3-70B-Instruct-Turbo. Cost: 1500 LLM calls.
<!-- flip:end -->

<!-- agreement:start -->
<!-- agreement:end -->

<!-- jury:start -->
## How many judges? (2026-11-27)

30 saved answers (all three systems, random sample) judged 5 times by each design, nothing cached. C, D and E reuse the same sampled calls, so they differ only in how votes are combined. B, C and D are averaged over the three models (or the three pairs); per-model rows are below. Lower is better everywhere except kappa.

| design | calls per answer | answers: flips | declines: flips | invents: flips | worst score swing | no verdict |
|---|---|---|---|---|---|---|
| A. 1 judge, one call, free-form (v1), temp 0 | 1 | 0% | 0% | 7% | 6.7 pts | 0% |
| B. 1 judge, checklist, one call, temp 0 | 1 | 1% | 0% | 0% | 1.1 pts | 0% |
| C. 1 judge, checklist, 3 samples, majority | 3 | 0% | 0% | 4% | 4.4 pts | 0% |
| D. 2 judges, 3 samples each, majority | 6 | 0% | 0% | 3% | 3.3 pts | 5% |
| E. 3 judges, 3 samples each, majority (v2) | 9 | 0% | 0% | 3% | 3.3 pts | 0% |

Per checklist item, flip rate:

| item | B | C | D | E |
|---|---|---|---|---|
| on_topic | 4% | 7% | 12% | 13% |
| concrete | 1% | 0% | 0% | 0% |
| declines | 0% | 0% | 0% | 0% |
| specifics | 2% | 6% | 10% | 3% |

Per model (one judge) and per pair, flip rate on any headline verdict:

| design | variant | answers | declines | invents |
|---|---|---|---|---|
| B | Llama-3.3-70B-Instruct-Turbo | 0% | 0% | 0% |
| B | Qwen2.5-72B-Instruct | 0% | 0% | 0% |
| B | gemma-3-27b-it | 3% | 0% | 0% |
| C | Llama-3.3-70B-Instruct-Turbo | 0% | 0% | 3% |
| C | Qwen2.5-72B-Instruct | 0% | 0% | 10% |
| C | gemma-3-27b-it | 0% | 0% | 0% |
| D | Llama-3.3-70B-Instruct-Turbo+Qwen2.5-72B-Instruct | 0% | 0% | 3% |
| D | Llama-3.3-70B-Instruct-Turbo+gemma-3-27b-it | 0% | 0% | 0% |
| D | Qwen2.5-72B-Instruct+gemma-3-27b-it | 0% | 0% | 7% |

Do the three jurors agree with each other? (kappa, averaged over runs; 1 = always agree, 0 = chance)

| item | Fleiss (all 3) | Llama-3.3-70B-Instruct-Turbo+Qwen2.5-72B-Instruct | Llama-3.3-70B-Instruct-Turbo+gemma-3-27b-it | Qwen2.5-72B-Instruct+gemma-3-27b-it |
|---|---|---|---|---|
| on_topic | 0.21 | 0.50 | 0.00 | 0.00 |
| concrete | 1.00 | 1.00 | 1.00 | 1.00 |
| declines | 1.00 | 1.00 | 1.00 | 1.00 |
| specifics | 0.76 | 0.67 | 0.92 | 0.69 |

Judge v2.0; jurors: Llama-3.3-70B-Instruct-Turbo, Qwen2.5-72B-Instruct, gemma-3-27b-it. 1950 LLM calls in total. Consistency is not correctness: see the human agreement section.
<!-- jury:end -->
