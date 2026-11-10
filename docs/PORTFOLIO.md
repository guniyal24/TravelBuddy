# Portfolio kit

Everything here is backed by a file in this repository; the numbers come from the reports in
`eval/` and can be regenerated with the commands in [`eval/README.md`](../eval/README.md).

## Resume bullets

Pick three or four; each one has a number a recruiter can check.

- Built **TravelBuddy**, a multi-agent trip planner for Uttarakhand (LangGraph, MCP, Self-RAG,
  Neo4j, Pinecone, FastAPI, React) with human approval at every decision and a live trace of
  each agent's work.
- Cut hallucination with **Self-RAG**: on a 104-question bilingual benchmark, a plain LLM named
  places outside the data in **73%** of answers and invented specifics in **80%** of
  unanswerable ones; Self-RAG: **1% and 0%**, while answering **97%** of answerable questions
  (plain RAG: 59%).
- Paired an LLM planner with a **rule-based Critic**: **100%** of 30 test trips pass every code
  check (right days, towns, meals in the right town, stays, diet, budget, altitude notes);
  ablation: without it **2 of 30** trips reach the traveller with an error (invented place,
  wrong-town meal); without the Food agent **2 of 5** vegetarian trips include meat.
- Built an **LLM-as-judge** grounded in the literature (yes/no checklists, a three-family jury,
  majority voting, verdict caching, code-verified claims) and measured its stability: headline
  verdicts flip on **0–3%** of answers across repeated runs.
- Added a **parallel hotel-research stage** (LangGraph `Send` fan-out, Google reviews over MCP):
  every review claim must quote its source word for word, checked in code (**92%** pass across
  26 towns); ranking is code, so prompt injection in a review cannot promote a hotel.
- Grew the knowledge base from **333 to 721 places in 26 towns** with an OpenStreetMap pipeline;
  calibrated OSRM road times against hand-checked routes (distances within **4%**, times
  ×1.5–2.1 for hill roads).
- Production hardening: per-trip cost metering (**₹0.01** median LLM cost, **17 s** median),
  **13/13** red-team attacks defended in CI, Postgres-backed durable state, long-term memory on
  a LangGraph store, 250+ tests.

## Talking points (likely interview questions)

**Why not just use one big prompt?** The LLM is good at composing a plan and bad at
guaranteeing it is valid. So the LLM drafts from candidate ids only, and deterministic code
(the Critic) rejects unknown places, missing stays, wrong-town meals and overloaded days. It
retries with the Critic's errors, and a rule-based plan is the last resort. Switched off, 2 of
30 trips reached the traveller with an error; with it, none.

**How do you know the evaluation is right?** I measured the judge itself. Two findings I would
mention: the first grounding metric reported 15% "places not in data" for Self-RAG, but every
flagged name was an address from our own listings; the metric was wrong, not the model
(fixed: 1%). And the judge's `on_topic` item flips on 23% of re-runs, all on polite declines, a
rubric ambiguity; the headline metric does not use it alone.

**What broke in production-like testing?**
1. A slow vector store made the planner return an empty plan, because "search failed" looked
   like "nothing found". Now searches retry and an outage stops planning with a clear message.
2. Parallel translation reused one Python `Context` across threads, which crashes when calls
   overlap. Unit tests missed it because fakes are instant; a benchmark with real latency found
   it. There is now a test that forces overlap.

**How do you handle untrusted text (reviews, web pages)?** It goes to the LLM only inside a
delimited block marked as data, the LLM can only fill a fixed JSON shape, every quote is checked
against its source in code, and ranking never uses LLM text.

**What would you do next?** Collect human labels and report Cohen's kappa for the judge;
tighten the `on_topic` rubric; deploy and measure real usage (approval rate, edits per plan).

## Two-minute demo script

| time | show | say |
|---|---|---|
| 0:00 | landing page | "LLMs plan trips confidently and wrongly. This one shows its work." |
| 0:10 | click **Try it now**, type "Kausani and Almora, 3 days from next Friday, vegetarian" | "No sign-up. Plain language, Hindi works too." |
| 0:20 | live agent trace | "Intake, advisor, research, parallel specialists, the LLM planner, then a rule-based Critic that can reject the draft. Real data only." |
| 0:45 | choose the circuit, review the plan, open Timeline and Map | "Real dates, a live forecast per day, road times calibrated for hill roads, safety notes." |
| 1:05 | approve; hotel agents run in parallel; open a hotel card | "Agents read Google reviews; every pro and con quotes a real reviewer, verified in code." |
| 1:25 | pick a hotel; the cost updates; show the trace footer | "Planning this trip cost about one paisa in LLM fees." |
| 1:35 | Preferences, **What I remember** | "It remembers what I said, with my exact words, and I can delete it." |
| 1:45 | README evaluation table | "Measured: 1% invented places versus 73% for a plain LLM; 13 of 13 red-team attacks defended." |
