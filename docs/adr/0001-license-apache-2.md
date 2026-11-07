# 0001. License the repo under Apache-2.0

Date: 2026-11-07. Status: accepted. Owner confirmed Apache-2.0 on 2026-11-07; still verify against the Rules tab before 2026-11-25.

## Context
The competition requires winners to release their submission under an open licence. The
Kaggle Rules tab could not be fetched (JavaScript-rendered). A secondary source says the
winner licence is Apache-2.0; a different Gemma hackathon used CC-BY 4.0. MIT was the
initial guess.

## Decision
Apache-2.0. It is permissive like MIT, adds an explicit patent grant, and matches the
licence the secondary source gives for winners, so a win would need no relicensing.

## Consequences
- Verify against Rules > "Winner License" before the entry deadline (2026-11-25). If it says
  something else, relicense now while we are the only contributor.
- LoRA adapters are derivatives of Gemma weights and also fall under the Gemma Terms of Use.
  Adapters are gitignored and are not covered by this repo licence.
- Rejected: MIT (no patent grant, and no evidence the competition asks for it), CC-BY 4.0
  (a content licence, poor fit for code).
