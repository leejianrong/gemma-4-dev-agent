# T10: Is a LoRA trained on our own traces worth trying? (2026-11-13)

**Recommendation: no-go for now.** Reasons, in order of weight:

1. **Data.** The 31B traces hold 56 resolved task-runs over only 17 distinct tasks (12 always solved, 5 flaky); the pod run adds 15 more resolved
   runs but saved no traces. Published SWE-agent fine-tunes used 491 to about 5,000 trajectories from a stronger teacher over hundreds of
   distinct tasks (literature.md section 4). Our set is dominated by the easy tasks (gold patches median 5 lines, A42), so it would
   teach the model what it already does.
2. **No teacher.** We are not allowed to use a hosted model on real tasks (task text would leave the machine, CLAUDE.md). Distilling 31B into E4B is
   the only teacher we have, and the 31B is itself at 36 to 42% on the dev tasks.
3. **Terms.** Rules 4b: we may not transmit, duplicate, publish or redistribute Competition Data (COMPETITION.md section on derived
   data). Traces contain issue text, repo code and patches. Sending them to a pod already happens for the data itself (`runpodctl send`), but
   adapter weights trained on them would be shipped inside `submission.zip`. Whether weights derived from task data count as redistributing it
   is unresolved; ask the host before spending on it. The synthetic tasks (A45) avoid the question but are too easy (2-line patches).
4. **Mechanics.** Only `w4a16-ct` bases and `.safetensors` PEFT adapters are accepted. Training an adapter against a compressed-tensors
   4-bit base is not a standard recipe and the training stack on a pod is untested. Cost is small (a one-hour run on a 16 to 24 GB
   card is under 0.5 USD at the prices in GPU_RUNS) but the setup risk is not.
5. **Budget.** About 1.8 USD is left, a small-model replicate costs about 0.5 USD, and noise is 8 to 11 points; a LoRA result could
   not be told apart from noise with one replicate.

**What would change this:** the host confirming that adapter weights are not Competition Data; T11 producing harder synthetic tasks
with multi-line patches (so there is something new to learn); or budget beyond the 10 USD cap.
If revisited, the cheapest first experiment is E4B only, filtered to resolved trajectories (JetBrains found that filter better than mixing
in failures, literature.md), judged by edit-refusal rate before resolution.
