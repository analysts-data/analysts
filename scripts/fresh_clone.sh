#!/usr/bin/env bash
# Свежий клон по шагам README: репозиторий должен запускаться без ручных правок.
# Каталог клона не удаляется (rm -rf запрещён правилами), временную папку
# чистит система; путь печатается в конце. PORT=<порт> (умолчание 8000) — если
# на 8000 уже работает сервер команды.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "использование: $0 <url|путь репозитория>" >&2
  exit 2
fi
repo_url=$1
port=${PORT:-8000}
base="http://127.0.0.1:$port"
# иначе health ответит чужой сервер, а make run клона упадёт незаметно
if curl -sf "$base/api/health" >/dev/null 2>&1; then
  echo "ошибка: порт $port занят, остановите сервер или задайте PORT=<свободный порт>" >&2
  exit 1
fi

server_pid=""
stop_server() {
  if [ -n "$server_pid" ]; then
    kill "$server_pid" 2>/dev/null || true
    pkill -P "$server_pid" 2>/dev/null || true
  fi
}
trap stop_server EXIT

step() { # step <имя шага README> <команда...>: провал — ненулевой код и имя шага
  local name=$1
  shift
  echo "шаг: $name"
  if ! "$@"; then
    echo "ошибка: шаг «$name» не пройден" >&2
    exit 1
  fi
}

dir=$(mktemp -d "${TMPDIR:-/tmp}/cqa-fresh-clone.XXXXXX")
step "git clone" git clone "$repo_url" "$dir/repo"
cd "$dir/repo"

step "uv sync" uv sync
step "cp .env.example .env" cp .env.example .env
step "make check" make check

echo "шаг: make run"
make run PORT="$port" &
server_pid=$!

health=""
for _ in $(seq 1 60); do
  body=$(curl -sf "$base/api/health") || { sleep 1; continue; }
  if printf '%s' "$body" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; then
    health=$body
    break
  fi
  sleep 1
done
if [ -z "$health" ]; then
  echo "ошибка: шаг «curl /api/health» не пройден" >&2
  exit 1
fi
page=$(curl -sf "$base/") || true
case "$page" in
  *"<cqa-app"*) ;;
  *)
    echo "ошибка: шаг «curl /» не пройден: на странице нет <cqa-app>" >&2
    exit 1
    ;;
esac

stop_server
server_pid=""

echo "свежий клон проверен, шаги README пройдены"
echo "каталог клона: $dir"
