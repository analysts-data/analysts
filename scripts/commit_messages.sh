#!/usr/bin/env bash
# Сообщения коммитов ветки без следов ИИ-соавторства (запрещено AGENTS.md).
# Использование: scripts/commit_messages.sh [--base <ref>]
#   --base <ref>  база сравнения, по умолчанию origin/main
set -euo pipefail

base=origin/main
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base=$2; shift ;;
    *) echo "ошибка: неизвестный аргумент $1" >&2; exit 2 ;;
  esac
  shift
done

if ! git rev-parse -q --verify "$base^{commit}" >/dev/null 2>&1; then
  echo "предупреждение: нет базы $base, проверка сообщений пропущена" >&2
  exit 0
fi

status=0
for commit in $(git rev-list "$base..HEAD"); do
  if git log -1 --format=%B "$commit" | grep -qiE 'co-authored-by|generated with'; then
    subject=$(git log -1 --format=%s "$commit")
    echo "ошибка: $commit «$subject» — запрещённый трейлер ИИ в сообщении коммита" >&2
    status=1
  fi
done
exit $status
