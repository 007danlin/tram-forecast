# Локальный комплект сдачи TramFlow

> Историческая инструкция отдельного B2-комплекта и `build_final_bundle`. Для общего комплекта с C01 используйте [актуальный README](README.md). Старые даты и решения ниже сохранены как история.

Текущее локальное состояние 27.09.2026: [итоговая приёмка](final-closure-status.md). Датированные проверки ниже относятся к своим версиям.

27.09.2026. Новый проверенный локальный комплект с подтверждением DS-результата
от 26.09. Точный путь: `artifacts/final-closure-20260927-r01/final-delivery.zip`.
Сохранение формы решения пока не подтверждено.

Уточнение 27.09: [новая переписка о проверке ML и сдаче](organizer-clarifications-2026-09-27.md).
Локальная приёмка ниже подтверждает прежний протокол. Соответствие переданному
условию потокового ML пока не установлено. Дополнение этого этапа:
[Docker inference B2](docker-inference-verification.md) — два новых расчёта
из исходных весов без fit/сети/готовых ответов, точные float/DS. HTTP продолжает
выдавать подготовленный handoff; протокол потоковой проверки не выдумывается.

Текущие статусы — `tram-forecast/docs/submission-final/final-closure-status.md`
после распаковки; `verification.md` сохраняет прежние протоколы.
Реестр формы — `tram-forecast/docs/submission-final/artifacts.md`, сценарий защиты —
`tram-forecast/docs/submission-final/pitch.md`. Готовые тексты полей A1–A6 —
`tram-forecast/docs/submission-final/submission-fields.md`.

В комплекте: `sources.zip` (снимок рабочего дерева с MANIFEST.sha256),
`demo-handoff.zip` (принятый B2 и float-прогноз), `g0-b2.zip` (исходный G0,
исходники ML, evaluation/OOF, metadata/schema/provenance), `ds-candidate.csv`,
`ds-preflight.json`, `g0-reproduction.json`, `release-manifest.json`, `SHA256SUMS`
и каталог evidence. В новой версии добавлены `evidence/final-closure/`: приёмка UI, календарная абляция, проверка входов остановок, независимая приёмка v4, Docker raw evidence и отдельные принятые кейсы Игоря. Все эти производные остаются вне Git и web-root. Имя `demo-handoff.zip` обозначает роль файла в локальном
запуске; фактическая модель теперь `calendar_interaction_ensemble`.
Исходные raw train/test и секреты не включены; G0 содержит агрегированные OOF.

Два CLI inference без fit в чистой Python 3.12.14 venv воспроизвели B2 побайтно.
Model SHA: `39edd75e265102f5973d14acd94bd4ae75a0473f12b7d07e47e2dc8b32eb9942`.
Float SHA: `f60caf48d1ce5d5066eaa4c6e74dc34454648b372d715efb1ad2b735dbf3ac4c`.
DS SHA: `505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94`.
Паспорт и ограничения приёмки — `tram-forecast/docs/submission-final/b2-acceptance.md`.

Даниэль проверил и подтвердил: именно `champion.csv` получил **0,84260**.
Связь с DS SHA выше принята по его подтверждению. Новый скриншот показывает
успешную строку от 26.09 18:50 +03:00 и остаток 32 любых / 20 успешных попыток
на момент снимка. Подтверждение и PNG — `evidence/score/`; самостоятельная
проверка сессии ассистентом не заявляется. Исходный training
commit/dirty state и полный lock обучения не сохранены автором. Null в manifest
сохраняет эти неизвестные значения. Скриншот и протокол отклонения старого model
сохранены в evidence; сам отклонённый model в текущий комплект не включён. Реконструкция point-model больше не используется для запуска:
получен и повторён исходный B2. Ассистент не выполнял публикацию или отправки;
успешную DS-отправку подтвердил Даниэль, receipt формы остаётся отдельным.

Репетиции и личная командная приёмка отложены по прямому указанию Даниэля.
Все локальные технические проверки завершены; публичный доступ/форма относятся
к следующему отдельно разрешаемому этапу.

## Контейнерный расчёт модели

Новая [инструкция Docker inference](../../ml/inference/README.md) даёт точные
команды подготовки входов, сборки отдельного образа, forecast/submission,
независимой сверки и подключения нового float к локальному handoff.
Host-venv и ML-библиотеки на хосте не нужны; Python 3.11+ требуется только
для stdlib-проверочного скрипта. История обучения и ограничения G0 сохранены.
Локальный комплект этого дополнения:
`artifacts/inference-docker/b2-20260927-r02/delivery/`; исходники в `sources.zip`,
четыре model-файла и sample отдельно в `inputs/`, эталоны — в `references/`,
протоколы — в `evidence/`. Файлы связаны `SHA256SUMS`.
Это дополнение к прежнему комплекту A1–A6, не новая отправка на платформу.

