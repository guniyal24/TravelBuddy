# Concierge evaluation (2026-11-11)

The hotel agent run on the first 3 hotels of each offered town (76 hotels, 26 towns), with live Google reviews.

| measure | result |
|---|---|
| hotels Google could match (name + location) | 67% (56-77%) |
| reviews read | 234 |
| analyst claims whose quote was found in the cited review | 92% (88-95%) |
| Spearman: analyst aspect score vs Google star rating | 0.48 over 46 hotels |
| LLM cost per town researched (median) | ₹0.02, plus 3 Google Places calls |

Claims that fail the quote check are dropped before a traveller sees them, so the survival rate measures how often the analyst paraphrases or invents; it is not an error rate of what is shown. Ranking is computed in code (rating shrunk toward 4.0 by review count, tier and budget fit), not by the LLM.
