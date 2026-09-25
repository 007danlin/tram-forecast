# Нагрузка handoff — 25.09.2026

**Целевая ступень 200 RPS прошла локально.** Принимающий по ТЗ — Игорь;
командная приёмка ожидается. Исполнитель Codex по поручению Даниэля.
Измерения 20:04–20:20 UTC (23:04–23:20 МСК), база `1e0bcf6` и рабочие
изменения задачи. Реальный пакет — `calendar-holiday-priority-v1.zip`,
SHA-256 `c5beb99d3fc10bca689b234caf71990378e9a705076481951b86edae8d61d5a9`;
[полный run и воспроизведение пакета](verification-priority-implementation.md).

## Окружение

Путь: k6 → Vite proxy → FastAPI, локальный Compose project
`tramflow-priority-load`. Это не измерение Caddy/VPS. Backend: **один worker**,
Python 3.12.10; frontend image Node 22.16.0. Docker inspect подтвердил NanoCpus
2 000 000 000, Memory 4 294 967 296, MemorySwap 4 294 967 296: 2 CPU / 4 GiB,
без дополнительного swap. Пакет смонтирован read-only.

Docker Desktop 4.70.0, Engine 29.4.0, Compose 5.1.2, Linux arm64.
Хост: 10 CPU, 32 GiB; Docker VM: 10 CPU, 8 321 712 128 байт (~7,75 GiB).
Нагрузчик и frontend находятся в той же VM, вне cgroup backend. Другой
локальный тестовый стек существовал во время замеров; хост не был выделенным.
Цифры нельзя переносить на сервер без повторения в его окружении.

k6 `grafana/k6:1.3.0`, digest
`sha256:3ddc8b1a33a2c3d8edc6e99b6a762ae36cba08788463458f5e6a7703e14eb77d`.
Размер ZIP 1 166 400 байт, исходного forecast CSV 1 214 242 байта.
Сырые JSON/logs/stats сохранены в `artifacts/load/priority-run-01/`.

## Метод и результат

Отдельный прогрев 50 RPS × 60 секунд, затем последовательные ступени
50/100/200 RPS × 5 минут. 70% day/hour, 20% month/day, 10% capabilities,
по одному HTTP-запросу на итерацию. Setup не входит в latency/RPS ниже.
Контроли вычислены из полного локального CSV, включая маршрут № 5.
Каждый измеренный ответ проверен по run, схеме, ключам и числам.

| Задано RPS | Запросов | Фактически RPS | p50, мс | p95, мс | p99, мс | Ошибки | Semantic | Dropped |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 | 15000 | 49.995 | 4.170 | 7.048 | 14.477 | 0% | 100% | 0 |
| 100 | 30001 | 99.994 | 2.592 | 5.003 | 21.706 | 0% | 100% | 0 |
| 200 | 60001 | 199.967 | 1.964 | 9.310 | 37.098 | 0% | 100% | 0 |

| Задано RPS | Day p50 / p95 / p99, мс | Month p50 / p95 / p99, мс |
|---:|---|---|
| 50 | 4.084 / 5.919 / 7.975 | 5.754 / 11.072 / 31.328 |
| 100 | 2.460 / 4.344 / 7.173 | 3.969 / 11.846 / 33.935 |
| 200 | 1.827 / 6.500 / 36.207 | 3.045 / 25.560 / 42.153 |

Все целевые пороги выполнены: общий и оба query p95 <300 мс, ошибки <1%,
semantic=100%, dropped=0. Небольшое отличие фактического RPS от заданного
связано с границами измеренного интервала и завершением последней итерации.
300 RPS не запускались: это необязательная ступень.

Отдельный большой export: 7 440 строк, HTTP 200, точные числа и X-Result-Id
совпали; **889.049 мс**, 3,439,814 байта.
Это один замер, не распределение export latency. Предшествующий большой query
проверен отдельно, размер JSON 2,243,610 байт.
Обычный контрольный day JSON — 9306 байт,
month JSON — 10301 байт; размеры меняются с фильтром.

## Ресурсы и пересоздание

Поток docker stats содержит 1 929 наблюдений каждого сервиса за весь прогон,
включая прогрев и export. Backend: максимальный наблюдённый CPU **91,36%**
одного CPU, то есть **45,68% лимита двух CPU**; docker memory до 53,27 MiB.
Frontend: до 35,75% CPU и 86,50 MiB. Это наблюдённые пики, не непрерывный
профиль. Docker memory и process RSS имеют разный учёт файлового кэша.
После RPS/export `/proc/1/status`: RSS 64 788 KiB, HWM 73 564 KiB,
VmSwap 0. OOMKilled=false, RestartCount=0, backend healthy.

Контрольный снимок во время 200 RPS: backend CPU 38,04%, Vite 16,99%,
k6 16,45% и 2,459 GiB RAM. Нагрузчик заметно занимает память общей VM;
этот снимок не объявляется его пиком. Влияние общей VM входит в измерения.

После нагрузки выполнены два `up --force-recreate --no-build --pull never`
только backend. В обоих случаях read-only mount и исходный run сохранились:

- Пересоздание 1: команда up → ready 1016.007 мс, первый query 4.417 мс.
- Пересоздание 2: команда up → ready 958.485 мс, первый query 4.043 мс.

Это холодный процесс с уже собранным образом и возможным файловым кэшем ОС;
не старт холодной VM и не серверный `deploy/update.sh`/rollback.
Последующие последовательные запросы сверяли исходные ключи и значения:

| Серия | Запросов | p50, мс | p95, мс | p99, мс |
|---|---:|---:|---:|---:|
| Одинаковые сутки | 30 | 2.747 | 3.917 | 4.139 |
| Разные сутки/маршруты | 32 | 2.532 | 4.733 | 5.625 |
| Разные месяцы/маршруты | 22 | 3.359 | 5.507 | 11.560 |

Эти дополнительные времена включают клиентский HTTP и JSON decode; приёмочные
latency берутся из k6. Кэша query нет, термины cache hit/miss не используются.

## Воспроизведение

Общий порядок, подготовка reference, прогрев, остановка и pinned image:
[tests/load/README](../tests/load/README.md). В этом прогоне для изоляции портов
использовался дополнительный файл `artifacts/load/priority-run-01/ports.yaml`:

```yaml
services:
  backend:
    ports: !override ["127.0.0.1:28080:8000"]
  frontend:
    ports: !override ["127.0.0.1:25173:5173"]
```

```sh
export TRAMFLOW_HANDOFF_HOST_DIR="$PWD/artifacts/releases/calendar-holiday-priority-v1"
docker compose -p tramflow-priority-load -f compose.yaml -f compose.handoff.yaml \
  -f compose.load.yaml -f artifacts/load/priority-run-01/ports.yaml up --build -d --wait
python -m tests.load.reference --release "$TRAMFLOW_HANDOFF_HOST_DIR" \
  --output artifacts/load/priority-run-01/reference.json
# Эту команду последовательно выполнить для RATE/DURATION/output:
# 50/60s/warmup.json, 50/5m/summary-50.json, 100/5m/summary-100.json,
# 200/5m/summary-200.json. При ненулевом exit code остановиться.
docker run --rm --network tramflow-priority-load_default \
  -v "$PWD/tests/load:/scripts:ro" -v "$PWD/artifacts/load/priority-run-01:/results" \
  -e REFERENCE=/results/reference.json -e BASE_URL=http://frontend:5173 \
  -e RATE=50 -e DURATION=60s grafana/k6:1.3.0 \
  run --summary-export /results/warmup.json /scripts/handoff.js
# После ступеней: отдельный run с -e MODE=export и /results/export.json.
python -m tests.load.lifecycle --project tramflow-priority-load \
  --base-url http://127.0.0.1:25173 \
  --reference artifacts/load/priority-run-01/reference.json \
  --compose-file compose.yaml --compose-file compose.handoff.yaml \
  --compose-file compose.load.yaml --compose-file artifacts/load/priority-run-01/ports.yaml \
  --output artifacts/load/priority-run-01/lifecycle.json
```

При повторе выбрать новый каталог результатов. Начальный короткий smoke выявил
403 на Docker hostname Vite; load-overlay теперь разрешает `frontend`.
Обычная конфигурация приложения не расширена. Полные ступени выше проведены
после исправления. Настройка кэша/дополнительных workers для достижения порогов
не потребовалась. Публичный сервер не нагружался и не изменялся.

После проверки локальный стек оставлен для просмотра по `http://127.0.0.1:25173`.
Остановить только его: `docker compose -p tramflow-priority-load -f compose.yaml down`.
