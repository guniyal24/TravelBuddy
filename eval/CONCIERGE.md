# Concierge evaluation (2026-11-10)

The hotel agent run on the first 3 hotels of each offered town (25 hotels, 9 towns), with live Google reviews.

| measure | result |
|---|---|
| hotels Google could match (name + location) | 56% (37-73%) |
| reviews read | 63 |
| analyst claims whose quote was found in the cited review | 95% (86-98%) |
| Spearman: analyst aspect score vs Google star rating | 0.60 over 12 hotels |

Claims that fail the quote check are dropped before a traveller sees them, so the survival rate measures how often the analyst paraphrases or invents; it is not an error rate of what is shown. Ranking is computed in code (rating shrunk toward 4.0 by review count, tier and budget fit), not by the LLM.
