# Paper and blog notes for the Gemma 4 agent

Fetched 2026-11-13 with WebFetch (a small model summarises each page, so treat quoted numbers as one hop from the primary text). The two arXiv pages were read only for their first 100,000 characters; appendices are not read. Numbers not seen in the page text are marked "unverified".

## LLM-as-a-Verifier (arXiv 2607.05391v2)

- Setup: verifier is Gemini 2.5 Flash (Terminal-Bench, SWE-Bench, scaling study) or Qwen 3.6 35B (robotics). Generators are GPT-5.5 (Terminal-Bench), a pool of Claude Opus 4.5, Gemini 3 Flash and MiniMax M2.5 (SWE-Bench Verified, N=3 candidates per task), Claude Opus 4.8 (MedAgentBench). Sizes of closed models are not stated.
- Headline: SWE-Bench Verified 78.2% against mean Pass@1 76.1% and best single model (Opus 4.5) 76.8%; oracle 84.4%. Terminal-Bench V2 86.5% against Pass@1 83.1%.
- Cost: no training, but needs N candidate patches per task plus C x K pairwise verification calls and token logprobs.
- Under our limits: no. We get one sample and 28 calls, and Gemma through our harness probably does not expose logprobs for a verifier pass.
- Distrust: self-reported, frontier generators, and the gain over the best single model is 1.4 points on SWE-Bench; baselines come from different harnesses. Pivot count k is unverified.

## SWE-Verifier (arXiv 2610.30284)

- Setup: Qwen3.5-4B fine-tuned as a step-level verifier; policies MiniMax-M2.7 and DeepSeek-V4-Flash (sizes not stated). SWE-Bench Verified, 500 tasks, mini-swe-agent; 202-task subset for tuning.
- Headline: MiniMax-M2.7 75.47% +/- 1.40 without verifier, 77.20% +/- 0.87 with Two-Stage Rubric verifier at 1.09x cost. DeepSeek-V4-Flash 72.60% +/- 0.53 to 74.27% +/- 1.01 at 1.13x. All-step self-verification: 75.27% at 3.35x.
- Cost: training required (30k action labels from 6,000 steps, 4 H200s, teacher GPT-5.6). At inference it scores every action and samples three extra candidates when the gate score is low (3.43% of steps verified).
- Under our limits: no. It needs a trained verifier running beside the policy, and we have no GPU time and a LoRA-only training route. The idea of spending extra samples only on a few uncertain steps is the one transferable piece, partly.
- Distrust: the MiniMax gain of 1.73 points is inside the reported standard deviations; cost assumes the local verifier is free; one benchmark and harness; all-step rows are single runs.

## Hashline vs replace edit format

Sources: dev.to (nwyin) and the harness-problem post. blog.can.ac redirected (302) to stencil.so/blog/the-harness-problem, which was read instead.

16-model benchmark (stencil.so page):
- Setup: 16 models, 180 tasks per run, 3 runs each. Task is a mutated React file with a plain-English bug description; the agent has read, edit and write tools. Models include Grok Code Fast 1, MiniMax M2.1, Devstral Medium, GLM-4.5 Air, GLM-4.7, GPT-5.1 Codex Mini, Grok-4.1 Fast, Grok 4 Fast, Qwen Turbo, Claude Sonnet 4.5, Claude Haiku 4.5, Gemini 2.5 Flash Lite, Kimi K2.5, Gemini 3 Flash, GPT-5.2 Codex, DeepSeek V3.2. No model sizes given.
- Headline: hashline beats the patch format in 14 of 16 models. Against replace the gains are smaller, in percentage points: Haiku 4.5 +11.3, Gemini 3 Flash +11.3, MiniMax M2.1 +10, GLM-4.7 +8.3, Kimi K2.5 +5, Grok Code Fast 1 +4.6, GPT-5.1 Codex Mini +4.2, Devstral Medium +3.8, Sonnet 4.5 +3.3, GLM-4.5 Air +0.4; Qwen Turbo -1.7, Grok 4 Fast -0.4, GPT-5.2 Codex -0.4, DeepSeek V3.2 -8.3. Output tokens fell for most models (for example Grok 4 Fast -61%). Largest cited gain: GPT-5.1 Codex Mini 60.0% to 77.5%; Grok Code Fast 1 6.7% to 68.3% (against patch format, not replace).
- The table headers on the page were garbled, so the column reading (vs patch, vs replace) is the summariser's inference: unverified.
- Weakest or smallest models: the page does not say which are small. Against replace, the small-ish ones (GLM-4.5 Air, Qwen Turbo, Gemini 2.5 Flash Lite) gain 0.4, -1.7 and 0, so there is no evidence of a big hashline gain for weak models over a str_replace tool.
- Training/extra calls: none. Each read and grep returns lines tagged with a 2-3 character content hash; edits cite tags and are rejected if the file changed.
- Under our limits: partly. It needs a changed read_file/edit_file contract, and our tools are fixed. We can only imitate it through prompt wording (cite line numbers), which our e4b_v3 already does for small models.
- Distrust: synthetic mutation tasks on React files, author writes for a vendor of the harness, numbers do not fully reconcile (6.7% to 68.3% is 61.6 points, table says +64.6), Gemini results may be incomplete.

