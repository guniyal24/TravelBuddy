# Circuit discovery: town search + LLM vs rule-based list

**search** (app default): Pinecone town profiles find towns that fit the request; an LLM proposes circuits from those short profiles and road times; code rejects impossible ones (days, road times, availability) and the rule-based list is the fallback. Places are then retrieved only for the chosen towns, graded against the interests, and expanded from the graph. **rules**: the previous design, the curated circuit list scored in code by season and interest tags.

Same code, data, models and day for both; only the circuit step differs. Checks are computed in code (see `eval/plans.py`); 95% Wilson intervals.

## 30 trip requests (`eval/scenarios.yaml`)

Runs: search 2026-11-27, rules 2026-11-27.

| check | search | rules |
|---|---|---|
| reaches the approval step | 100% (89-100%) | 100% (89-100%) |
| every place exists in our data | 100% (89-100%) | 100% (89-100%) |
| exact number of days | 100% (89-100%) | 100% (89-100%) |
| includes every named town | 100% (88-100%) | 100% (88-100%) |
| named towns offered first | 100% (88-100%) | 100% (88-100%) |
| stops and meals in that day's town | 100% (89-100%) | 100% (89-100%) |
| a stay every night | 100% (89-100%) | 100% (89-100%) |
| veg diet respected | 100% (57-100%) | 100% (57-100%) |
| budget fits or is flagged | 100% (44-100%) | 100% (44-100%) |
| health note above 2,500 m | 100% (34-100%) | 100% (34-100%) |
| LLM draft valid first try | 93% (79-98%) | 93% (79-98%) |
| no rule-based fallback needed | 100% (89-100%) | 100% (89-100%) |

| per trip (median) | search | rules |
|---|---|---|
| LLM calls | 4 | 2 |
| tokens | 2,746 | 1,338 |
| agent time | 19 s | 12 s |
| LLM cost | $0.0003 | $0.0002 |

Search fell back to the rule-based list in 1 of 30 requests (p22).

## 15 open requests, no town named (`eval/discovery.yaml`)

Runs: search 2026-11-27, rules 2026-11-27.

| check | search | rules |
|---|---|---|
| reaches the approval step | 100% (80-100%) | 100% (80-100%) |
| every place exists in our data | 100% (80-100%) | 100% (80-100%) |
| exact number of days | 100% (80-100%) | 100% (80-100%) |
| stops and meals in that day's town | 100% (80-100%) | 100% (80-100%) |
| a stay every night | 100% (80-100%) | 100% (80-100%) |
| LLM draft valid first try | 93% (70-99%) | 100% (80-100%) |
| no rule-based fallback needed | 100% (80-100%) | 100% (80-100%) |
| open request: 1st circuit fits | 100% (80-100%) | 100% (80-100%) |
| open request: a circuit fits | 100% (80-100%) | 100% (80-100%) |

| per trip (median) | search | rules |
|---|---|---|
| LLM calls | 5 | 2 |
| tokens | 4,293 | 1,378 |
| agent time | 29 s | 14 s |
| LLM cost | $0.0004 | $0.0002 |

Search fell back to the rule-based list in 0 of 15 requests.

First circuit offered:

| request | search | rules |
|---|---|---|
| d01 4 days in November for 2 people, we love lakes and boating | Bhimtal + Nainital + Ranikhet | Nainital + Bhimtal |
| d02 Wildlife safari with a chance to see tigers, 3 days, fami... | Jim Corbett | Jim Corbett + Nainital |
| d03 5 days of snow and skiing in January for 2 friends | Auli | Rishikesh + Auli |
| d04 Temples and the evening Ganga aarti, 3 days, 2 people, Oc... | Haridwar + Dhanaulti | Haridwar + Rishikesh |
| d05 Tea gardens and Himalayan sunrise views for a couple, 3 d... | Kausani + Munsiyari | Almora + Kausani |
| d06 Valley of flowers trek, 4 days, 2 friends, August | Valley of Flowers (Ghangaria) | Valley of Flowers (Ghangaria) |
| d07 White water rafting and cafes for 3 days, 3 friends, March | Rishikesh + Lansdowne | Haridwar + Rishikesh |
| d08 A quiet forest getaway with birdwatching, 3 days, 2 peopl... | Dhanaulti + Kanatal | Mussoorie + Dhanaulti |
| d09 A pilgrimage to the high Himalayan temples, 6 days, 2 peo... | Joshimath + Badrinath + Valley of Flowers (Ghangaria) | Uttarkashi + Gangotri |
| d10 Heritage, local crafts and mountain culture for 3 days, 2... | Almora + Pithoragarh | Nainital + Almora |
| d11 Ek shant pahadi jagah, 3 din, 2 log, December, barf dekhn... | Dhanaulti + Kanatal + Mussoorie | Dhanaulti + Kanatal |
| d12 Family trip with small kids, easy sightseeing and a mall ... | Mukteshwar + Bhimtal + Nainital | Mussoorie + Dhanaulti |
| d13 मंदिर और गंगा आरती, 2 दिन, 2 लोग, नवंबर | Haridwar | Haridwar + Rishikesh |
| d14 Camping under the stars and a short trek, 3 days, 2 frien... | Chopta + Kedarnath | Dhanaulti + Kanatal |
| d15 Honeymoon in the hills with great views, 4 days in Decemb... | Nainital + Ranikhet + Mukteshwar | Nainital + Almora + Kausani |

✗ = the first circuit has none of the hand-labelled fitting towns.
