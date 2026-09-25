# Нагрузка handoff

Инструментарий реализован; результаты на реальном пакете пока не получены.
Версия: k6 **1.3.0**, Docker-образ `grafana/k6:1.3.0`. Один worker backend,
2 vCPU, 4 GiB, swap выключен через `memswap_limit: 4g`. На Docker Desktop
учитывать лимиты всей VM и расход нагрузки отдельно. Не запускать на публичном
VPS без отдельного поручения. Секрет AUTHORIZATION задаётся только в закрытом окружении.

Из корня, после импорта настоящего release:

```sh
export TRAMFLOW_HANDOFF_HOST_DIR="$PWD/artifacts/releases/ui-first-run"
docker compose -f compose.yaml -f compose.handoff.yaml -f compose.load.yaml config --quiet
docker compose -f compose.yaml -f compose.handoff.yaml -f compose.load.yaml up --build -d --wait
mkdir -p artifacts/load/run-01
python -m tests.load.reference --release "$TRAMFLOW_HANDOFF_HOST_DIR" --output artifacts/load/run-01/reference.json
export REFERENCE="$PWD/artifacts/load/run-01/reference.json"
export BASE_URL=http://127.0.0.1:5173
k6 version
docker version
docker info
container=$(docker compose -f compose.yaml ps -q backend)
docker inspect "$container" --format '{{json .HostConfig}}' > artifacts/load/run-01/limits.json
docker stats "$container" --format '{{json .}}' > artifacts/load/run-01/stats.jsonl &
stats_pid=$!
# Отдельный прогрев.
k6 run -e RATE=50 -e DURATION=60s --summary-export artifacts/load/run-01/warmup.json tests/load/handoff.js
# Выполнять по очереди; код ошибки k6 запрещает повышение нагрузки.
for rate in 50 100 200; do
  k6 run -e RATE="$rate" -e DURATION=5m --summary-export "artifacts/load/run-01/summary-$rate.json" tests/load/handoff.js || break
done
# Отдельный export 7 440 строк; не смешивается с query.
k6 run -e MODE=export --summary-export artifacts/load/run-01/export.json tests/load/handoff.js
kill "$stats_pid"
docker inspect "$container" --format '{{json .State}} {{.RestartCount}}' > artifacts/load/run-01/state.txt
docker compose -f compose.yaml -f compose.handoff.yaml -f compose.load.yaml down
```

При необходимости `300 RPS` запускать только после успешной ступени 200.
Нагрузка содержит 70% day/hour, 20% month/day, 10% capabilities; каждая
итерация выполняет один HTTP-запрос. Setup сверяет ready/run/полный период и
контрольный запрос, измеряет первый query отдельно. Все числа сверяются с
контролями, вычисленными из локального CSV, включая baseline № 5.
Измеренные запросы помечены phase=measured; setup не входит в их latency.
Контроли включают повторяющиеся и разные фильтры; кэш не реализован,
названия hit/miss не используются. Холодный старт: засечь время от `up` до
первого ready=200 отдельно от RPS (например, `/usr/bin/time` вокруг up+curl).

k6 RPS: использовать `measured_requests.rate` и `count`, рядом записать
запрошенный RATE, длительность и `dropped_iterations`. Порог 200 RPS:
общий и каждый query p95 <300 мс, HTTP-ошибки <1%, semantic=100%, dropped=0.
Записать p50 (`med`), p99, worker count, размер пакета и ответа, CPU raw % и
CPU/200 как долю двух CPU, RSS/пик памяти, OOM/restarts, CPU/RAM хоста/VM,
влияние нагрузчика. Замеры через Vite не выдавать за Caddy.

Контейнерный k6 требует общей сети и адреса `http://frontend:5173`, а также
read-only mounts скрипта и REFERENCE. `127.0.0.1` внутри k6-контейнера
не является хостом. Для первой проверки используйте хостовый k6.
Сводка — `docs/verification-load.md`; исходные JSON остаются в `artifacts/`.
[Семантика constant-arrival-rate](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/).
