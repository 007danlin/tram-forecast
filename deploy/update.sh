#!/usr/bin/env bash
# Run after git pull; all builds use the current checkout.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $(id -u) != 0 ]]; then
  echo 'Запустите на VPS под root.' >&2
  exit 1
fi
[[ $(git branch --show-current) == main ]] || {
  echo 'Серверное обновление разрешено только из ветки main.' >&2
  exit 1
}
map=frontend/public/map-local/network.json
git ls-files --error-unmatch "$map" >/dev/null || {
  echo 'Готовая карта ещё не добавлена в Git. Деплой остановлен.' >&2
  exit 1
}
if ! git diff --quiet HEAD -- frontend backend ml deploy compose.server.yaml; then
  echo 'Есть локальные изменения приложения. Сначала сохраните и согласуйте их.' >&2
  exit 1
fi
[[ -f /srv/tramflow/index.html ]] || {
  echo 'Это обновление существующего сайта; первый запуск описан в deploy/README.md.' >&2
  exit 1
}
# Prevent two deployments from switching files simultaneously.
exec 9>/var/lock/tramflow-deploy.lock
flock -n 9 || { echo 'Другой деплой уже выполняется.' >&2; exit 1; }
revision=$(git rev-parse --short HEAD)
stamp=$(date +%Y%m%d-%H%M%S)-$revision
backup=/opt/tramflow-backups/$stamp
mkdir -p "$backup"
chmod 700 "$backup"
git rev-parse HEAD > "$backup/target-commit.txt"
cp compose.server.yaml "$backup/compose.server.yaml"
cp -a /srv/tramflow "$backup/frontend"
image_id=$(docker compose -f compose.server.yaml images -q backend)
if [[ -n "$image_id" ]]; then
  docker image tag "$image_id" "tramflow-backend:backup-$stamp"
fi
stage=$(mktemp -d /srv/tramflow-build.XXXXXX)
trap 'rm -rf -- "$stage"' EXIT
# prebuild fails before changing the running application if the map is missing/incomplete.
docker build -f deploy/frontend.Dockerfile --output "type=local,dest=$stage" .
cmp "$map" "$stage/map-local/network.json"
chmod -R a+rX "$stage"
docker compose -f compose.server.yaml build backend
docker compose -f compose.server.yaml up -d --wait --wait-timeout 120
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health
old=/srv/tramflow-before-$stamp
mv /srv/tramflow "$old"
if ! mv "$stage" /srv/tramflow; then
  mv "$old" /srv/tramflow
  exit 1
fi
# Keep the old directory and backend image for manual rollback.
site_url=${SITE_URL:-https://tramflow.ru}
curl --fail --silent --show-error "$site_url/" -o "$backup/served-index.html"
cmp /srv/tramflow/index.html "$backup/served-index.html"
curl --fail --silent --show-error "$site_url/map-local/network.json" -o "$backup/served-network.json"
cmp "$map" "$backup/served-network.json"
curl --fail --silent --show-error "$site_url/api/v1/health"
printf '\nОбновлено до %s. Резервная копия: %s\n' "$revision" "$backup"
