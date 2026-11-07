#!/usr/bin/env bash
# Публикация репозитория: только после проверки всей истории и свежего клона
# и только с подтверждением капитана — ввода точного имени репозитория
# (eval-and-delivery design, решение 13). Отменить открытую историю нельзя.
set -euo pipefail

if [ $# -ne 1 ] || [[ "$1" != */* ]]; then
  echo "использование: $0 <owner/repo>" >&2
  exit 2
fi
repo=$1
url="https://github.com/$repo.git"

run_tool() { # run_tool <скрипт> <аргументы...>: из PATH или рядом с publish.sh
  local name=$1
  shift
  if command -v "$name" >/dev/null 2>&1; then
    "$name" "$@"
  else
    "$(dirname "$0")/$name" "$@"
  fi
}

echo "проверка 1 из 2: секреты и данные во всей истории"
run_tool secret_scan.sh --history
echo "проверка 2 из 2: свежий клон по шагам README"
run_tool fresh_clone.sh "$url"

printf 'публикация необратима. введите имя репозитория (%s) для подтверждения: ' "$repo"
read -r answer
if [ "$answer" != "$repo" ]; then
  echo "ошибка: имя не совпало, публикация отменена" >&2
  exit 1
fi

gh repo edit "$repo" --visibility public --accept-visibility-change-consequences

anon_dir=$(mktemp -d "${TMPDIR:-/tmp}/cqa-anon-clone.XXXXXX")
if ! GIT_TERMINAL_PROMPT=0 git clone "$url" "$anon_dir/repo"; then
  echo "ошибка: анонимный клон не прошёл, репозиторий не открыт" >&2
  exit 1
fi

echo "репозиторий опубликован: https://github.com/$repo"
