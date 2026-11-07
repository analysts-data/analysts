.PHONY: check e2e eval eval-holdout record run fmt

check:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy
	uv run pytest -q
	@if ls web/js/*.test.js web/js/*/*.test.js tests/*/*.test.js >/dev/null 2>&1; then node --test "web/**/*.test.js" "tests/**/*.test.js"; fi
	@if [ -x scripts/secret_scan.sh ]; then scripts/secret_scan.sh; fi
	@if [ -x scripts/protected_paths.sh ]; then scripts/protected_paths.sh; fi
	@if [ -d openspec ]; then openspec validate --all --strict >/dev/null && echo "openspec: ok"; fi

e2e:
	uv run pytest -q -m e2e tests/e2e

eval:
	@echo "нет эталона: make eval появится в eval-and-delivery"

eval-holdout:
	@echo "нет эталона: make eval-holdout появится в eval-and-delivery"

record:
	@echo "запись ответов модели появится в llm-evaluation"

run:
	uv run uvicorn cqa.http.app:create_app --factory --reload --port 8000

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests
