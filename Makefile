.PHONY: check e2e eval eval-holdout record run fmt demo

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
	@echo "нет эталона: make eval появится в eval-and-delivery"

eval-holdout:
	@echo "нет эталона: make eval-holdout появится в eval-and-delivery"

record:
	CQA_LLM_MODE=record uv run pytest -m "cassette or e2e"

run:
	uv run uvicorn cqa.http.app:create_app --factory --reload --port 8000

demo:
	# без ключа: replay, база data/demo.db, набор tests/e2e/fixtures/defence_set.json
	uv run python scripts/demo.py serve

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests
