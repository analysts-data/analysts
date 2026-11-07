#!/usr/bin/env bash
# Защищённые пути и файлы агентов (шаг make check и шаг CI).
# Использование: scripts/protected_paths.sh [--allow] [--base <ref>]
#   --allow       у PR есть метка human-ok (в CI это определяет шаг с gh pr view)
#   --base <ref>  база сравнения, по умолчанию origin/main
# Правка защищённых путей без --allow — ошибка в CI и предупреждение локально
# (окончательно метку проверяет CI). Отслеживаемые файлы агентов — всегда
# ошибка, даже символические ссылки и даже с --allow: openspec/, .claude/, .pi/,
# AGENTS.md, AGENT.md, CLAUDE.md не хранятся в git.
set -euo pipefail

allow=0
base=origin/main
while [ $# -gt 0 ]; do
  case "$1" in
    --allow) allow=1 ;;
    --base) base=$2; shift ;;
    *) echo "ошибка: неизвестный аргумент $1" >&2; exit 2 ;;
  esac
  shift
done
if [ "${PROTECTED_ALLOW:-0}" = "1" ]; then
  allow=1
fi

status=0

agent_files=$(git ls-files -- openspec .claude .pi AGENTS.md AGENT.md CLAUDE.md)
if [ -n "$agent_files" ]; then
  echo "ошибка: файлы агентов в git, уберите их из индекса (общие файлы — через wt.sh):" >&2
  printf '%s\n' "$agent_files" >&2
  status=1
fi

changed=
if git rev-parse -q --verify "$base^{commit}" >/dev/null 2>&1; then
  changed=$(git diff --name-only "$base...HEAD")
else
  echo "предупреждение: нет базы $base, сравнение пропущено" >&2
fi

hits=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  case "$f" in
    eval/gold|eval/gold/*|eval/thresholds.yaml|eval/baseline.json|\
    design/contract.md|design/ports.md|.github|.github/*)
      hits="$hits$f\n" ;;
  esac
done <<EOF
$changed
EOF

if [ -n "$hits" ]; then
  if [ "$allow" -eq 1 ]; then
    echo "защищённые пути изменены с меткой human-ok:"
    printf "$hits"
  elif [ "${GITHUB_ACTIONS:-false}" = "true" ]; then
    echo "ошибка: защищённые пути изменены без метки human-ok на PR:" >&2
    printf "$hits" >&2
    status=1
  else
    echo "предупреждение: защищённые пути изменены, PR нужна метка human-ok:" >&2
    printf "$hits" >&2
  fi
fi

exit $status
