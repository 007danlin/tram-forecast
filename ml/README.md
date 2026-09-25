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
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt -r ml/requirements.txt
export DATASET_DIR="/absolute/path/to/unpacked/dataset"
```

`DATASET_DIR` должен содержать `train.csv`, `test.csv`, `labels/` и реальный
`test_submission.csv`. Архив повторно распаковывать не требуется.

## Воспроизведение

Проверка готовых labels прямой потоковой агрегацией raw CSV:

```sh
python -m ml verify-target --dataset-dir "$DATASET_DIR" --chunksize 500000
```

Выбор модели на двух ранних временных folds и однократный финальный holdout:

```sh
python -m ml backtest \
  --dataset-dir "$DATASET_DIR" \
  --output artifacts/evaluation.json \
  --experiment-log ml/reports/experiment-log.csv
```

Обучение выбранной модели на январе–октябре:

```sh
python -m ml train \
  --dataset-dir "$DATASET_DIR" \
  --evaluation-report artifacts/evaluation.json \
  --artifact-dir artifacts/calendar-hgbt-v1
```

Формирование submission строго по шаблону:

```sh
python -m ml submission \
  --artifact-dir artifacts/calendar-hgbt-v1 \
  --template "$DATASET_DIR/test_submission.csv" \
  --output artifacts/submission.csv
```

Внутренний прогноз хранит неокруглённые значения, reference, 90% интервал,
priority score и status. Округление `floor(x + 0.5)` выполняется только адаптером
submission.

```sh
python -m ml forecast --artifact-dir artifacts/calendar-hgbt-v1 \
  --start 2025-11-01 --end 2025-11-01 --output artifacts/day.csv
python -m ml month --artifact-dir artifacts/calendar-hgbt-v1 \
  --start 2025-11-01 --end 2025-11-30 --output artifacts/month.csv
python -m ml year-scenario --output artifacts/year-scenario.json
```

## Проверки

```sh
python -m unittest discover -s tests/ml -v
python -m unittest discover -s tests/integration -v
```

Фактические результаты: [паспорт модели](reports/model-card.md),
[аудит данных](reports/data-audit.md), [журнал экспериментов](reports/experiment-log.csv).
Журнал содержит гипотезу, версию схемы, seed, параметры, одинаковые временные границы, общие метрики, JSON со
срезами по маршрутам, часам, типу дня, пику, величине потока, горизонту и статусу,
а также решение по эксперименту.
Реальные данные, модель, прогнозы и submission находятся в `artifacts/`/локальном
датасете и исключены из Git.
