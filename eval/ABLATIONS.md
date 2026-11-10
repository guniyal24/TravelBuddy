# Ablations (2026-11-11)

Each component switched off in turn, on the same 30 trip requests (`eval/scenarios.yaml`), scored by the same code checks. A drop shows what the component prevents.

| check | full system | without the Critic | without the Food agent |
|---|---|---|---|
| reaches the approval step | 100% (89-100%) | 100% (89-100%) | 100% (57-100%) |
| every place exists in our data | 100% (89-100%) | 97% (83-99%) | 100% (57-100%) |
| exact number of days | 100% (89-100%) | 100% (89-100%) | 100% (57-100%) |
| includes every named town | 100% (88-100%) | 100% (88-100%) | 100% (57-100%) |
| named towns offered first | 100% (88-100%) | 100% (88-100%) | 100% (57-100%) |
| stops and meals in that day's town | 100% (89-100%) | 97% (83-99%) | 100% (57-100%) |
| a stay every night | 100% (89-100%) | 100% (89-100%) | 100% (57-100%) |
| veg diet respected | 100% (57-100%) | 100% (57-100%) | 60% (23-88%) |
| budget fits or is flagged | 100% (44-100%) | 100% (44-100%) | n/a |
| health note above 2,500 m | 100% (34-100%) | 100% (34-100%) | n/a |
| LLM draft valid first try | 90% (74-97%) | not checked | 80% (38-96%) |
| no rule-based fallback needed | 100% (89-100%) | not checked | 100% (57-100%) |

**Trips with at least one error a traveller would see:** full system: 0 of 30; without the Critic: 2 of 30; without the Food agent: 2 of 5.

Without the Critic the first LLM draft is accepted as it is; without the Food agent eateries are not filtered for vegetarian travellers (5 scenarios).
The answer-level ablations (no retrieval, plain RAG, Self-RAG) are in [RESULTS.md](RESULTS.md); single judge vs jury in [RELIABILITY.md](RELIABILITY.md).
