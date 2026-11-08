# Kaggle Writeup form: fields to fill on every submission

Seen on the paper-track submission page (2026-11-09). Limits (characters, image size, aspect
ratio) are not recorded here: read them in the form and add them below when known.
Only a *submitted* writeup counts. A saved draft is ignored (docs/COMPETITION.md section 10).

| Field | What to put in it | Our choice for the paper |
|---|---|---|
| Title | Short, states the question | "Where does a code graph help a bug-fixing agent?" |
| Subtitle | The main finding in one sentence | "BM25 beats graph and embedding search at finding the edit site; call-graph neighbours predict sibling edits." |
| Card and thumbnail image | One simple picture that reads at small size | A new single-panel figure (see below); not a dense multi-panel EDA figure |
| Media gallery | 4 to 6 figures, in paper order, each with its caption | eda_04, eda_05, eda_06, eda_07, eda_02 (+ GEM-77 figure when built) |
| Project description | The paper text, 3,000 words or fewer | `paper/DRAFT.md` after GEM-26 and the leaderboard number |
| Links | Code repo, public notebook | github.com/leejianrong/gemma-4-dev-agent; the GEM-27 notebook |
| Attachments: code | The public notebook with config, prompts, hashes (GEM-27) | Required for verifiability. A private notebook becomes public after the deadline |
| Attachments: model weights | Only if we trained something | None: harness-only entry, no adapter |
| File uploads | Small result tables that back the numbers | `experiments/runs.csv`, the EDA JSON tables. Not competition data; not annotations until GEM-22 |
| DOI | Opt in or out | Decide at submit time, see advice below |

## Checklist before pressing Submit (GEM-28)
- [ ] Every field above filled; limits recorded here
- [ ] Description word count 3,000 or fewer
- [ ] Leaderboard number and citations in the text are final (no PENDING, no TODO)
- [ ] Notebook attached and runs; nothing private in it that should not go public
- [ ] DOI choice made on purpose
- [ ] Pressed Submit, not Save
