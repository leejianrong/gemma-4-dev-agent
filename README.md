# gemma-4-dev-agent

Entry for the [Gemma 4 Developer Agent](https://www.kaggle.com/competitions/gemma-4-developer-agent)
Kaggle competition: a declarative agent config (plus optional LoRA) that fixes real Python
issues offline on a quantized Gemma 4.

```
make setup   # dev tools + pre-push hook
make check   # lint, unit tests, submission pre-flight
make zip     # dist/submission.zip
```

Status and plan: `docs/QUESTIONS.md`. Agent conventions: `CLAUDE.md`. Licensed under Apache-2.0
(see `docs/adr/0001-license-apache-2.md`); LoRA adapters also fall under the Gemma Terms of Use.
