FROM python:3.12-slim

# ffmpeg — разбор аудио звонков; build-essential и cmake — сборка praat-parselmouth из исходников
# на платформах без готового wheel (linux/arm64)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

# зависимости отдельным слоем: uv.lock меняется реже кода; инструмент сборки после установки удаляем
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    && apt-get purge -y build-essential cmake \
    && rm -rf /var/lib/apt/lists/* /root/.cache

# приложение и файлы рантайма: интерфейс (web/), сид-чек-лист и кассеты replay (tests/), карта критериев (results/)
COPY src ./src
COPY web ./web
COPY tests/fixtures/checklist_v3.json ./tests/fixtures/
COPY tests/cassettes ./tests/cassettes
COPY results ./results

# установка самого проекта (editable) поверх готовых зависимостей
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# не root: база data/cqa.db пишется от имени непривилегированного пользователя
RUN useradd --create-home cqa \
    && mkdir -p /app/data \
    && chown -R cqa:cqa /app
USER cqa

EXPOSE 8000
# тот же запуск, что make run, но без --reload и на всех интерфейсах
CMD ["uv", "run", "--no-sync", "uvicorn", "cqa.http.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
