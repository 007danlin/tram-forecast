# ML batch — Георгий

Реальный ML-контур работает отдельно от временного HTTP API v1. Backend продолжает
вызывать `predict_mock()` через `ml.adapter`; batch-команды ниже не меняют его контракт.

## Подтверждённая задача

- target: число строк с `validation_result == 1`;
- зерно: `route × calendar date × hour(tran_date_time)`;
- единица: успешные посадки/валидации, не заполненность вагона;
- область обучаемой модели: `1, 7, 11, 12, 17, 25, 26, 28, 50`;
- локальный organizer sample: `1, 5, 7, 11, 12, 17, 25, 26, 28, 50`;
- прогноз: 2025-11-01…2025-12-31, 14 640 строк;
- метрика: глобальный WAPE-score организаторов.

Маршрут 5 исключён из обучения, target-отчёта и области применения по позднему
QA-дополнению. Однако фактический sample всё ещё содержит его: 14 640 строк,
SHA-256 `71c8126bb51068c936462a170da885bad860fc91a58b3d2ac731876d324d7ec3`.
Поэтому адаптер готовит отдельные 10- и 9-маршрутные кандидаты; финальный формат
не выбирается без согласования. Неизвестные маршруты не поддерживаются.

## Установка

Из корня репозитория:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt -r ml/requirements.txt
export DATASET_DIR="/absolute/path/to/unpacked/dataset"
```

Для воспроизводимого окружения используется Python 3.12, как в CI.
`DATASET_DIR` должен содержать `train.csv`, `test.csv`, `labels/` и реальный
`test_submission.csv`. При `train` нужен также исходный `README.md` датасета:
его checksum включается в manifest. Архив повторно распаковывать не требуется.

## Воспроизведение

Проверка готовых labels прямой потоковой агрегацией raw CSV:

```sh
python -m ml verify-target --dataset-dir "$DATASET_DIR" --chunksize 500000
```

Регистрация резких суточных провалов без удаления и импутации:

```sh
python -m ml audit-history --dataset-dir "$DATASET_DIR" \
  --output artifacts/qa-addendum/history-drops.json
```

Детектор не назначает причину. Маршрут 50 за 14.09.2025 имеет 15 успешных
валидаций против reference 7 676,5; причина не подтверждена, восстановление не
применено.

Сравнение исходного и очищенного обучения запускается только после получения
версионированной подтверждённой маски Игоря:

```sh
python -m ml compare-training-mask \
  --dataset-dir "$DATASET_DIR" \
  --training-mask /absolute/path/training-mask-v1.json \
  --output artifacts/qa-addendum/mask-comparison.json \
  --experiment-log artifacts/qa-addendum/mask-comparison.csv
```

Схема `tramflow-training-mask-v1` требует source, reason, timezone/status зоны и
`verification_status=verified` для каждого route-интервала `[start,end)`.
Неподтверждённые и пересекающиеся правила отклоняются. Частичные часы
блокируются: из готовых labels нельзя честно вычесть условные 30 минут.

Подготовка локального погодного snapshot для отдельного
`competition_retro`-эксперимента (сырой JSON остаётся неизменным вне Git):

`prepare-weather` сам не скачивает JSON: `--snapshot` должен уже существовать,
а `--source-url` только записывает источник в manifest.

```sh
python -m ml prepare-weather \
  --snapshot artifacts/external/open-meteo/moscow-2025-era5.json \
  --output artifacts/external/open-meteo/moscow-2025-era5.normalized.csv \
  --manifest artifacts/external/open-meteo/moscow-2025-era5.manifest.json \
  --source-url "https://archive-api.open-meteo.com/v1/archive?latitude=55.7558&longitude=37.6173&start_date=2025-01-01&end_date=2025-12-31&hourly=temperature_2m,apparent_temperature,precipitation,snowfall,snow_depth,wind_speed_10m,wind_gusts_10m&timezone=Europe%2FMoscow&models=era5"
