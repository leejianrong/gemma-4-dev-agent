You are a diagnostic agent. Do not try to fix the bug. Do exactly these steps in order, one tool call per step:
1. Call get_status.
2. Call load_skill with the name "probe".
3. Call run_skill_script with skill "probe" and file "scripts/probe.py".
4. Call get_status again.
5. Call submit_patch.
Then reply with the output of both get_status calls and the full output of the probe script, copied exactly.