Independent small replication (dev.to, nwyin):
- Setup: gpt-4.1-mini, gemini-3-flash-preview, qwen3.5-397b-a17b on edit-bench (mutation tests, Python/TypeScript/Rust), 20 tasks per language, one attempt.
- Headline: replace vs hashline, Python/TS/Rust: gemini-3-flash 95/80/95 vs 70/85/90; qwen3.5-397b 90/85/85 vs 85/85/90; gpt-4.1-mini 65/75/45 vs 50/70/55. Weakest model gpt-4.1-mini averages about 61.7% (replace) and 58.3% (hashline); the author says model gap is much bigger than format gap.
- No training. Under our limits: no, since it finds no gain from the format. Distrust: 20 tasks per cell, author calls it not statistically rigorous; fuzzy matching never triggered in 134 replace edits.

## More with Less: turn limits (arXiv 2510.16786v2)

- Setup: Claude 4 Sonnet, Gemini 2.5 Pro, GPT 4.1 (closed, sizes not stated) on a 100-task SWE-bench Verified subset, TRAE Agent with str_replace_editor, bash, task_done. Limits at the 25th, 50th, 75th percentile of baseline turns, with remaining-turn reminders, plus dynamic 25 to 50 and 50 to 75 extensions.
- Headline: unlimited baseline solve rates 75% (Sonnet, $585.21), 63% (Gemini, $407.66), 62% (GPT 4.1, $322.02). At the 75th percentile limit: Sonnet 71% ($446.99, down 23.62%), Gemini 65% ($129.32, down 68.28%), GPT 4.1 57% ($198.26, down 38.43%). Paper reports cost cuts of 24%-68%.
- Training/extra calls: none; each task allowed up to three patch attempts.
- Under our limits: partly. The result is about saving cost, not raising resolution; the useful part is telling the model its remaining budget, which suits our hard 28-call cap.
- Distrust: mostly single runs, closed frontier models only, prompt caching off, results tied to one agent and reminder wording. Resolution dropped for two of three models at the sweet spot.
- Percentile turn counts themselves are unverified (not extracted).

## Sweep edit normalization

- Page status: https://blog.sweep.dev/posts/jetbrains-coding-agent failed to load (DNS error ENOTFOUND, as did sweep.dev). Everything below comes from a WebSearch snippet, not the primary text, and is unverified.
- Setup: coding agent for JetBrains; models and benchmark not known.
- Headline (unverified): normalising the model's new_string in place, for example trimming trailing whitespace, cut the edit error rate by 38%, from 13% to 8%. The post also discusses "state drift", where the file changes between read and edit.
- Training/extra calls: none (unverified).
- Under our limits: yes in principle, but edit_file is a fixed tool, so we cannot normalise in code; we can only instruct the model on whitespace and re-reading before editing.
- Distrust: vendor blog, own production telemetry rather than a benchmark, no model or n known.

## What to try under our limits

- Tell the model its remaining budget in the prompt (28 calls, 8 minutes) and to submit once a patch exists; the turn-limit paper suggests this cuts waste, but check it by first-edit call and calls per task, not resolution.
- Keep the line-number or exact-copy edit instructions already in e4b_v3 and add whitespace guidance (copy old_string verbatim, no trailing spaces, re-read after a failed edit); the format studies show gains of 0 to 11 points for some models and losses for others, so judge by edit-failure rate in logs.
- Instruct re-reading the target lines immediately before every edit to avoid state drift, the cheapest analogue of hashline's stale-file check.
- If a free second pass remains in the budget, spend it on a cheap self-check of the patch (run the issue's reproduction), but expect little; the verifier papers show gains of 1 to 2 points with frontier models and extra samples.
- Do not pursue trained or multi-sample verifiers (SWE-Verifier, LLM-as-a-Verifier): they need extra samples, logprobs or training we cannot afford.
