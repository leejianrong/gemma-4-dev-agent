.DEFAULT_GOAL := help
.PHONY: help setup hooks lint fmt test validate check zip

help: ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup: ## Install dev tooling and git hooks
	uv sync
	$(MAKE) hooks

hooks: ## Point git at .githooks (pre-push runs `make check`)
	git config core.hooksPath .githooks

lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Apply ruff formatting and safe fixes
	uv run ruff check --fix .
	uv run ruff format .

test: ## Fast unit tests (no GPU, no docker, no data); pulls the viz group on demand
	uv run --group viz pytest -q

validate: ## Check submission/ against documented harness limits
	uv run python scripts/submission.py check submission

check: lint test validate ## Everything the pre-push hook and CI run

zip: ## Build dist/submission.zip (runs validate first)
	uv run python scripts/submission.py zip submission dist/submission.zip

.PHONY: rehearse
rehearse: ## Rehearse pod/job.sh against fake CLIs with injected failures (free, ~3 min)
	bash pod/rehearse/run.sh

KAGGLE_USER = $$(python3 -I -c "import json,os;print(json.load(open(os.path.expanduser('~/.kaggle/credentials.json')))['username'])")

.PHONY: kernel kernel-eda eda pull-eda
kernel: ## Build the Kaggle explore kernel from pod/explore.py (username read by key name)
	python3 kaggle/build_kernel.py "$(KAGGLE_USER)"

kernel-eda: ## Build the Kaggle EDA-extract kernel from pod/eda_extract.py
	python3 kaggle/build_kernel.py "$(KAGGLE_USER)" eda

eda: ## Regenerate every EDA figure into figures/eda/ from data/eda/
	uv run --group viz python -m analysis.run_all

pull-eda: ## Download the EDA kernel output into data/eda/ (small CSVs, no competition files)
	mkdir -p data/eda
	kaggle kernels output "$(KAGGLE_USER)/gemma-4-eda-extract" -p data/eda
