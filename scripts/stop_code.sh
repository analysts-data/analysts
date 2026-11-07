#!/usr/bin/env bash
# Стоп-код контрольного дня: после 2026-11-08T12:00:00+05:00 код не меняется.
# После этого времени шаг make check проходит только на ветке, неотличимой
# от origin/main. Время подменяется переменной CQA_NOW (только для тестов,
# в Settings её нет — design/ports.md).
set -euo pipefail

deadline="2026-11-08T12:00:00+05:00"

# '+05:00' -> '+0500' и 'Z' -> '+0000': один формат для GNU и BSD date
norm() {
  printf '%s' "$1" | sed -E 's/([+-][0-9]{2}):([0-9]{2})$/\1\2/; s/Z$/+0000/'
}

epoch() { # секунды с эпохи; GNU date сначала, BSD date (macOS) — запасной
  local ts out
  ts=$(norm "$1")
  out=$(date -u -d "$ts" +%s 2>/dev/null) || out=""
  if [ -n "$out" ]; then
    printf '%s' "$out"
    return 0
  fi
  date -u -j -f '%Y-%m-%dT%H:%M:%S%z' "$ts" +%s
}

now_ts=${CQA_NOW:-$(date +%Y-%m-%dT%H:%M:%S%z)}
if [ "$(epoch "$now_ts")" -lt "$(epoch "$deadline")" ]; then
  exit 0
fi

base=origin/main
if ! git rev-parse -q --verify "$base^{commit}" >/dev/null 2>&1; then
  echo "предупреждение: нет ветки $base, сравнить не с чем" >&2
  exit 0
fi

if [ "$(git rev-parse HEAD)" = "$(git rev-parse "$base")" ]; then
  exit 0
fi

echo "стоп-код 12:00, код не меняется: $(git rev-parse --abbrev-ref HEAD) отличается от $base" >&2
exit 1
