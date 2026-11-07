.PHONY: check e2e eval eval-holdout record run fmt backup demo

check:
	uv run ruff check --no-cache src tests
	uv run ruff format --check src tests
	uv run mypy
	uv run pytest -q
	@if find web tests -name '*.test.js' | grep -q .; then node --test "web/**/*.test.js" "tests/**/*.test.js"; fi
	@if [ -x scripts/secret_scan.sh ]; then scripts/secret_scan.sh; fi
	@if [ -x scripts/protected_paths.sh ]; then scripts/protected_paths.sh; fi
	@if [ -x scripts/stop_code.sh ]; then scripts/stop_code.sh; fi
	@if [ -d openspec ]; then openspec validate --all --strict >/dev/null && echo "openspec: ok"; fi

e2e:
	# cassette вместе с e2e: test_every_cassette_is_replayed сверяет записи с журналом всего прогона
	CQA_CASSETTE_AUDIT=1 uv run pytest -q -m "e2e or cassette" tests

eval:
	CQA_LLM_MODE=live uv run python -m cqa.services.quality_eval $(ARGS)

eval-holdout:
	CQA_LLM_MODE=live uv run python -m cqa.services.quality_eval --holdout $(ARGS)

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

backup:
	uv run python scripts/backup_db.py
