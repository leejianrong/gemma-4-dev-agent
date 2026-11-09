"""Filter stdin to stdout, replacing the Kaggle token from .env with <redacted>."""

import sys

from pod.pod_cmd import ENV, env_value

if __name__ == "__main__":
    tok = env_value(ENV, "KAGGLE_API_TOKEN")
    for line in sys.stdin:
        sys.stdout.write(line.replace(tok, "<redacted>") if tok else line)
