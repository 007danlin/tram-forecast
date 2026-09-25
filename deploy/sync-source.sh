#!/usr/bin/env bash
# Check by default; --apply updates a clean main checkout, never services.
set -euo pipefail
mode=${1:---check}
[[ $# -le 1 && ( "$mode" == --check || "$mode" == --apply ) ]] || {
  echo 'Использование: bash deploy/sync-source.sh [--check|--apply]' >&2; exit 2;
}
cd "$(git rev-parse --show-toplevel)"
[[ $(git branch --show-current) == main ]] || {
  echo 'Синхронизация сервера разрешена только из ветки main.' >&2; exit 1;
}
[[ -z $(git status --porcelain) ]] || {
  echo 'Checkout содержит изменения или неотслеживаемые файлы. Сначала сохраните их отдельно.' >&2; exit 1;
}
git fetch origin main
before=$(git rev-parse HEAD)
target=$(git rev-parse refs/remotes/origin/main)
if [[ "$before" == "$target" ]]; then
  printf 'Код уже соответствует origin/main: %s\n' "$target"
  exit 0
fi
kind=fast-forward
if ! git merge-base --is-ancestor "$before" "$target"; then
  tree=$(git rev-parse 'HEAD^{tree}')
  equivalent=$(git log --format='%H %T' "$target" | awk -v tree="$tree" '$2 == tree && match_id == "" {match_id=$1} END {print match_id}')
  [[ -n "$equivalent" ]] || {
    echo 'История разошлась, и исходное дерево VPS не найдено в истории origin/main. Автоматический переход запрещён.' >&2
    exit 1
  }
  kind=rewritten-history
  printf 'Прежний код сохранён в новой истории: %s\n' "$equivalent"
fi
printf 'Переход %s: %s -> %s\n' "$kind" "$before" "$target"
if [[ "$mode" == --check ]]; then
  echo 'Проверка завершена; checkout и сервисы не изменены. Для перехода повторите с --apply.'
  exit 0
fi
# Recheck after fetch, before changing any local ref or source file.
[[ $(git rev-parse HEAD) == "$before" && -z $(git status --porcelain) ]] || {
  echo 'Checkout изменился во время проверки. Переход отменён.' >&2; exit 1;
}
backup="refs/tramflow-backups/before-sync-$(date -u +%Y%m%dT%H%M%SZ)-$$"
git update-ref "$backup" "$before" ''
if [[ "$kind" == fast-forward ]]; then
  git merge --ff-only "$target"
else
  # --keep refuses conflicting worktree changes; no --hard, clean or force push.
  git reset --keep "$target"
fi
printf 'Исходники обновлены до %s. Старая версия сохранена: %s\n' "$target" "$backup"
echo 'Работающие сервисы не менялись; следующим шагом выполните deploy/update.sh.'
