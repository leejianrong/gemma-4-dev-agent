# Literature and community notes

Trust levels: **paper** = peer-reviewed or arXiv, seen as a snippet; **blog** = single author, small sample;
**issue** = bug thread, anecdotal. None of this is measured on our setup (Gemma 4 w4a16, 32k context, 8 min, 28 calls).

## 1. Edit mechanics

| Claim | Source | Trust |
|---|---|---|
| 77% of `str_replace` failures: the text to replace is not in the file; tab and punctuation drift are common causes | [Hashline vs replace](https://dev.to/nwyin/hashline-vs-replace-does-the-edit-format-matter-15n2), [The harness problem](https://blog.can.ac/2026/02/12/the-harness-problem) | blog |
| A Feb 2026 test of 16 models over patch, `str_replace` and hashline (line-anchored) formats: the weakest models gained most | same | blog, "not rigorous" by one author |
| Normalising edit output cut agentic edit failures by 38% | [Sweep](https://blog.sweep.dev/posts/jetbrains-coding-agent) | blog |
| Model gap dwarfs format gap in a 20-task comparison; failures were hallucinated content and line numbers left in `old_string` | [agentpatterns](https://www.agentpatterns.ai/tool-engineering/llm-edit-format-selection/) | blog |
| Search-replace beats unified diff for large models; small open models gain almost nothing from any format (Diff-XYZ, as reported) | same | secondhand |
| No source tests line-number edits against `str_replace` on small models directly | (search gap) | |

Reading for us: A44 matches the first row (old_string not found is about half of E2B's edit calls). The v3 line-number
edit is the cited fix, but the counterpoint says a format change may do little. We need our own run to know.
Notice the counterpoint's failure mode: line numbers copied into `old_string`. Check v3 traces for the mirror image
(wrong line numbers).

## 2. Gemma 4 chat template and tool calls

- After a tool response the template does not open a new `<|turn>model`, so all tool rounds share one model turn; `content` on a
  `tool_calls` message is rendered after the tool response instead of before the call. Reported symptoms: reasoning missing after the
  first tool call (31B), at most one good tool call before answering, repetition loops from re-injected reasoning.
  [HF 31B discussion 115](https://huggingface.co/google/gemma-4-31B-it/discussions/115) (**issue**, anecdotal fixes). A Google
  team member said on Jul 24 a fix was coming and linked vLLM PR #42776. Whether the Kaggle image has the fix is unknown.
- Workarounds named there: the vLLM recipe's Jinja template; forcing an open thought channel (does not work with thinking off).
- Other threads (HF 31B discussions 119, 134 to 137, 142): hallucinated tool schemas, template fixes.
  [vLLM recipe](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html),
  [Google function-calling guide](https://ai.google.dev/gemma/docs/capabilities/function-calling).

Reading for us: we do not control the template or vLLM flags (the harness does). We can still see the symptom in traces and,
if present, shape the prompt around it. Not yet looked at.

## 3. Selection, verification, time policy

| Claim | Source | Trust |
|---|---|---|
| Training-free best-of-N with an LLM verifier; reported 78.2% on SWE-bench Verified, but over frontier models, not small ones | [LLM-as-a-Verifier](https://arxiv.org/html/2607.05391v2) | paper |
| Verify only selected steps (under 4%); 75.47 to 77.20% at 1.09x cost on a frontier model | [SWE-Verifier](https://arxiv.org/html/2610.30284) | paper |
| Open-source verifiers leave a gap to oracle selection | [SWE-ZERO to SWE-HERO](https://arxiv.org/pdf/2604.01496) | paper |
| Best results with test-time scaling lean on a trained testing agent / pre-trained model | [R2E-Gym](https://arxiv.org/pdf/2504.07164), [Satori-SWE](https://arxiv.org/html/2505.23604v1) | paper |
| Dynamic turn limits beat fixed limits at equal or lower cost | [More with Less](https://arxiv.org/html/2510.16786v2) | paper |
| Early termination cuts cost 19 to 55% (mean 32%), loss "negligible" (unverified) | [EET](https://www.alphaxiv.org/abs/2601.05777.md) | paper, snippet |
| Trajectory reduction cuts cost 21 to 36% at the same score | [AgentDiet](https://arxiv.org/html/2509.23586v1) | paper |

Reading for us: N samples do not fit in 8 minutes per task, so selection would have to live inside one run. Our budget
stops and time-outs are 20% of task-runs, almost all in never-solved tasks (A42), so the interesting lever is spending
less on hopeless tasks and more on flaky ones, not cost saving as such. Verifier results are on frontier models; do not expect them to transfer to a 4-bit 31B.

## 4. Fine-tuning from trajectories

| Claim | Source | Trust |
|---|---|---|
| 32B model to 20.6% on SWE-bench Verified from 491 trajectories | [SWE-Gym](https://arxiv.org/html/2412.21139v2) | paper |
| 7B to 42.4% with about 5k SFT trajectories plus a short RL phase; scaling SWE-smith data can regress | [SWE-Protege](https://arxiv.org/html/2602.22124v1) | paper |
| Training on resolved trajectories only (5k) beat mixing in failures: 30.9%; step rejection fine-tuning 32.2% | [JetBrains](https://blog.jetbrains.com/research/2026/06/step-rejection-fine-tuning/), [paper](https://arxiv.org/pdf/2605.10674) | blog and paper |
| Unfiltered self-generated trajectories collapsed performance; rejection filtering restored it | [daVinci-Agency](https://arxiv.org/pdf/2602.02619) | paper |
| Unit tests alone are not a sufficient trajectory filter | cited in the same search | secondhand |
| Agents trained on SWE-Gym or R2E-Gym generalise poorly beyond SWE-bench format | [SWE-Playground](https://arxiv.org/html/2512.12216v2) | paper |

Reading for us: published gains use thousands of trajectories from a strong teacher. We have about 15 own resolved
traces, no teacher we may use on real tasks (hosted APIs would receive task text, rules 4b), and 1.8 USD. The synthetic set
(A45, 14 tasks, 2-line patches) is the only data we could train on without the terms problem, and it is too easy.
Only the `w4a16-ct` bases and `.safetensors` adapters are allowed as shipped artifacts.

## 5. Working round GPU limits

- **Small proxy model.** Koh et al. find small models predict large ones only when aligned with the target task, and there is a
  size floor ([arXiv 2509.21013](https://arxiv.org/html/2509.21013v1); about pretraining-style reasoning, not agents).
  Our own proxy is E4B on a 0.24 USD/h card (about 0.5 USD per replicate). Risk: E4B's dominant failure (edit mechanics) is not 31B's, so a win may not transfer.
- **PACE** predicts a model's agentic score from a small set of non-agentic instances; MAE under 4%, rank accuracy about 85%
  over 14 models ([paper](https://huggingface.co/papers/2607.02032.md)). It ranks models, not prompts, so it does not fit.
- **Offline replay of logged trajectories:** no good source found.
- **Community on this competition:** no public discussion posts or LoRA notebooks found by search. One paper-track writeup:
  [TOPAZ](https://blog.gopenai.com/how-i-built-topaz-competing-in-googles-gemma-4-paper-track-904286cb4531). The Kaggle
  Discussion and Code tabs need a logged-in look.
