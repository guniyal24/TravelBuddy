# Evaluation results (2026-11-10)

| system | hit@k (answerable) | answers naming places not in data ↓ | answers the question | declines (unanswerable) | invents specifics (unanswerable) ↓ | LLM calls/q | latency s/q |
|---|---|---|---|---|---|---|---|
| no_rag | n/a | 73% (63-82%) | 100% (95-100%) | 16% (6-35%) | 80% (61-91%) | 1.0 | 19.6 |
| baseline | 87% (78-93%) | 0% (0-5%) | 59% (48-70%) | 100% (87-100%) | 0% (0-13%) | 1.0 | 5.7 |
| self_rag | 96% (89-99%) | 1% (0-7%) | 97% (91-99%) | 100% (87-100%) | 0% (0-13%) | 3.1 | 7.9 |

**Answers the question, by language** (answerable questions)

| system | English | Hindi | Hinglish |
|---|---|---|---|
| no_rag | 100% (95-100%) | 100% (51-100%) | 100% (68-100%) |
| baseline | 61% (49-72%) | 25% (5-70%) | 62% (31-86%) |
| self_rag | 99% (92-100%) | 100% (51-100%) | 88% (53-98%) |

Golden set: 79 answerable + 25 unanswerable questions (`eval/golden.yaml`), in English, Hindi and Hinglish, including prompt-injection and false-premise questions. Each cell is a rate with its 95% Wilson interval. ↓ = lower is better.

Judge v2.0: yes/no checklist, jury of 3 model families (Llama-3.3-70B-Instruct-Turbo, Qwen2.5-72B-Instruct, gemma-3-27b-it), 3 sampled verdicts each at temperature 0.7, majority vote, cached. Named places are checked in code: they must appear in the answer and in the knowledge base (names, descriptions, addresses, hours, prices). Reliability: eval/RELIABILITY.md.

Data quality: no_rag: 0 answer errors, 0 incomplete judgements; baseline: 0 answer errors, 0 incomplete judgements; self_rag: 0 answer errors, 0 incomplete judgements.
