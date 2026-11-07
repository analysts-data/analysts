.PHONY: check e2e eval eval-holdout record run fmt

check:
	uv run ruff check --no-cache src tests
	uv run ruff format --check src tests
	uv run mypy
	uv run pytest -q
	@if find web tests -name '*.test.js' | grep -q .; then node --test "web/**/*.test.js" "tests/**/*.test.js"; fi
	@if [ -x scripts/secret_scan.sh ]; then scripts/secret_scan.sh; fi
	@if [ -x scripts/protected_paths.sh ]; then scripts/protected_paths.sh; fi
	@if [ -d openspec ]; then openspec validate --all --strict >/dev/null && echo "openspec: ok"; fi

e2e:
	# код 5 — e2e-тестов пока нет: цель не должна ломать CI пустым набором
	uv run pytest -q -m e2e tests/e2e || [ $$? -eq 5 ]

eval:
	CQA_LLM_MODE=live uv run python -m cqa.services.quality_eval $(ARGS)

eval-holdout:
	CQA_LLM_MODE=live uv run python -m cqa.services.quality_eval --holdout $(ARGS)

record:
	@echo "запись ответов модели появится в llm-evaluation"

run:
	uv run uvicorn cqa.http.app:create_app --factory --reload --port 8000

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests
