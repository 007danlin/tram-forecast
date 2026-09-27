# B2: расчёт из весов в Docker

Отдельный образ исполняет существующий `python -m ml`: forecast/submission
из сохранённого `calendar_interaction_ensemble`. Он не содержит весов, sample,
готовых ответов, backend или интерфейса. Обучение и скачивание погоды при сборке
и проверке не вызываются. HTTP по-прежнему обслуживает готовый handoff.
[Результаты и ограничения приёмки](../../docs/submission-final/docker-inference-verification.md).

Нужны Docker Engine, Python **3.11+ только со стандартной библиотекой** для
проверочного скрипта и отдельно полученный доверенный B2/G0. Host-venv, sklearn
или host Python для ML не нужны. Сеть нужна при первой сборке; готовый образ
рассчитывает прогноз с `--network none`. Проверена платформа `linux/arm64`;
другие платформы требуют такой же приёмки без ослабления сравнения.

## Подготовка и сборка

Команды из корня исходников (после распаковки `sources.zip` — `tram-forecast/`).
`B2_G0` — каталог с исходным `bundle-manifest.json`, `model/`, `template.csv`,
`champion.csv`, `forecast-float.csv`. Подготовка проверяет **все** записи G0,
manifest модели и закреплённые SHA B2, затем копирует байты без изменений.
Нужны новые каталоги: существующие результаты и отчёты не перезаписываются.

```sh
export B2_G0="/absolute/path/champion-b2-g0-20260926-r01"
export INFERENCE_WORK="$PWD/artifacts/inference-docker/my-new-run"
python3 -m scripts.verify_container_inference prepare \
  --g0 "$B2_G0" --output-dir "$INFERENCE_WORK/prepared"
docker build --platform linux/arm64 --progress plain \
  -f ml/inference/Dockerfile -t tramflow-inference:b2 .
export MODEL_INPUT="$INFERENCE_WORK/prepared/model"
export SAMPLE_INPUT="$INFERENCE_WORK/prepared/input/test_submission.csv"
```

В готовом локальном комплекте `inputs/model/`, `inputs/test_submission.csv` и
`references/` уже выделены и связаны SHA256SUMS. Тогда задайте `MODEL_INPUT` и
`SAMPLE_INPUT` этими абсолютными путями; повторная подготовка G0 не нужна.
Данные/веса/эталоны отсутствуют в `sources.zip`. Не монтируйте весь комплект,
G0 или репозиторий в вычислительный контейнер.

Образ закреплён на Python **3.12.14-slim-bookworm** и OCI index digest
`sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e`.
Все 15 pins из `ml/requirements-inference.txt` сохранены. Установка требует
готовых wheels (`--only-binary=:all:`), затем выполняет `pip check`.

## Прямой запуск существующего CLI

Оба запуска независимы, каждый десериализует проверенную модель и рассчитывает
прогноз. В `/model` находятся ровно четыре файла модели. Sample монтируется
отдельным файлом, только для чтения; эталоны не передаются.

```sh
mkdir "$INFERENCE_WORK/manual"
mkdir "$INFERENCE_WORK/manual/forecast" "$INFERENCE_WORK/manual/submission"
docker run --rm --network none --cpus 2 --memory 4g --memory-swap 4g \
  --read-only --tmpfs /tmp:rw,nosuid,size=64m \
  --mount "type=bind,src=$MODEL_INPUT,dst=/model,readonly" \
  --mount "type=bind,src=$INFERENCE_WORK/manual/forecast,dst=/output" \
  tramflow-inference:b2 forecast --artifact-dir /model \
  --start 2025-11-01 --end 2025-12-31 --output /output/forecast.csv
docker run --rm --network none --cpus 2 --memory 4g --memory-swap 4g \
  --read-only --tmpfs /tmp:rw,nosuid,size=64m \
  --mount "type=bind,src=$MODEL_INPUT,dst=/model,readonly" \
  --mount "type=bind,src=$SAMPLE_INPUT,dst=/input/test_submission.csv,readonly" \
  --mount "type=bind,src=$INFERENCE_WORK/manual/submission,dst=/output" \
  tramflow-inference:b2 submission --artifact-dir /model \
  --template /input/test_submission.csv --scope sample \
  --output /output/submission.csv --preflight-output /output/submission.preflight.json
```

CLI включает обе даты. Forecast сохраняет float, reference, lower/upper,
priority и status. Submission один раз округляет `floor(x + 0.5)` после ансамбля,
сохраняет порядок sample, UTF-8 и `;`. № 5 — нулевой fallback. Модель/веса и
параметры не меняются. Контейнеры наследуют из образа пять ограничителей потоков
со значением 2; `memory-swap=memory` запрещает дополнительный swap.

## Полная автоматизированная приёмка

```sh
python3 -m scripts.verify_container_inference run \
  --image tramflow-inference:b2 --model-dir "$MODEL_INPUT" \
  --template "$SAMPLE_INPUT" --output-dir "$INFERENCE_WORK/acceptance"
# Отдельный процесс, только после завершения всех вычислительных контейнеров:
python3 -m scripts.verify_container_inference compare \
  --run-dir "$INFERENCE_WORK/acceptance" \
  --reference-forecast "$INFERENCE_WORK/prepared/references/forecast.csv" \
  --reference-submission "$INFERENCE_WORK/prepared/references/submission.csv" \
  --output-dir "$INFERENCE_WORK/comparison"
```

