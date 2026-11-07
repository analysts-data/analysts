#!/usr/bin/env bash
# Поиск секретов в отслеживаемых файлах (шаг make check).
# Шаблоны — openspec/changes/bootstrap-harness/design.md, решение 5.
# Исключения: .env.example (имена переменных без значений) и сам скрипт,
# который содержит шаблоны в исходнике.
set -euo pipefail

[ -n "$(git ls-files)" ] || exit 0

set +e
git grep -nIiE \
  -e 'sig=' \
  -e 'apikey_' \
  -e 'gho_' \
  -e 'sk-[0-9a-fA-F]{16,}' \
  -e 'powerplatform\.com' \
  -e 'dynamics\.com/api/filedownload' \
  -- . ':(exclude).env.example' ':(exclude)scripts/secret_scan.sh'
status=$?
set -e

if [ "$status" -gt 1 ]; then
  exit "$status"
fi
if [ "$status" -eq 0 ]; then
  echo "ошибка: в отслеживаемых файлах найдены сигнатуры секретов (см. выше)" >&2
  exit 1
fi
exit 0
