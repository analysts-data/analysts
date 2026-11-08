#!/usr/bin/env bash
# Поиск секретов в отслеживаемых файлах (шаг make check).
# Шаблоны — openspec/changes/bootstrap-harness/design.md, решение 5.
# Исключения: .env.example (имена переменных без значений) и сам скрипт,
# который содержит шаблоны в исходнике.
#
# scripts/secret_scan.sh --history проверяет всю историю всех веток:
# шаблоны секретов по содержимому каждого коммита и запрещённые пути
# (.env, data/, *.mp3, *.wav, *.db, *.sqlite) по git ls-tree каждого коммита.
set -euo pipefail

if [ "${1:-}" = "--history" ]; then
  mode=history
  shift
else
  mode=worktree
fi
if [ $# -gt 0 ]; then
  echo "использование: $0 [--history]" >&2
  exit 2
fi

if [ "$mode" = "worktree" ]; then
  [ -n "$(git ls-files)" ] || exit 0
else
  git rev-parse -q --verify HEAD >/dev/null 2>&1 || exit 0 # пустая история
fi

grep_secrets() { # "$@" — дополнительные аргументы git grep
  git grep -nIiE \
    -e 'sig=' \
    -e 'apikey_' \
    -e 'gho_' \
    -e 'sk-[0-9a-fA-F]{16,}' \
    -e 'powerplatform\.com' \
    -e 'dynamics\.com/api/filedownload' \
    "$@"
}
EXCLUDES=(':(exclude).env.example' ':(exclude)scripts/secret_scan.sh')

status=0

if [ "$mode" = "worktree" ]; then
  [ -n "$(git ls-files)" ] || exit 0
  set +e
  grep_secrets -- . "${EXCLUDES[@]}"
  rc=$?
  set -e
  if [ "$rc" -gt 1 ]; then
    exit "$rc"
  fi
  if [ "$rc" -eq 0 ]; then
    echo "ошибка: в отслеживаемых файлах найдены сигнатуры секретов (см. выше)" >&2
    exit 1
  fi
  exit 0
fi

# --history: содержимое и пути каждого коммита всех веток
forbidden_path() { # выводит путь, если он запрещён
  case "$1" in
    .env|data/*|*.mp3|*.wav|*.db|*.sqlite) printf '%s' "$1" ;;
  esac
}

# Фальшивые значения из ранних тестов (в HEAD их уже нет): не секреты, историю не переписываем.
FAKE='storage\.test/rec\.mp3\?sig=abc|CQA_ORG_SIG=\{SIG\}example'

for commit in $(git rev-list --all); do
  set +e
  out=$(grep_secrets "$commit" -- . "${EXCLUDES[@]}")
  rc=$?
  set -e
  if [ "$rc" -gt 1 ]; then
    exit "$rc"
  fi
  out=$(printf '%s\n' "$out" | grep -vE "$FAKE" | grep . || true)
  if [ -n "$out" ]; then
    printf '%s\n' "$out"
    echo "ошибка: в истории ($commit) найдены сигнатуры секретов (см. выше)" >&2
    status=1
  fi
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    bad=$(forbidden_path "$f")
    if [ -n "$bad" ]; then
      echo "ошибка: запрещённый путь в истории: $commit $bad" >&2
      status=1
    fi
  done < <(git ls-tree -r --name-only "$commit")
done

exit $status
