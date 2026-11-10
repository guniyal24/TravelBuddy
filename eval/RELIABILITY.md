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
