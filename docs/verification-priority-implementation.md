# Протокол реализации приоритетов — 25.09.2026

Исполнитель: Codex по поручению Даниэля. Исходная постановка — `2c67772`;
промежуточные исходники сохранены параллельными задачами в `1e0bcf6`, `ba40098`
и `6ae211b`; финальные протоколы и lifecycle-проверка включены в этот
комплект исходников. Этот протокол подтверждает перечисленные
локальные проверки, а не командную приёмку принятого commit на другой машине.
Данные, веса, полные отчёты и screenshots находятся в игнорируемом `artifacts/`.
Конкурсная отправка и деплой VPS этой задачей не выполнялись.

## Статус этапов

| Этап | Фактический результат | Принимающий по ТЗ |
|---|---|---|
| RUN-01 | Настоящая календарная модель обучена, упакована, импортирована; первый и последний дни всех 10 маршрутов совпадают с API | Игорь — ожидается |
| UI-01 | Настоящий batch → API → UI → CSV, даты/границы/№ 5, ошибки и отмена запросов проверены браузером | Даниэль + Игорь — ожидается |
| LOAD-01 | 50/100/200 RPS по 5 минут прошли; при 200 RPS p95 9,310 мс, ошибки 0%, semantic 100%, dropped 0; export 7 440 строк проверен отдельно | Игорь — ожидается |
| WEATHER-01 | Год ERA5 получен, 8 760 часов, receipt/checksums; независимая программная сверка raw и normalized | Даниэль; отдельная сверка источника Игорем ожидается |
| ML-02 | W00–W05 для legacy и сдвига осадков, выбран W00; новый пакет и полный DS preflight | Игорь + Даниэль — ожидается |
| FIN-01 | Локальные проверки выполнены частично; чистый принятый checkout, независимая сверка target и полный серверный update/rollback не приняты | Игорь — ожидается |

Нагрузочные результаты записаны в [отдельном протоколе](verification-load.md).
Исправления поставки и их изолированные проверки описаны
[в смежном отчёте](reproducibility-fixes-2026-09-25.md).

## Пакет и воспроизведение RUN/UI

Фактическая модель: `calendar_holiday_hgbt`, operational, календарь и официальный
производственный календарь, без погоды. Обучение январь–октябрь 2025; forecast
01.11–31.12.2025, 14 640 строк. № 5 — нулевой cold-start baseline.

| Артефакт | SHA-256 / идентификатор |
|---|---|
| `artifacts/releases/calendar-holiday-priority-v1.zip` | `c5beb99d3fc10bca689b234caf71990378e9a705076481951b86edae8d61d5a9` |
| `artifacts/forecast-priority-v1.csv` | `81f26a3c327e90e68f776f284e9d5e7c5e70c08102ad83f6f8c9475f310864b7` |
| Run | `handoff-4c8d04b97381c5f0aa654f1128d6c7833a46650a418e973af3287d59d4f6daf2` |

Нужны Python 3.12, зависимости backend/ML, Node из frontend Dockerfile и
`npm ci`. В shell задайте `DATASET_DIR` путём к разрешённому локальному датасету;
структура и источник sample описаны в [ML README](../ml/README.md).
Локальные CLI-тесты: Python 3.12.14, Node 22.22.2. Docker/CI frontend закреплён
на Node 22.16.0; нагрузочный backend использовал Python 3.12.10.
Ниже команды использованной цепочки; повторять в **новых** каталогах результатов:

```sh
python -m ml train --dataset-dir "$DATASET_DIR" \
  --evaluation-report artifacts/experiments/weather-groups-priority-v1/evaluation.json \
  --artifact-dir artifacts/calendar-holiday-priority-v1
python -m ml forecast --artifact-dir artifacts/calendar-holiday-priority-v1 \
  --start 2025-11-01 --end 2025-12-31 --output artifacts/forecast-priority-v1.csv
python -m scripts.package_ml_handoff --artifact-dir artifacts/calendar-holiday-priority-v1 \
  --forecast artifacts/forecast-priority-v1.csv \
  --output artifacts/releases/calendar-holiday-priority-v1.zip
python -m backend.handoff.install artifacts/releases/calendar-holiday-priority-v1.zip \
  --output artifacts/releases/calendar-holiday-priority-v1
export TRAMFLOW_HANDOFF_HOST_DIR="$PWD/artifacts/releases/calendar-holiday-priority-v1"
docker compose -f compose.yaml -f compose.handoff.yaml up --build -d --wait
python -m backend.handoff.check --base-url http://127.0.0.1:5173 \
  --release "$TRAMFLOW_HANDOFF_HOST_DIR"
QA_RELEASE="$TRAMFLOW_HANDOFF_HOST_DIR" NODE_PATH="$PWD/frontend/node_modules" \
  python tests/frontend/run_browser.py
```

