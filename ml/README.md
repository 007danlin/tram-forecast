# ML batch — Георгий

Реальный ML-контур работает отдельно от временного HTTP API v1. Backend продолжает
вызывать `predict_mock()` через `ml.adapter`; batch-команды ниже не меняют его контракт.

## Подтверждённая задача

- target: число строк с `validation_result == 1`;
- зерно: `route × calendar date × hour(tran_date_time)`;
- единица: успешные посадки/валидации, не заполненность вагона;
- маршруты submission: `1, 5, 7, 11, 12, 17, 25, 26, 28, 50`;
- прогноз: 2025-11-01…2025-12-31, 14 640 строк;
- метрика: глобальный WAPE-score организаторов.

Маршрут 5 не имеет успешных наблюдений за январь–октябрь. Он получает нулевой
cold-start baseline и явный статус. Неизвестные маршруты не поддерживаются.

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

Выбор модели на двух ранних временных folds и однократный непрерывный
61-дневный holdout сентября–октября:

```sh
python -m ml backtest \
  --dataset-dir "$DATASET_DIR" \
  --weather-factors artifacts/external/open-meteo/moscow-2025-era5.normalized.csv \
  --output artifacts/evaluation-addendum.json \
  --experiment-log ml/reports/experiment-log.csv
```

Порядок P0-гипотез фиксирован: сначала официальный календарь F01, затем на той
же основе ERA5 F02. Фактический реанализ относится только к
`competition_retro`; эксплуатационная погода требует архивных forecast runs,
доступных на соответствующий `as_of`. Будущий пассажиропоток внутри горизонта
не используется ни в одном режиме.
Без `--weather-factors` backtest работает с календарными кандидатами, а F02
отмечается как blocked. Для пробного локального прогона задавайте
`--experiment-log artifacts/experiment-log.csv`: значение по умолчанию
перезаписывает отслеживаемый `ml/reports/experiment-log.csv`.

Обучение выбранной модели на январе–октябре:

```sh
python -m ml train \
  --dataset-dir "$DATASET_DIR" \
  --evaluation-report artifacts/evaluation-addendum.json \
  --artifact-dir artifacts/calendar-holiday-hgbt
```

Формирование submission строго по шаблону:

```sh
python -m ml submission \
  --artifact-dir artifacts/calendar-holiday-hgbt \
  --template "$DATASET_DIR/test_submission.csv" \
  --output artifacts/submission-calendar-holiday-hgbt.csv \
  --preflight-output artifacts/submission-calendar-holiday-hgbt.preflight.json
```

Preflight проверяет точные колонки и порядок ключей шаблона, 14 640 строк,
дубли, пропуски, даты, часы, маршруты, конечность/неотрицательность/целочисленность
экспортных значений и записывает checksum. Он не отправляет файл на платформу.

Внутренний прогноз хранит неокруглённые значения, reference, 90% интервал,
priority score и status. Округление `floor(x + 0.5)` выполняется только адаптером
submission.

```sh
python -m ml forecast --artifact-dir artifacts/calendar-holiday-hgbt \
  --start 2025-11-01 --end 2025-11-01 --output artifacts/day.csv
python -m ml month --artifact-dir artifacts/calendar-holiday-hgbt \
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
Выбран `calendar_holiday_hgbt`: selection WAPE-score 0,84009. На однократно
открытом 61-дневном holdout score 0,82170 против 0,82319 у previous-weekday;
holdout не использовался для повторного выбора. Погодный кандидат получил
0,83327 на selection и отклонён относительно календарного кандидата.

Это результаты автора: обучение и аудит реальных данных в текущей рабочей папке
не повторялись. Для модели, прогнозов и submission предусмотрен `artifacts/`,
для данных — локальный датасет; они исключены из Git и сюда не переданы.
Перед сдачей нужны сверка исходного sample, train-маски и качества после финального
DS-округления; [письменный ответ](../docs/integration/qa-2026-09-25/submission-clarification.md)
требует сохранять sample целиком, включая № 5 и все таймстемпы.
