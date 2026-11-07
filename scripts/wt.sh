#!/usr/bin/env bash
# Worktree на агента (AGENTS.md): scripts/wt.sh new <change> <slug> | rm <change> <slug>
#
# new: fetch origin main, worktree .worktrees/<change>-<slug> от origin/main,
#      ветка feat/<change>-<slug>, символические ссылки на openspec/, AGENTS.md,
#      CLAUDE.md, .claude/, .pi/ из основной копии, затем uv sync.
#      WT_SKIP_SYNC=1 пропускает uv sync (для тестов без сети).
# rm:  удалить worktree и слитую ветку.
set -euo pipefail

usage() {
  echo "использование: $0 new|rm <change> <slug>" >&2
  exit 2
}

[ $# -eq 3 ] || usage
cmd=$1
name="$2-$3"
branch="feat/$name"
wt=".worktrees/$name"

# Корень основной копии (не текущего worktree) — оттуда общие файлы и .worktrees/
main_root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
cd "$main_root"

case "$cmd" in
new)
  git fetch origin main
  if [ -e "$wt" ]; then
    echo "ошибка: $wt уже существует" >&2
    exit 1
  fi
  if git rev-parse -q --verify "refs/heads/$branch" >/dev/null; then
    echo "ошибка: ветка $branch уже существует" >&2
    exit 1
  fi
  git worktree add -b "$branch" "$wt" origin/main
  for p in openspec AGENTS.md CLAUDE.md .claude .pi; do
    if [ -e "$main_root/$p" ] && [ ! -e "$wt/$p" ]; then
      ln -s "$main_root/$p" "$wt/$p"
    fi
  done
  if [ "${WT_SKIP_SYNC:-0}" = "1" ]; then
    echo "uv sync пропущен (WT_SKIP_SYNC=1)"
  elif command -v uv >/dev/null 2>&1; then
    (cd "$wt" && uv sync)
  else
    echo "предупреждение: uv не найден, зависимости не установлены" >&2
  fi
  ;;
rm)
  if [ ! -d "$wt" ]; then
    echo "ошибка: $wt не существует" >&2
    exit 1
  fi
  # без --force: незакоммиченная работа остаётся, git объясняет причину (ссылки общих файлов
  # и .venv в .gitignore удалению не мешают)
  git worktree remove "$wt"
  if ! git branch -d "$branch" 2>/dev/null; then
    echo "предупреждение: ветка $branch не слита, оставлена" >&2
  fi
  ;;
*)
  usage
  ;;
esac
