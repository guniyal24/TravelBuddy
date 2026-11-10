# Evaluation results (2026-11-09)

| system | hit@k (answerable) | answers naming places not in data | answers the question | declines (unanswerable) | invents specifics (unanswerable) | LLM calls/q | latency s/q |
|---|---|---|---|---|---|---|---|
| no_rag | n/a | 85% | 100% | 0% | 100% | 1.0 | 27.5 |
| baseline | 95% | 0% | 55% | 100% | 0% | 1.0 | 5.3 |
| self_rag | 96% | 4% | 100% | 100% | 0% | 3.1 | 7.2 |

Golden set: 20 answerable + 5 unanswerable questions (`eval/golden.yaml`). Lower is better for 'names places not in data' and 'invents specifics'; higher is better elsewhere. Judge: LLM, temperature 0.
