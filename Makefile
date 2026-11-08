.PHONY: check e2e eval eval-holdout record run share fmt backup demo results docker-build docker-run

PORT ?= 8000

PORT ?= 8000

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
	CQA_CASSETTE_AUDIT=1 uv run pytest -q -m "e2e or cassette" tests $(ARGS)

eval:
	CQA_LLM_MODE=live uv run python -m cqa.services.quality_eval $(ARGS)

eval-holdout:
	CQA_LLM_MODE=live uv run python -m cqa.services.quality_eval --holdout $(ARGS)

record:
	CQA_LLM_MODE=record uv run pytest -m "cassette or e2e"

run:
	uv run uvicorn cqa.http.app:create_app --factory --reload --port $(PORT)

share:
	# показ жюри по сети: 0.0.0.0, вход по ссылке с токеном (README, «Доступ для жюри по сети»)
	@token=$${CQA_ACCESS_TOKEN:-$$(uv run python -c 'import secrets;print(secrets.token_urlsafe(16))')}; \
	ip=$$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $$1}'); \
	echo "Ссылка для жюри: http://$${ip:-<IP ноутбука>}:$(PORT)/login?token=$$token"; \
	CQA_ACCESS_TOKEN=$$token uv run uvicorn cqa.http.app:create_app --factory --host 0.0.0.0 --port $(PORT)

COMPOSE := $(shell command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo docker\ compose)

docker-build:
	docker build -t cqa:latest .

docker-run:
	$(COMPOSE) up

demo:
	# без ключа: replay, база data/demo.db, набор tests/e2e/fixtures/defence_set.json
	uv run python scripts/demo.py serve

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

backup:
	uv run python scripts/backup_db.py

results:
	# файл организаторов results/$(SET)/results.json; SET=dev|prod, для prod GROUP=<group_id>, несколько — GROUP="A B"; ARGS=--evaluate — сначала загрузить и оценить набор (scripts/results.py --help)
	uv run python scripts/results.py $(SET) $(foreach g,$(GROUP),--group $(g)) $(ARGS)
