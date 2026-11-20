# ADR-0007: The second final is an E4B bundle; stop tuning E4B prompts

- Status: Accepted
- Date: 2026-11-20
- Deciders: owner (asked to carry out the recommendation)

## Context
ADR-0003 makes the second final a small-model entry so the $10k small-model bonus stays possible. Since then (A43 to A58):
E4B v2 scored 0.06 on the leaderboard (A57) against 0.18 for the 31B baseline; the thinking budget, the edit skill
(`e4b_edit2`) and v3 edits changed edit-failure rates but not resolution on 36 dev tasks (A49, A54, A58); dev resolution
runs 5 to 8 of 36 whatever we change, and identical zips differ by about 1.6 tasks on the hidden set. One leaderboard
submission is allowed per day and the entry deadline is 2026-11-25.

## Decision
- Select an E4B bundle as the second final. Default is `e4b_v2` (zip `85d00aac`, already scored). `e4b_edit2` is the
  alternative only if a public score or a log signal gives a reason; it solves the same dev tasks (A58).
- No more E4B prompt or budget arms. Effort goes to the 31B entry, where the main prize is.
- Keep E4B work to what feeds both entries (the benchmark v2 data, the LoRA question to the host).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Keep tuning E4B prompts | Four arms moved log signals, none moved resolution; the detectable gain is about 11 points and the search space is exhausted at this noise level |
| E2B as the second final | Never ahead of E4B (A43, A46) |
| Drop the bonus, two 31B finals | Forgoes the bonus for little diversity (ADR-0003) |

## Consequences
The small-model entry is probably weak (0.06 public). Its value is the chance at the bonus, which depends on other
competitors' small-model scores that we cannot see. GEM-37 picks the exact zip by 2026-11-25.