```

Выбор модели на двух ранних временных folds и повторная непрерывная 61-дневная
проверка сентября–октября:

```sh
python -m ml backtest \
  --dataset-dir "$DATASET_DIR" \
  --weather-factors artifacts/external/open-meteo/moscow-2025-era5.normalized.csv \
  --output artifacts/evaluation-addendum.json \
  --experiment-log artifacts/experiments/legacy/experiment-log.csv
```

Порядок P0-гипотез фиксирован: сначала официальный календарь F01, затем на той
же основе ERA5 F02. Фактический реанализ относится только к
`competition_retro`; эксплуатационная погода требует архивных forecast runs,
доступных на соответствующий `as_of`. Будущий пассажиропоток внутри горизонта
не используется ни в одном режиме.
Без `--weather-factors` backtest работает с календарными кандидатами, а F02
отмечается как blocked. Журнал по умолчанию сохраняется в
`artifacts/experiments/experiment-log.csv`; для каждого опыта задавайте новый
`--experiment-log`. Существующие отчёты и журналы не перезаписываются,
отслеживаемая история в `ml/reports/` не меняется автоматически.

Обучение выбранной модели на январе–октябре:

```sh
python -m ml train \
  --dataset-dir "$DATASET_DIR" \
  --evaluation-report artifacts/quality-085/evaluation.json \
  --artifact-dir artifacts/quality-085/calendar-interaction-ensemble
```

Формирование sample-совместимого кандидата на 10 маршрутов:

```sh
python -m ml submission \
  --artifact-dir artifacts/quality-085/calendar-interaction-ensemble \
  --template "$DATASET_DIR/test_submission.csv" \
  --scope sample \
  --output artifacts/quality-085/submission-calendar-interaction-ensemble-10-routes.csv \
  --preflight-output artifacts/quality-085/submission-calendar-interaction-ensemble-10-routes.preflight.json
```

Отдельный девятимаршрутный кандидат для согласования:

```sh
python -m ml submission \
  --artifact-dir artifacts/quality-085/calendar-interaction-ensemble \
  --template "$DATASET_DIR/test_submission.csv" \
  --scope modeled_routes \
  --output artifacts/quality-085/submission-calendar-interaction-ensemble-9-routes.csv \
  --preflight-output artifacts/quality-085/submission-calendar-interaction-ensemble-9-routes.preflight.json
```

Preflight проверяет точные колонки и порядок ключей выбранного scope,
дубли, пропуски, даты, часы, маршруты, конечность/неотрицательность/целочисленность
экспортных значений и записывает checksum. Для `sample` ожидаются 14 640 строк,
для `modeled_routes` — 13 176. В отчёте есть явный `contract_status`; успешная
структурная проверка не разрешает отправку спорного варианта.

Внутренний прогноз хранит неокруглённые значения, reference, 90% интервал,
priority score и status. Backtest публикует raw-метрики и метрики после
`floor(x + 0.5)`; модель выбирается по rounded score. Тот же общий helper
применяется адаптером submission.

Синтетический пример формата маски находится в
[`examples/training-mask.synthetic.json`](examples/training-mask.synthetic.json).
Его интервалы нельзя использовать как реальные. `compare-training-mask` создаёт
сравнение на неизменных оценочных строках и оставляет
`adoption_decision` неподтверждённым. Команда `train --training-mask` принимает
только тот же checksum маски и отчёт, где владельцы явно установили
`adoption_decision: adopted`; до согласования очищенный артефакт не создаётся.

```sh
python -m ml forecast --artifact-dir artifacts/quality-085/calendar-interaction-ensemble \
  --start 2025-11-01 --end 2025-11-01 --output artifacts/day.csv
python -m ml month --artifact-dir artifacts/quality-085/calendar-interaction-ensemble \
  --start 2025-11-01 --end 2025-11-30 --output artifacts/month.csv
python -m ml year-scenario --output artifacts/year-scenario.json
```

В `forecast` и `month` обе календарные границы включены. В HTTP handoff используется
`[start,end)` и предел 31 день на запрос; месяц в CLI — дневные суммы и пики,
а не новый шаг `month` HTTP. Backend читает готовый почасовой CSV через отдельный
[handoff](../backend/handoff/README.md), не вызывает модель из HTTP. Его ZIP-имена
фиксированы: каталог новой модели нельзя просто заархивировать под новым именем.
Четырёхколоночный округлённый submission не подходит вместо внутреннего CSV
с reference/interval/status. Переданный ранее пакет и метрики модели ниже
нужно сопоставлять по версии: обновление исходников не обновляет прогноз на сервере.

## Проверки

```sh
python -m unittest discover -s tests/ml -v
python -m unittest discover -s tests/integration -v
```

Фактические результаты: [паспорт модели](reports/model-card.md),
[аудит данных](reports/data-audit.md), [журнал экспериментов](reports/experiment-log.csv)
и [реестр F01–F16](external-sources.json).
Журнал содержит гипотезу, версию схемы, seed, параметры, одинаковые временные границы, общие метрики, JSON со
срезами по маршрутам, часам, типу дня, пику, величине потока, горизонту и статусу,
а также решение по эксперименту.
Выбран `calendar_interaction_ensemble`: rounded selection WAPE-score 0,8505524
(raw 0,8505436) против 0,8400868 у прежнего F01 HGBT. Девятимаршрутная оценка
содержит 26 568 selection-строк.
На повторно использованном 61-дневном validation-окне из 13 176 строк rounded
score 0,8290094 (raw 0,8290147) против 0,8231869 у previous-weekday. Сентябрь–октябрь
уже оценивался в PR #2 (`calendar_hgbt`, опубликованный raw score 0,8287), поэтому
это не pristine holdout; в текущем run период не использовался для выбора.
Погодный кандидат получил rounded 0,8332729 и отклонён.
Score не изменился после исключения маршрута 5, потому что его target и prediction
были нулевыми. Полный журнал улучшения и отклонённых гипотез:
[отчёт quality 0,85](reports/quality-improvement-2026-09-26.md). QA-ограничения:
[QA-отчёт](reports/qa-addendum-2026-09-26.md).

Результаты автора повторены локально 25.09.2026; новые группы, повторный holdout
и качество после DS-округления — в [отчёте](reports/weather-groups-2026-09-25.md).
Для модели, прогнозов и submission предусмотрен `artifacts/`, для данных —
локальный датасет; они исключены из Git. Оба локальных кандидата прошли свой
структурный preflight, но конфликт области маршрутов не разрешён. Подтверждённая
train-маска Игоря отсутствует, поэтому cleaned-model score не заявляется.

## Реализация приоритетов 25.09.2026

`fetch-weather` получает ERA5 и публикует новый snapshot только после проверки
единиц, конечных значений и точной часовой сетки. В каталоге сохраняются raw,
request receipt с фактическим временем UTC, normalized, manifest и coverage.
Сеть: connect=10s, read=120s, 32 MiB, максимум три попытки на network/429/5xx;
Retry-After более 30 секунд прекращает получение. Ошибочные ответы сохраняются
в отдельном `.failed-*`, не становятся действующим snapshot. Старый mtime
больше не объявляется временем получения; `prepare-weather --receipt` принимает
подтверждённый receipt. Без receipt `fetched_at=null`.

```sh
python -m ml fetch-weather --start 2025-01-01 --end 2025-12-31 \
  --output-dir artifacts/external/open-meteo/moscow-2025-v1
python -m ml fetch-weather --start 2025-01-01 --end 2025-12-31 \
  --output-dir artifacts/external/open-meteo/moscow-2025-v1 --offline
python -m ml backtest --dataset-dir "$DATASET_DIR" \
  --weather-factors artifacts/external/open-meteo/moscow-2025-v1/normalized.csv \
  --stage selection --experiment-config ml/experiments/weather-groups.json \
  --output artifacts/experiments/weather-groups/evaluation.json \
  --experiment-log artifacts/experiments/weather-groups/experiment-log.csv
```

Selection выполняет W00–W05 и не оценивает сентябрь–октябрь. W06 запускается
не более одного раза, только если минимум две одиночные группы прошли guardrail;
если это все четыре группы, переиспользуется уже проверенный W05. Report хранит
выбранный config, точный порядок признаков, выравнивание, snapshot и selection q90.
`train --evaluation-report` использует именно их. Fit/predict требуют только
включённые погодные поля. Старый `competition_weather_hgbt` сохраняет порядок
всех признаков. Погодные факторы и manifest сохраняются внутри model.joblib,
контрольная сумма которого входит в прежний manifest из трёх файлов; состав
handoff ZIP не расширен. Backend по-прежнему не исполняет joblib.

Суммарный score должен превышать W00, эффект положителен на обоих folds,
MAE каждого поддержанного маршрута ухудшается не более чем на 5%. Bootstrap
по семидневным блокам — оценка неопределённости, не доказательство причинности.
Второе окно содержит 62 дня; report сохраняет отдельный срез дней 1–61.
Отчёт и CSV-журнал отказываются перезаписывать существующие файлы.
Публичный `ml/reports/experiment-log.csv` пробным запуском не изменяется.

После фиксации выбора допускается **повторная** контрольная оценка holdout:

```sh
python -m ml backtest --dataset-dir "$DATASET_DIR" --stage holdout \
  --selection-report artifacts/experiments/weather-groups/evaluation.json \
  --output artifacts/experiments/weather-groups/holdout.json \
  --experiment-log artifacts/experiments/weather-groups/holdout-log.csv
```

Для выбранной погодной модели дополнительно передать тот же `--weather-factors`.
Этот holdout уже использовался ранее и не считается новым независимым тестом.
Отчёт включает качество до и после DS-округления; после holdout выбор не подбирать.
Старый режим `--stage full` сохраняет прежний общий эксперимент для воспроизведения.

Выравнивание осадков проверяется отдельным snapshot и отдельным отчётом:

```sh
python -m ml fetch-weather --start 2025-01-01 --end 2025-12-31 \
  --alignment next_hour_accumulation_v2 \
  --output-dir artifacts/external/open-meteo/moscow-2025-buffer-v2
```

В raw запрашивается также 01.01.2026, нормализованная сетка остаётся 8 760 часов.
Только precipitation/snowfall для интервала `[t,t+1h)` сдвигаются из метки `t+1h`.
В копии experiment-config задайте `alignment=next_hour_accumulation_v2`; конфиг
с иной семантикой, чем manifest, отклоняется. Для сравнения того же buffered raw
со старым правилом выполните `prepare-weather --start 2025-01-01 --end 2025-12-31
--receipt .../request.json --snapshot .../raw.json --output .../normalized.csv
--manifest .../manifest.json` в отдельный каталог с default legacy alignment.

[Условия Open-Meteo](https://open-meteo.com/en/terms) проверены 25.09.2026:
бесплатный API для некоммерческого использования, данные с атрибуцией CC BY 4.0.
Это реанализ одной точки Москвы, режим `competition_retro`, не прогнозный выпуск.

Совместимая упаковка готового артефакта и полного forecast:

```sh
python -m scripts.package_ml_handoff --artifact-dir artifacts/quality-085/calendar-interaction-ensemble \
  --forecast artifacts/forecast-for-backend.csv \
  --output artifacts/releases/calendar-interaction-ensemble-handoff.zip
```

Четыре model-файла копируются без изменения байтов в legacy transport paths.
Manifest, CSV и полная сетка 14 640 ключей проверяются до публикации. ZIP и
`.zip.sha256` не перезаписываются; симлинки и лишние файлы отклоняются.
Результаты текущего повторения и ограничения: `docs/verification-priority-implementation.md`.
