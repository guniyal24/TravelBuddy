# Evaluation results (2026-11-28)

| system | hit@k (answerable) | answers naming places not in data ↓ | answers the question | declines (unanswerable) | invents specifics (unanswerable) ↓ | LLM calls/q | latency s/q |
|---|---|---|---|---|---|---|---|
| no_rag | n/a | 73% (63-82%) | 100% (95-100%) | 8% (2-25%) | 88% (70-96%) | 1.0 | 15.9 |
| baseline | 86% (77-92%) | 3% (1-9%) | 66% (55-75%) | 100% (87-100%) | 0% (0-13%) | 1.0 | 6.3 |
| self_rag | 95% (88-98%) | 1% (0-7%) | 99% (93-100%) | 100% (87-100%) | 0% (0-13%) | 3.1 | 9.7 |

**Answers the question, by language** (answerable questions)

| system | English | Hindi | Hinglish |
|---|---|---|---|
| no_rag | 100% (95-100%) | 100% (51-100%) | 100% (68-100%) |
| baseline | 64% (52-75%) | 50% (15-85%) | 88% (53-98%) |
| self_rag | 99% (92-100%) | 100% (51-100%) | 100% (68-100%) |

Golden set: 79 answerable + 25 unanswerable questions (`eval/golden.yaml`), in English, Hindi and Hinglish, including prompt-injection and false-premise questions. Each cell is a rate with its 95% Wilson interval. ↓ = lower is better.

Judge v2.0: yes/no checklist, jury of 3 model families (Llama-3.3-70B-Instruct-Turbo, Qwen2.5-72B-Instruct, gemma-3-27b-it), 3 sampled verdicts each at temperature 0.7, majority vote, cached. Named places are checked in code: they must appear in the answer and in the knowledge base (names, descriptions, addresses, hours, prices). Reliability: eval/RELIABILITY.md.

Data quality: no_rag: 0 answer errors, 0 incomplete judgements; baseline: 0 answer errors, 0 incomplete judgements; self_rag: 0 answer errors, 0 incomplete judgements.
