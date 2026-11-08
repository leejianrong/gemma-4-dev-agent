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
	uv run --group viz --group dash pytest -q

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
	kaggle kernels output "$(KAGGLE_USER)/gemma-4-eda-extract" -p data/eda --force

.PHONY: kernel-map pull-map
kernel-map: ## Build the Kaggle gold-patch mapping kernel from pod/gold_map.py
	python3 kaggle/build_kernel.py "$(KAGGLE_USER)" map

pull-map: ## Download the mapping kernel output into data/map/ (gold_nodes.csv, gold_hunks.csv, report)
	mkdir -p data/map
	kaggle kernels output "$(KAGGLE_USER)/gemma-4-gold-map" -p data/map --force

.PHONY: kernel-localize pull-localize
kernel-localize: ## Build the Kaggle localization-baselines kernel (re-derives gold nodes first)
	python3 kaggle/build_kernel.py "$(KAGGLE_USER)" localize

pull-localize: ## Download the localization kernel output into data/localize/
	mkdir -p data/localize
	kaggle kernels output "$(KAGGLE_USER)/gemma-4-localize" -p data/localize --force

.PHONY: kernel-cochange pull-cochange
kernel-cochange: ## Build the Kaggle co-change kernel (re-derives gold nodes first)
	python3 kaggle/build_kernel.py "$(KAGGLE_USER)" cochange

pull-cochange: ## Download the co-change kernel output into data/cochange/
	mkdir -p data/cochange
	kaggle kernels output "$(KAGGLE_USER)/gemma-4-cochange" -p data/cochange --force

.PHONY: pull-runs dash
pull-runs: ## Download an eval-runner kernel's runs into data/runs/<KERNEL>/ (make pull-runs KERNEL=slug)
	@test -n "$(KERNEL)" || { echo "usage: make pull-runs KERNEL=<kernel slug>" >&2; exit 2; }
	mkdir -p data/runs/$(KERNEL)
	kaggle kernels output "$(KAGGLE_USER)/$(KERNEL)" -p data/runs/$(KERNEL) --force

dash: ## Serve the indah dashboards on a free port (fixtures when data/runs/ is empty)
	uv run --group viz --group dash python -m dashboards

.PHONY: kernel-subcheck pull-subcheck
kernel-subcheck: ## Build the Kaggle kernel that diffs submission/ against the starter sample_submission
	python3 kaggle/build_kernel.py "$(KAGGLE_USER)" subcheck

pull-subcheck: ## Download the submission-check output into data/subcheck/
	mkdir -p data/subcheck
	kaggle kernels output "$(KAGGLE_USER)/gemma-4-submission-check" -p data/subcheck --force

.PHONY: kernel-eval run-eval
kernel-eval: ## Build the GPU eval-runner kernel. EVAL_TASKS=5|all|id,id EVAL_RUN_ID EVAL_MODEL EVAL_CONCURRENCY EVAL_MAX_MIN
	python3 kaggle/build_kernel.py "$(KAGGLE_USER)" eval

run-eval: kernel-eval ## Push the eval runner to Kaggle GPU (uses quota; capped by EVAL_TIMEOUT_S, default 7200)
	kaggle kernels push -p kaggle/eval_kernel -t $${EVAL_TIMEOUT_S:-7200}