Локальный browser runner использовал установленный Chrome (`QA_BROWSER=chrome`);
CI устанавливает pinned Playwright Chromium. Runner запускает отдельные API/Vite
на свободных портах. Проверяет raw float с допуском `1e-9 + 1e-12*abs(expected)`,
первый/последний день, неделю, ноябрь/декабрь, baseline, экспорт, быстрые смены,
503/410/409, partial/no_data, клавиатуру и ширины 1366/390, немосковскую зону.
Карта и её исходные данные не заменены. Скриншоты сохраняются в `artifacts/verification/ui-real/`.
Synthetic сценарий и повреждённые пакеты проверяются отдельно, не выдаются за модель.

Дополнительно прошёл `tests/access/run_browser_check.py` через временный локальный
HTTPS/Caddy: anonymous/wrong password получают 401, авторизованный браузер видит
карту и UI, отсутствие handoff остаётся явным после retry, новый контекст снова
требует вход. Временный CA не устанавливался в доверенные хранилища ОС.

После полного нагрузочного прогона два последовательных пересоздания backend
сохранили read-only mount и тот же run. Команда up → ready: 1 016 и 958 мс;
значения query/export после перезапуска совпали. Это локальное пересоздание
процесса, не полный серверный цикл обновления и отката.

## Погода и выбор модели

Пошаговые команды получения/offline/selection/holdout — в
[ML README](../ml/README.md#реализация-приоритетов-25092026).
Использованы snapshots `moscow-2025-priority-v1` и `moscow-2025-buffer-priority-v2`
в `artifacts/external/open-meteo/`. Точная сетка: 8 760 часов;
январь–август 5 832, сентябрь–октябрь 1 464, ноябрь–декабрь 1 464.
Сырые параметры, время получения, единицы, coverage и checksums сохранены рядом.
Оба snapshot повторно нормализованы с `--offline`: checksums и coverage совпали.

Два исследования находятся в `artifacts/experiments/weather-groups-priority-v1/`
и `artifacts/experiments/weather-alignment-priority-v2/`. Для alignment-опыта
legacy control повторно получен из того же buffered raw и совпал по SHA-256
с первым normalized. Семь граничных часов дополнительно сопоставлены с raw
программой, не использующей нормализатор; это не независимая подпись Игоря.

[Таблица W00–W06 и checksums](../ml/reports/weather-groups-2026-09-25.md):
ни один погодный кандидат не прошёл все заранее заданные guardrails. Сохранён
W00 (selection score 0.84008809). Holdout уже использовался ранее и проверен
повторно после фиксации выбора: score 0.82170203 до DS-округления, 0.82169780
после, фактическое покрытие номинального 90% интервала 82.802%.

```sh
python -m ml submission --artifact-dir artifacts/calendar-holiday-priority-v1 \
  --template "$DATASET_DIR/test_submission.csv" \
  --output artifacts/submission-calendar-holiday-priority-v1.csv \
  --preflight-output artifacts/submission-calendar-holiday-priority-v1.preflight.json
```

Preflight прошёл на полном реальном sample: 14 640 ключей, ночные строки и № 5
сохранены. Очистка цели и независимая сверка исходных оплат — отдельная открытая
работа; target-маска не менялась внутри погодного сравнения.
Версионированная маска рабочих часов по маршрутам и датам для исключения
технологических валидаций не предоставлена; часы 05:30–01:00 не приняты
за доказанное общее расписание.

Повторный `predict_artifact` с запрещённым `socket.create_connection` сформировал
все 14 640 строк: байты CSV и SHA-256 точно совпали с переданным forecast.
Тест погодного артефакта отдельно проверяет встроенные факторы без внешнего файла.

## Проверки исходников

На Python 3.12 прошли 37 backend, 9 integration, 28 ML и 24 tooling теста
(98 всего), `pip check`, OpenAPI check и frontend build. Команды:

```sh
python -m unittest discover -s backend/tests -v
python -m unittest discover -s tests/integration -v
python -m unittest discover -s tests/ml -v
python -m unittest discover -s tests/tooling -v
python -m backend.contracts.openapi --check
python -m pip check
npm --prefix frontend run build
```

Проверка `python -m scripts.check_delivery` прошла в изолированной копии
исходных файлов (временный индекс Git без commit). Финальный комплект включает
169 файлов с lifecycle-проверкой. Это проверка комплектности и ссылок,
не доказательство публикации. Локальный перечень SHA-256 исходников сохранён
в `artifacts/verification/source-checksums.json` до оформления публикации;
последующие редакционные уточнения статуса отражены в Git.
