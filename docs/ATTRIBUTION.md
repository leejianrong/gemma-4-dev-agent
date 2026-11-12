# Attribution

`submission/` is the baseline agent from the Kaggle notebook **Gemma 4 | Budget-Aware Coding Agent
v2** by flexonafft (`flexonafft/gemma-4-budget-aware-coding-agent-v2`). That notebook credits
matterhorn3838's **Gemma 4 SuperAgent** (https://www.kaggle.com/code/matterhorn3838/gemma-4-superagent),
the official `sample_submission` prompt, and community investigations of the graph tools. Kaggle
notebooks are Apache-2.0 by default; this repo is Apache-2.0.

What we took: `agent.yaml`, `configs/sampling.yaml`, `eval_config.yaml` and `prompts/system.md`,
extracted by running only the notebook's string-definition cell (the notebook packages a zip and
runs no model). Nothing is changed except a comment block at the top of `agent.yaml`, which is not
sent to the model. `prompts/system.md` is byte-identical to the notebook's `SYSTEM_PROMPT`.

Scores: the notebook says its SuperAgent adaptation scored 0.18 on the public leaderboard and that
this v2 candidate **has not been scored**. Third-party scores are unverified (see
`docs/QUESTIONS.md`). Our own baseline number comes from our runs (GEM-10, GEM-11).

Things in this baseline that are choices, not facts about the harness: 28 tool calls, 8 minutes and
80 turns (the harness defaults are 100 calls, 60 minutes, 500 turns), and a prompt that tells the
agent never to use the three graph tools. The second matches our measurements (A27, A28) but the
first limits the agent more than it needs to; treat both as ablation targets (GEM-12).

## Apache Beam vLLM notebook (reference only)

`docs/reference/colab/beam_run_inference_vllm.ipynb` is the Apache Beam example notebook "Run ML
inference by using vLLM on GPUs" (apache/beam, `examples/notebooks/beam-ml/run_inference_vllm.ipynb`),
Apache License 2.0, copyright the Apache Software Foundation. It is kept unchanged, with its license
header, as a reference for running vLLM on a Colab T4. We do not run it. Ruff skips `docs/reference/`.
