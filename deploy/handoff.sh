#!/usr/bin/env bash
# Sourced by update.sh; no service mutation here.
select_handoff() {
  compose=(docker compose -f compose.server.yaml)
  previous_handoff=''
  local current
  current=$("${compose[@]}" ps -q backend)
  if [[ -n "$current" ]]; then
    previous_handoff=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data/handoff"}}{{.Source}}{{end}}{{end}}' "$current")
  fi
  # Explicit environment selects a new release. Otherwise retain the running
  # mount, including on a second update in a fresh shell.
  if [[ -z ${TRAMFLOW_HANDOFF_HOST_DIR:-} && -n "$previous_handoff" ]]; then
    export TRAMFLOW_HANDOFF_HOST_DIR="$previous_handoff"
  fi
  if [[ -n ${TRAMFLOW_HANDOFF_HOST_DIR:-} ]]; then
    [[ "$TRAMFLOW_HANDOFF_HOST_DIR" == /* && -d "$TRAMFLOW_HANDOFF_HOST_DIR" && -f "$TRAMFLOW_HANDOFF_HOST_DIR/receipt.json" ]] || {
      echo 'Требуется абсолютный путь к импортированному handoff-пакету.' >&2; return 1;
    }
    export TRAMFLOW_HANDOFF_HOST_DIR
    compose+=(-f compose.handoff.yaml)
  elif [[ -n "$current" ]] && docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$current" | grep -q '^TRAMFLOW_HANDOFF_DIR=.'; then
    echo 'У backend настроен нестандартный handoff mount. Укажите TRAMFLOW_HANDOFF_HOST_DIR явно.' >&2
    return 1
  fi
  "${compose[@]}" config --quiet
}

verify_handoff() {
  local url=$1 expected=$2
  local auth=()
  if [[ "$url" == https://* ]]; then auth=("${curl_auth[@]}"); fi
  curl --fail --silent --show-error --connect-timeout 5 --max-time 20 \
    "${auth[@]}" "$url/api/v2/handoff/ready" | \
    "${compose[@]}" exec -T backend python -c \
    'import json,sys; r=json.load(sys.stdin); assert r["status"] == "ready" and r["forecast_run_id"] == sys.argv[1], "Unexpected handoff run"' "$expected"
}