Для готового комплекта укажите CSV из его `references/`. `run` вообще не
принимает эталонных файлов; tag разрешается в неизменяемый image ID один раз.
Для каждого вызова создаётся новый контейнер и пустой выходной подкаталог:
даже float предыдущего вызова недоступен процессу submission. Сохраняются argv, exit codes,
stdout/stderr, inspect с реальными mounts, образ/архитектура, hashes до/после,
preflight и замеры. Удаляются только контейнеры, созданные этим запуском.

Проверяются два полных расчёта, три отдельных дня (01.11, 15.11, 31.12),
шаблон с заменённой `prediction`, отсутствующий/повреждённый model, неверная
checksum, дубли ключей sample и отказ перезаписывать forecast/submission/preflight.
`measure.py` запускает тот же CLI через `runpy` и отклоняет Python-вызовы
`fit`/`partial_fit`/`fit_transform` модулей ML/sklearn. Это инструмент приёмки,
не изменение модели; обычный entrypoint остаётся `python -m ml`.

`compare` отдельно сверяет SHA, точные значения, статусы, ключи, порядок,
№ 5, однократное округление и дневные срезы. При расхождении возвращает exit 1,
сохраняет число отличий, max absolute/relative error и примеры в `report.json`.
Допуск **нулевой**, автоматического принятия численной близости нет. Успешный
`run` означает только выполнение сценариев; воспроизведение требует также
успешного `compare`. Некорректный вызов/повтор output возвращает ошибку;
существующий отчёт не меняется.

## Передать новый расчёт в локальный веб

Это отдельный шаг после успешного сравнения. Упаковщик выполняется в backend
образе; только его исходники подключаются дополнительно. Нужен Docker Compose
≥2.24.4, свободные **15187/18107**, новый `web/release`. Существующие проекты
и публичный сервер эти команды не меняют. Мониторинг отключён в явной локальной
накладке. Веб-проверка использует отдельную bridge-сеть и loopback-порты;
режим `--network none` относится к вычислительным контейнерам.

```sh
docker compose -p tramflow-inference-qa -f compose.yaml build
mkdir "$INFERENCE_WORK/web"
docker run --rm --network none \
  --mount "type=bind,src=$PWD/scripts,dst=/app/scripts,readonly" \
  --mount "type=bind,src=$MODEL_INPUT,dst=/model,readonly" \
  --mount "type=bind,src=$INFERENCE_WORK/acceptance/run-1/forecast/forecast.csv,dst=/input/forecast.csv,readonly" \
  --mount "type=bind,src=$INFERENCE_WORK/web,dst=/output" \
  tramflow-inference-qa-backend python -m scripts.package_ml_handoff \
  --artifact-dir /model --forecast /input/forecast.csv --output /output/handoff.zip
docker run --rm --network none \
  --mount "type=bind,src=$INFERENCE_WORK/web/handoff.zip,dst=/input/handoff.zip,readonly" \
  --mount "type=bind,src=$INFERENCE_WORK/web,dst=/output" \
  tramflow-inference-qa-backend python -m backend.handoff.install \
  /input/handoff.zip --output /output/release
export TRAMFLOW_HANDOFF_HOST_DIR="$INFERENCE_WORK/web/release"
docker compose -p tramflow-inference-qa -f compose.yaml -f compose.handoff.yaml \
  -f ml/inference/compose.web-check.yaml up -d --wait --wait-timeout 120
curl --fail http://127.0.0.1:15187/api/v2/handoff/ready
docker compose -p tramflow-inference-qa -f compose.yaml -f compose.handoff.yaml \
  -f ml/inference/compose.web-check.yaml exec -T backend \
  python -m backend.handoff.check --base-url http://frontend:5173 --release /data/handoff
```

Откройте `http://127.0.0.1:15187`, выберите маршрут и дату, проверьте «О данных»
→ «Паспорт». Run зависит от содержимого: побайтно одинаковый B2 сохраняет
`handoff-dd668e2870ae1b4069c689811d15ae6c5f6ff7668e4db04c64a452d4e30d03ed`,
хотя новый каталог release и его `imported_at` другие. Handoff-check сравнивает
первый/последний день всех маршрутов, каждый час, дневные суммы и закреплённый CSV.
В handoff передаётся **forecast.csv**, четырёхколоночный submission туда не подходит.

```sh
docker compose -p tramflow-inference-qa -f compose.yaml -f compose.handoff.yaml \
  -f ml/inference/compose.web-check.yaml down
```

Схема: проверенный артефакт → Docker CLI → новый float → handoff → FastAPI →
React/CSV. Это batch inference по сохранённым весам, а не модель на каждом
HTTP-запросе. Проверка дат не доказывает неизвестный потоковый протокол жюри,
NDTP или онлайн-обучение. Score и первоначальное обучение заново не оцениваются.