## Чистый локальный запуск

Нужны Docker Engine с Compose ≥2.24.4, `unzip`, `shasum` и доступ к registry/npm/PyPI
при первой сборке. Предварительно созданные `.venv`, developer Downloads, образы
проекта и локальный датасет для UI не нужны. Выполнять из каталога комплекта;
порты 15186 и 18106 должны быть свободны (либо задайте `TRAMFLOW_QA_FRONTEND_PORT` и `TRAMFLOW_QA_BACKEND_PORT`, затем используйте их в URL проверок). `runtime/release` должен отсутствовать.

```sh
shasum -a 256 -c SHA256SUMS
unzip sources.zip
cd tram-forecast
shasum -a 256 -c MANIFEST.sha256
mkdir -p ../runtime
docker compose -p tramflow-final-qa -f compose.yaml build
docker compose -p tramflow-final-qa -f compose.yaml run --rm --no-deps \
  -v "$PWD/../demo-handoff.zip:/input/package.zip:ro" \
  -v "$PWD/../runtime:/output" backend \
  python -m backend.handoff.install /input/package.zip --output /output/release
export TRAMFLOW_HANDOFF_HOST_DIR="$(cd ../runtime/release && pwd)"
docker compose -p tramflow-final-qa -f compose.yaml -f compose.handoff.yaml \
  -f docs/submission-final/compose.local.yaml up -d --wait --wait-timeout 120
curl --fail http://127.0.0.1:15186/api/v2/handoff/ready
# Независимая численная проверка первого/последнего дня, всех маршрутов и CSV:
docker compose -p tramflow-final-qa -f compose.yaml -f compose.handoff.yaml \
  -f docs/submission-final/compose.local.yaml exec -T backend \
  python -m backend.handoff.check --base-url http://127.0.0.1:8000 --release /data/handoff
```

Открыть `http://127.0.0.1:15186`. Swagger: `http://127.0.0.1:18106/docs`.
Выбрать 01.11.2025, «Обзор маршрутов» → маршрут → временной интервал.
Выбранное значение, график/таблица и ползунок используют один интервал. «Сценарий»:
погода 1,10, событие 1,20; проверить базу/сценарий/разницу и скачать отдельный CSV.
Сброс возвращает базу. Месяц → «Год» (качественные сценарии) сохраняет маршрут и показывает
три условных сценария и план на четыре квартала. В основе показан выбранный базовый прогноз; отдельный проверенный исторический профиль маршрута не передан. В карточке откройте «Проверить выпуск» для соседних значений и следующего действия. № 5 — baseline; № 2 — только схема, CSV отключён.
Обзор выгружает все маршруты, карточка — только выбранный. Все единицы — успешные
посадки, не заполненность; схема 2026 не является stop mapping для истории 2025.

Проверка перезапуска (run должен сохраниться):

```sh
docker compose -p tramflow-final-qa -f compose.yaml -f compose.handoff.yaml \
  -f docs/submission-final/compose.local.yaml up -d --force-recreate --wait backend
curl --fail http://127.0.0.1:15186/api/v2/handoff/ready
```

Остановка только этого тестового проекта:

```sh
docker compose -p tramflow-final-qa -f compose.yaml -f compose.handoff.yaml \
  -f docs/submission-final/compose.local.yaml down
```

## Воспроизводимость и границы

`release-manifest.json` связывает SHA исходников, модели, схемы, исходного датасета,
float-прогноза и DS; неизвестное происхождение training checkout отражено отдельно. `source_commit` — базовый HEAD,
`source_dirty=true` — рабочие изменения; source_fingerprint идентифицирует снимок.
Для повторной упаковки нужен исходный checkout: команда из корня
`python -m scripts.build_final_bundle --help`; список новых файлов явно задан
в `docs/submission-final/source-allowlist.json`. Ничего не staging/commit автоматически.
Повторная полная упаковка выполняется одной командой из исходного Git checkout.
`BUNDLE_INPUT` — абсолютный путь распакованного проверенного комплекта. Выходной
каталог должен быть новым; рядом будут созданы ZIP и его SHA256. Пример для
нынешнего решения Даниэля об отсрочке командной приёмки:

```sh
export BUNDLE_INPUT="/absolute/path/tramflow-local-final"
.venv/bin/python -m scripts.build_final_bundle \
  --output-dir artifacts/submission-final/repacked-local \
  --handoff "$BUNDLE_INPUT/demo-handoff.zip" \
  --ds-csv "$BUNDLE_INPUT/ds-candidate.csv" \
  --include-list docs/submission-final/source-allowlist.json \
  --release-name calendar-interaction-ensemble-b2 \
  --g0-verification "$BUNDLE_INPUT/g0-reproduction.json" \
  --supporting-bundle "$BUNDLE_INPUT" \
  --defer-team-acceptance
```

