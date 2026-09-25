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
if ! git diff --quiet HEAD -- frontend backend ml deploy scripts .dockerignore compose.server.yaml compose.handoff.yaml ||
   [[ -n $(git ls-files --others --exclude-standard -- frontend backend ml deploy scripts .dockerignore compose.server.yaml compose.handoff.yaml) ]]; then
  echo 'Есть локальные изменения приложения. Сначала сохраните и согласуйте их.' >&2
  exit 1
fi
[[ -f /srv/tramflow/index.html ]] || {
  echo 'Это обновление существующего сайта; первый запуск описан в deploy/README.md.' >&2
  exit 1
}
site_url=${SITE_URL:-https://tramflow.ru}
curl_auth=()
if [[ -n ${TRAMFLOW_NETRC_FILE:-} ]]; then
  [[ "$site_url" == https://* ]] || {
    echo 'Учётные данные разрешены только с HTTPS SITE_URL.' >&2; exit 1;
  }
  [[ -f "$TRAMFLOW_NETRC_FILE" && -r "$TRAMFLOW_NETRC_FILE" ]] || {
    echo 'Закрытый netrc-файл недоступен.' >&2; exit 1;
  }
  curl_auth=(--netrc-file "$TRAMFLOW_NETRC_FILE")
fi
# Fail before changing services if the protected site needs credentials.
curl --fail --silent --show-error --connect-timeout 5 --max-time 20 \
  "${curl_auth[@]}" "$site_url/" >/dev/null
# Prevent two deployments from switching files simultaneously.
exec 9>/var/lock/tramflow-deploy.lock
flock -n 9 || { echo 'Другой деплой уже выполняется.' >&2; exit 1; }
source deploy/handoff.sh
select_handoff
revision=$(git rev-parse --short HEAD)
stamp=$(date +%Y%m%d-%H%M%S)-$revision
backup=/opt/tramflow-backups/$stamp
mkdir -p "$backup"
chmod 700 "$backup"
git rev-parse HEAD > "$backup/target-commit.txt"
cp compose.server.yaml "$backup/compose.server.yaml"
if [[ -n ${TRAMFLOW_HANDOFF_HOST_DIR:-} ]]; then
  cp compose.handoff.yaml "$backup/compose.handoff.yaml"
  printf '%s\n' "$TRAMFLOW_HANDOFF_HOST_DIR" > "$backup/target-handoff-path.txt"
fi
printf '%s\n' "$previous_handoff" > "$backup/previous-handoff-path.txt"
cp -a /srv/tramflow "$backup/frontend"
image_id=$("${compose[@]}" images -q backend)
if [[ -n "$image_id" ]]; then
  if docker image inspect "$image_id" >/dev/null 2>&1; then
    docker image tag "$image_id" "tramflow-backend:backup-$stamp"
  else
    # A running container can survive removal of its original image.
    container_id=$("${compose[@]}" ps -q backend)
    [[ -n "$container_id" ]] || { echo 'Нет контейнера для резервной копии.' >&2; exit 1; }
    docker container commit "$container_id" "tramflow-backend:backup-$stamp"
  fi
fi
stage=$(mktemp -d /srv/tramflow-build.XXXXXX)
trap 'rm -rf -- "$stage"' EXIT
# prebuild fails before changing the running application if the map is missing/incomplete.
docker build -f deploy/frontend.Dockerfile --output "type=local,dest=$stage" .
cmp "$map" "$stage/map-local/network.json"
chmod -R a+rX "$stage"
"${compose[@]}" build backend
expected_run=''
if [[ -n ${TRAMFLOW_HANDOFF_HOST_DIR:-} ]]; then
  expected_run=$("${compose[@]}" run --rm --no-deps -T backend python -c \
    'from pathlib import Path; from backend.handoff.store import load_snapshot; print(load_snapshot(Path("/data/handoff")).run_id)')
  printf '%s\n' "$expected_run" > "$backup/target-handoff-run.txt"
fi
"${compose[@]}" up -d --wait --wait-timeout 120
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health
if [[ -n "$expected_run" ]]; then
  verify_handoff http://127.0.0.1:8000 "$expected_run"
fi
old=/srv/tramflow-before-$stamp
mv /srv/tramflow "$old"
if ! mv "$stage" /srv/tramflow; then
  mv "$old" /srv/tramflow
  exit 1
fi
# Keep the old directory and backend image for manual rollback.
curl --fail --silent --show-error "${curl_auth[@]}" "$site_url/" -o "$backup/served-index.html"
cmp /srv/tramflow/index.html "$backup/served-index.html"
curl --fail --silent --show-error "${curl_auth[@]}" "$site_url/map-local/network.json" -o "$backup/served-network.json"
cmp "$map" "$backup/served-network.json"
curl --fail --silent --show-error "${curl_auth[@]}" "$site_url/api/v1/health"
if [[ -n "$expected_run" ]]; then
  verify_handoff "$site_url" "$expected_run"
fi
printf '\nОбновлено до %s. Резервная копия: %s\n' "$revision" "$backup"
