# Запуск веб-приложения для жюри

Нужны Docker Engine/Desktop, Docker Compose **2.24.4 или новее**, `unzip` и доступ к интернету при первой сборке. Python и Node.js на компьютере не нужны. Веб использует проверенный **B2**; конкурсный C01 запускается отдельно.

Все команды ниже — из распакованного полного комплекта, где лежат `sources.zip` и `demo-handoff.zip`. Порты **15186** и **18106** должны быть свободны. Используйте новый каталог: импорт не перезаписывает прошлый прогноз.

```sh
shasum -a 256 -c SHA256SUMS
unzip sources.zip
cd tram-forecast
shasum -a 256 -c MANIFEST.sha256
mkdir -p ../runtime
docker compose -p tramflow-jury -f compose.yaml build
docker compose -p tramflow-jury -f compose.yaml run --rm --no-deps \
  -v "$PWD/../demo-handoff.zip:/input/package.zip:ro" \
  -v "$PWD/../runtime:/output" backend \
  python -m backend.handoff.install /input/package.zip --output /output/release
export TRAMFLOW_HANDOFF_HOST_DIR="$(cd ../runtime/release && pwd)"
# Для автономного показа исторического прогноза отключаем текущий сбор новостей.
export TRAMFLOW_MONITOR_ENABLED=0
docker compose -p tramflow-jury -f compose.yaml -f compose.handoff.yaml \
  -f docs/submission-final/compose.local.yaml up -d --wait --wait-timeout 120
curl --fail http://127.0.0.1:15186/api/v2/handoff/ready
```

Linux: вместо `shasum -a 256` можно использовать `sha256sum`. Windows: команды выполняются в WSL2 с Docker Desktop.

Открыть **http://127.0.0.1:15186**. Документация API: **http://127.0.0.1:18106/docs**. Публичный сервер отдаёт `/api/*`; Swagger доступен напрямую на backend.

## Демо за две минуты

1. Выбрать 01.11.2025 и маршрут № 1. Менять время: график, таблица и значение у карты должны совпадать.
2. Перейти на неделю и месяц. Скачать CSV выбранного маршрута.
3. В сценарии изменить погоду на 1,10 и мероприятие на 1,20. Сравнить базу и сценарий, скачать сценарный CSV. Сбросить коэффициенты.
4. Открыть год: показаны качественные сценарии и план проверки, без выдуманного численного прогноза.
5. Проверить № 5: он явно обозначен как нулевой baseline. Маршрут № 2 — только схема, прогноз и CSV недоступны.

Текущий мониторинг можно включить через `TRAMFLOW_MONITOR_ENABLED=1` с пересозданием backend. Ему нужен интернет; доступность источников показывается отдельно от готовности исторического прогноза.

## API и проверка чисел

| Точка входа | Назначение |
|---|---|
| `GET /api/v2/handoff/ready` | Готов ли проверенный прогноз |
| `GET /api/v2/handoff/capabilities` | Даты, маршруты, версия и возможности |
| `POST /api/v2/handoff/query` | Прогноз по фильтрам |
| `POST /api/v2/handoff/export` | CSV этого результата |
| `POST /api/v2/scenarios/query`, `/export` | Ручные поправки и отдельный CSV |
| `GET /api/v2/monitoring/status`, `/records` | Состояние и записи мониторинга |

Тела запросов и ошибки описаны в Swagger и `tram-forecast/backend/handoff/README.md`. Сервис проверяет численные ответы всех маршрутов следующей командой:

```sh
docker compose -p tramflow-jury -f compose.yaml -f compose.handoff.yaml \
  -f docs/submission-final/compose.local.yaml exec -T backend \
  python -m backend.handoff.check --base-url http://127.0.0.1:8000 --release /data/handoff
```

Убедиться, что прогноз сохраняется после перезапуска:

```sh
docker compose -p tramflow-jury -f compose.yaml -f compose.handoff.yaml \
  -f docs/submission-final/compose.local.yaml up -d --force-recreate --wait backend
curl --fail http://127.0.0.1:15186/api/v2/handoff/ready
```

Остановить этот локальный проект, из того же терминала:

```sh
docker compose -p tramflow-jury -f compose.yaml -f compose.handoff.yaml \
  -f docs/submission-final/compose.local.yaml down
```

Если `ready` вернул 503, проверить импорт и `TRAMFLOW_HANDOFF_HOST_DIR`. Если порт занят, задать `TRAMFLOW_QA_FRONTEND_PORT` / `TRAMFLOW_QA_BACKEND_PORT` до запуска и использовать новые адреса. Сообщение «каталог существует» означает, что для повторного импорта нужен новый каталог.