Исходный organizer template читается непосредственно из `g0-b2.zip`; конкурсный
CSV повторно проверяется против него, а не против собственных ключей. При первой
сборке без supporting bundle исходный sample задаётся через `--template`.
Упаковщик проверяет SHA каждого перенесённого доказательства, совпадение
model/handoff/DS и снимка. Без `--supporting-bundle` получается только core-набор:
G0/evidence не включены, что явно отмечается в manifest.delivery_completeness.
При необходимости `--verification-log /path/tooling-tests.log` добавляет сохранённый
лог проверки упаковщика. Повтор тестов: `.venv/bin/python -m unittest discover -s tests/tooling -v`.
Старые протоколы не объявляются новой проверкой: revision-verification.json
сравнивает исходники; при изменении runtime статус требует повторной приёмки.

Для inference установить Python 3.12 и **`ml/requirements-inference.txt`**:
это точные pins переданного inference lock с удалённой строкой предупреждения pip.
Оригинальный lock в G0 сохранён; его нельзя устанавливать без этого исправления.
Из корня распакованных исходников:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r ml/requirements-inference.txt
unzip ../g0-b2.zip -d ../g0-input
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 .venv/bin/python -m ml submission \
  --artifact-dir ../g0-input/champion-b2-g0-20260926-r01/model \
  --template ../g0-input/champion-b2-g0-20260926-r01/template.csv --scope sample \
  --output ../reproduced-submission.csv --preflight-output ../reproduced-preflight.json
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 .venv/bin/python -m ml forecast \
  --artifact-dir ../g0-input/champion-b2-g0-20260926-r01/model \
  --start 2025-11-01 --end 2025-12-31 --output ../reproduced-forecast.csv
shasum -a 256 ../reproduced-submission.csv ../reproduced-forecast.csv
```

Ожидаемые SHA приведены выше. Для второго inference выбрать другие выходные имена.
Обучение *нового* артефакта требует отдельно разрешённого датасета и evaluation:
команда в G0 README. Оно не является доказательством старого receipt.

Базовый load 199,967 RPS/p95 9,310 мс относится к прежнему локальному Docker-замеру
(1 worker, 2 CPU/4 GiB), не к VPS и не к новому сценарному endpoint.
Новый сценарный замер и его ограничения — в verification.md.
После 27.09 16:00 МСК прекращаются новые функции/гипотезы; исправляются только
блокеры запуска/формата/доступа. План обновления/отката — `deploy-plan.md` рядом
с verification.md. Commit, push, деплой, размещение ссылок и две отправки требуют
отдельной команды Даниэля.

## Новый комплект закрытия 27.09

Точный локальный путь и фактические проверки — в [итоговой приёмке](final-closure-status.md).
Новые исходники включаются только через проверенный `source-allowlist.json`.
Упаковщик дополнительно принимает `--additional-evidence /absolute/evidence`:
каталог должен быть целиком покрыт собственным SHA256SUMS, без symlinks,
дубликатов и выходов за каталог. Он копируется в `evidence/final-closure`.
`--runtime-verification /absolute/current-runtime-verification.json` связывает
run, все недокументальные исходники и обязательные проверки с SHA сырых логов;
несовпадение останавливает приёмку. Прежние проверки остаются датированной историей.
Этот файл создаётся после чистого запуска, а не вместо него. Повторная сборка
всегда использует новый выходной каталог; старые принятые ZIP не перезаписываются.

Команда этого этапа из исходного checkout (новый output при повторении):

```sh
.venv/bin/python -m scripts.build_final_bundle \
  --output-dir artifacts/final-closure-20260927-r01/final-delivery \
  --handoff artifacts/submission-final/tramflow-local-ready-20260926/demo-handoff.zip \
  --ds-csv artifacts/submission-final/tramflow-local-ready-20260926/ds-candidate.csv \
  --include-list docs/submission-final/source-allowlist.json \
  --release-name calendar-interaction-ensemble-b2 \
  --g0-verification artifacts/submission-final/tramflow-local-ready-20260926/g0-reproduction.json \
  --supporting-bundle artifacts/submission-final/tramflow-local-ready-20260926 \
  --defer-team-acceptance \
  --additional-evidence artifacts/final-closure-20260927-r01/evidence \
  --runtime-verification artifacts/final-closure-20260927-r01/current-runtime-verification.json
```

Дополнения не разрешают публикацию данных. Вся поставка содержит модель,
агрегированные OOF и исторические кейсы: передавать её только по разрешённому
каналу жюри. Публичный сайт и GitHub не являются хранилищем этого архива.
Четыре коэффициента и UI используют прежние API. Прежний 60-секундный сценарный
load измерял два явно заданных коэффициента; он не называется свежим load
четырёхфакторной версии. DF-03/04 не меняют HTTP-расчёт или состав ответа.
