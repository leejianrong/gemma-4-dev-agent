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

test: ## Fast unit tests (no GPU, no docker, no data)
	uv run pytest -q

validate: ## Check submission/ against documented harness limits
	uv run python scripts/submission.py check submission

check: lint test validate ## Everything the pre-push hook and CI run

zip: ## Build dist/submission.zip (runs validate first)
	uv run python scripts/submission.py zip submission dist/submission.zip

.PHONY: rehearse
rehearse: ## Rehearse pod/job.sh against fake CLIs with injected failures (free, ~3 min)
	bash pod/rehearse/run.sh
