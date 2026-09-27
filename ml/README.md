# ML batch — Георгий

## v12: R03 — платформенный лидер 0,89061

По сообщению пользователя, R03 **0,89061**, +0,00058 к C01 **0,89003**, теперь резерву.
[Отчёт](reports/score-v12-2026-09-27.md), [реестр](experiments/platform-leader.json).
Смесь50%R02+50%C01 выпущена по просьбе после локального отказа; отрицательные
OCT/D сохранены. CSV/модель/float неизменны;36OOF и воспроизведение в архивеv12,
с обязательным родительским архивомv11. Карточка выпуска историческая доscore.
Сервис не переключался, автоматической отправки нет. >0,93/0,95 не достигнуты.

## Платформа v11: C01 — лидер 0,89003

По сообщению Даниэля, **C01 0,89003** улучшил E01 на **+0,00078**.
E01 0,88925 — основной резерв; G01/L02 по отдельности остаются непроверенными
на платформе. [Реестр](experiments/platform-leader.json) связывает score с точным
SHA CSV; [отчёт v11](reports/score-v11-2026-09-27.md) дополнен.
Модели/CSV/float/OOF/пакет неизменны, исходные карточки архива исторические.
Нового fit, отправок и переключения сервиса нет. Ниже — история выпуска.

## v11: измеренный локальный прирост, лидер E01 без изменений

[Отчёт v11](reports/score-v11-2026-09-27.md): выполнены четыре фиксированных
конфигурации и C01=50/50 G01+L02, сохранены 45 новых OOF, код, модели и три CSV.
C01 — первый ручной тест: OCT +0,00118257, D +0,00432695 к E01. G01 и L02
самостоятельно проигрывают D; L02 имеет низкий приоритет. Все окна повторные.
Полное воспроизведение CSV/float, manifest и переносимый архив — локальный
`artifacts/score-v11-ensemble-level-20260927-r01/`. **Платформенный лидер E01
0,88925**, резерв H02; результатов v11 пока нет. Сервис и Git не публиковались.

## Платформа v10: E01 — новый лидер 0,88925

По сообщению Даниэля: **E01 0,88925**, H02 **0,88774**, MW01 **0,88681**.
Все три превзошли A01; E01 улучшил прежний лучший score на **+0,00445**.
H02 — основной резерв, MW01/A01/R02/P1/B2 сохранены. [Реестр](experiments/platform-leader.json)
связывает результаты с точными SHA; [отчёт](reports/score-v10-2026-09-27.md)
обновлён без изменения исходных моделей и архива. Независимого запроса платформы нет.
Нового обучения/отправок/commit/push/PR/деплоя не выполнялось. Ниже — история выпуска.

## v10: три CSV для ручной проверки, лидер A01 сохранён

[Отчёт v10](reports/score-v10-2026-09-27.md): измерены H01/H02, M01/M02/MW01
и фиксированный E01=50/50 H02+MW01 на9локальных окнах. Первый приоритет — H02:
OCT +0,00313920 и D +0,00961435 к A01. MW01 экспериментальный: OCT +0,00362688,
D −0,00668440. E01 выпущен по отдельному разрешению пользователя после отказа
по исходному критерию D; OCT0,90602633 не является прогнозом платформы.

**Платформенный лидер A01 0,88480**, резерв R02 0,88423; новые score неизвестны.
CSV, модели, OOF, audit, регистрации и full saved inference — локальный пакет
`artifacts/score-v10-targeted-20260927-r01/`. Защищённые артефакты сохранены;
API/приложение/VPS не переключались, отправки и commit/push/PR нет.

## Итоги платформы v9: A01 — лидер, D02 отклонён

**A01 0,88480** сохраняется лидером, **R02 0,88423** — резервом.
Сообщённый Даниэлем **D02 0,88306** отклонён, артефакты сохранены.
[Реестр](experiments/platform-leader.json) и [отчёт v9](reports/score-v9-2026-09-27.md)
обновлены. Повторных отправок A01/D02 не делать; комбинацию A01+D02 не создавать.
Непересечение изменённых строк проверено: при той же глобальной WAPE расчётный
score комбинации ≈0,88363, не новый платформенный результат. Модели/CSV/архивы
не переписывались, новых fit/публикаций/деплоя нет.

**Ниже — история до получения результата D02.**

## Текущий платформенный лидер — A01 0,88480, 27.09.2026

Даниэль сообщил результат `submission-v9-a01-experimental-20260927.csv`:
**+0,00057** к R02. CSV, модель, float и архивы A01 сохранены неизменными;
[реестр](experiments/platform-leader.json) фиксирует SHA и источник подтверждения.
R02 0,88423 — основной резерв, P1/B2 — дополнительные. [Отчёт v9](reports/score-v9-2026-09-27.md)
дополнен результатом платформы; прежние локальные оценки и контроль R02 не менялись.
D02 пока без сообщённого результата. Новых fit/отправок/деплоя нет.

**Ниже — история до получения платформенной оценки A01.**

## v9 завершена: R02 0,88423 остаётся лидером

[Отчёт v9](reports/score-v9-2026-09-27.md): 8 фиксированных конфигураций × 8 окон,
модели и 64 OOF сохранены. Основного кандидата лучше R02 на осеннем D не найдено.
Для ручной проверки выданы отдельные экспериментальные D02 (календарь) и A01
(давность обычного дневного спроса); их платформенные score неизвестны.
Оба имеют ограниченный масштаб: теоретический потолок ниже 0,90 при прежней
метрике и области строк. Риски и дельты раскрыты, 0,90/0,95 не заявляются.

Локальный пакет `artifacts/score-v9-parallel-20260927-r01/` включает RESULT,
experiments, регистрации, команды полного replay P1→R02→A01/D02 и проверки.
Исходные R02/P1/B2 неизменны. API, приложение, VPS не переключались;
отправка, commit/push/PR и деплой не выполнялись.

## Текущий платформенный лидер — R02 0,88423, 27.09.2026

Результат ручной отправки сообщил Даниэль: **+0,04134** к P1.
[Реестр](experiments/platform-leader.json) фиксирует точные CSV/модель/архив;
[карточка R02](reports/score-v8-r02-export-2026-09-27.md) содержит метод и ограничения.
P1 0,84289 — основной резерв, B2 0,84260 — дополнительный. Байты всех выпусков
сохранены; актуальный score записан отдельно от исходного пакета R02.
Сравнение будущих кандидатов — с R02, P1 и B2 на одинаковых окнах.
Runtime/VPS не переключались. Источник результата — пользователь,
без независимо проверенного submission ID. Летние регрессии не отменены.

**Разделы ниже отражают историю этапов до получения результата R02.**

## Экспериментальный экспорт R02, 27.09.2026

По отдельной команде пользователя выпущен R02 для одной ручной проверки.
**P1 0,84289 остаётся лидером; платформенный score R02 неизвестен.** Формула,
сезонные границы и реестр v8 не менялись; история финального fit до 31 октября.
[Карточка](reports/score-v8-r02-export-2026-09-27.md) содержит риски, SHA и
изменения дневного объёма по маршрутам/месяцам. Пакет:
`artifacts/score-v8-r02-export-20260927-r01/`. Прежний отказ R02 по локальным
критериям сохраняется; исторические этапы ниже не переписаны. Отправки/деплоя нет.

## Обновление v8, 27.09.2026

E02 получил на платформе **0,83863** и отклонён. **P1 0,84289** остаётся
неизменным лидером, B2 — резервом. [v8](reports/score-v8-2026-09-27.md)
разделяет ошибку режима движения и систематическое занижение дневного спроса.
Экспериментальный R01: S **0,84805089**, D **0,83912721**; улучшено 1/4 S,
остальные неизменны. Это не сильный допуск и не новый платформенный лидер.
R02: D 0,88430082, но летние/stress-провалы — отказ. Весь evidence, два OOF
и отдельный CSV R01: `artifacts/score-v8-regime-audit-20260927-r01/`.
Команды — `COMMANDS.md`; 8 новых проверок и настоящий replay P1→R01 прошли.
Отправки, commit/push/деплоя не было. Ниже сохранены исторические этапы.

## Новый экспериментальный кандидат v7, 27.09.2026

[v7](reports/score-v7-2026-09-27.md): 10 конфигураций, выбран E02
`0.50*P1 + 0.25*F01 + 0.25*W07`. S1–S4 **0,84907498**, Δ к P1
**+0,00308363**, 4/4 окна лучше. На повторном D ухудшение **−0,00209566**;
допуск диагностики пройден, перенос выигрыша на платформу не доказан.
Режим — **competition_retro**, включая архивную фактическую погоду.
Пакет: `artifacts/score-v7-diverse-20260927-r01/`, команды — `COMMANDS.md`.
CSV: `final/candidate.csv`, SHA-256
`66017ad7b2b368f18f5104f90e7f7c8404aa49b8b6b601b64c89f67518ad3095`.
96 тестов, OOF и сохранённые веса проверены. P1 ниже остаётся платформенным
лидером неизменным. На момент выпуска v7 отправки не было; позднейший
результат E02 — 0,83863, кандидат отклонён. Runtime не заменён.

## Текущий платформенный лидер — P1, 27.09.2026

Даниэль подтвердил **P1 0,84289**, прежний **B2 0,84260** оставлен резервом.
Прирост на платформе +0,00029. [Реестр лидера](experiments/platform-leader.json)
содержит источник подтверждения, точные пути и SHA-256 CSV/моделей/OOF.
P1 CSV: `artifacts/daniel-ml-20260927-r01/final/export-1/candidate.csv`, SHA-256
`a9e49df37acafba0f041e8c5c148618bc956dd7a5d1290ce9142af7961369ad6`.
Модель: `artifacts/daniel-ml-20260927-r01/final/model/`; отдельный пакет
`artifacts/daniel-ml-20260927-r01/p1-experimental-20260927.zip` сохраняет исходное
имя и байты. Название «experimental» отражает статус на момент упаковки.

Цель следующего этапа — превзойти P1. Будущие кандидаты сравниваются с обоими
неизменными контролями на одинаковых S1–S4 и, при диагностике, D/X1–X3;
совпадение ключей, targets, горизонтов, округления и знаменателя обязательно.
Уже просмотренные окна не являются независимым holdout. P1 повторно обучать
или отправлять без изменений не нужно. Его конкурсное лидерство не означает
переключения приложения/VPS с B2. Старые результаты ниже сохранены как история.

## Исследование v6 — 27.09.2026

[Все 10 конфигураций](reports/score-v6-2026-09-27.md) уступили P1 на S1–S4.
Лучший новый вариант 0,84553387 против P1 0,84599136 (Δ −0,00045749).
GRU совместного объёма/профиля, маршрутные бустинги, парные солнечные признаки
и фиксированные смеси сохранены с OOF/весами/кодом в отдельном локальном
`artifacts/score-v6-joint-temporal-20260927-r01/`. 91 ML-тест прошёл;
16 моделей уровня fold и все 10 OOF точно воспроизведены без нового fit.
P1 0,84289 остаётся платформенным лидером. Цель 0,95 не достигнута;
новые финальная модель/CSV не создавались, D/stress этого этапа не открывались.

## Передача champion G0/G2 — 26.09.2026

Exact B2 локально воспроизведён дважды в чистой venv без обучения: DS SHA
`505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94`.
Даниэль подтвердил связь champion.csv с platform **0,84260** и снимком успешной
строки от 18:50. Стабильного submission ID/receipt формы нет; PNG находится в локальном evidence/score, вне Git.
Float, DS, исходная модель, config/seed, inference lock, source hashes, два
preflight и завершённые результаты v3 входят в локальный
`artifacts/champion-b2-g0-g2-20260926-final-v2.zip`. [README пакета](reports/champion-g0-readme.md),
[актуальный паспорт G2](reports/champion-b2-g2-2026-09-26.md),
[статус всех пунктов v3 и G1](reports/v3-completion-and-g1-result-2026-09-26.md).
Original training commit/full lock не записаны — они не подменены версией inference.
В текущей структуре ML-часть Георгия — каталог `ml/`; отдельного каталога `Георгий/` нет.

Adaptive № 50 получил сообщённые **0,83543**, Δ=−0,00717: отклонён,
исходный CSV сохранён. SHA кандидата и область 367 изменений проверены;
остальные маршруты, рабочая суббота 01.11 и праздники неизменны.
G1/v3 повторно не запускались. Этот G0/G2 не обновлял VPS; актуальный `main`
отдельно документирует уже выполненную поставку того же B2/run на сайт.

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
26.09.2026 Даниэль подтвердил разрешение организаторов на нули либо придуманные
значения № 5. Принято сохранять полный sample и нулевой fallback: 14 640 строк.
Адаптер поддерживает оба scope; девятимаршрутный экспорт теперь диагностический.
Metadata/preflight фиксируют `full_sample_route_5_zero_fallback_approved_by_team`;
`cold_start_zero_baseline` не означает доказанное отсутствие движения.
Неизвестные маршруты не поддерживаются.

Аудит следующей серии: [повторённые измерения](reports/score-audit-2026-09-26.md)
и [источники](../docs/team-specs/score-v3-sources.md). На общем протоколе четырёх
61-дневных окон текущий ансамбль даёт 0,84484148; на повторной диагностике
сентября–октября — 0,82900943. Это не score платформы: более свежий результат 0,84260
сообщён Даниэлем для B2 CSV с SHA 505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94.
Исходный B2 получен и дважды воспроизведён без fit: [приёмка](../docs/submission-final/b2-acceptance.md). При первоначальной локальной приёмке продукт подключён к тому же B2; VPS тогда не менялся. Последующая публичная установка и текущее локальное состояние — в [итоговой приёмке](../docs/submission-final/final-closure-status.md). Даниэль проверил и подтвердил champion.csv → 0,84260; новый скриншот 18:50 показывает успешную строку. 0,83732 относится к прежнему CSV.
История проверки выходных № 50 — в [отчёте](reports/route50-weekends-2026-09-26.md).
Серия [score v3](reports/score-v3-2026-09-26.md) выполнена: лучший новый
результат F1-B2 равен 0,84544143, но не прошёл заранее заданный порог +0,002 и
устойчивость по folds. Решение — `no_improvement`, действующий B2 сохранён;
новый artifact/submission не создан.

## Inference B2 без host-venv

[Отдельный Docker CLI](inference/README.md) использует Python 3.12.14 и
неизменённые `requirements-inference.txt`. В образе только исходники/зависимости,
модель и sample передаются read-only, запуск без сети. Два независимых полных
расчёта сохранили SHA B2, точные float/DS, интервалы и статусы; отдельные сутки
совпали со срезами. Эталоны читает только последующий процесс сравнения.
[Контейнерная приёмка и замеры](../docs/submission-final/docker-inference-verification.md).
Обучение/параметры/CLI-границы дат не менялись; это отдельная подготовка handoff,
не исполнение модели на HTTP-запросе и не подтверждение потокового протокола.

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

## Серия score v3

`score-v3` запускает отдельный origin-safe протокол с точными S1–S4,
обязательными control B0/B1/B2, direct CatBoost, daily level × normalized hourly
share, past-only regime и проверенным T01. Все метрики считаются до и после
`floor(x + 0.5)`; выбор выполняется по rounded.

```sh
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 .venv/bin/python -m ml score-v3 \
  --dataset-dir "$DATASET_DIR" \
  --config ml/experiments/score-v3.json \
  --output-dir artifacts/score-v3-<new-run>
```

Каталог run нельзя перезаписывать. `--resume` требует полного совпадения
fingerprint. `selection.json` записывается до повторной диагностики D; если ни
один кандидат не проходит guardrails, D не используется для перебора замен.
OOF, модели, journal и реальные targets остаются в игнорируемом `artifacts/`.
Итог `r02`: 12 новых fit-конфигураций из лимита 24 и шесть OOF-смесей;
ни одна не допущена. Подробности и ограничения — в
[отчёте](reports/score-v3-2026-09-26.md).

## Отдельная проверка выходных № 50

Отдельная последующая проверка выходных № 50 воспроизводится через
`python -m scripts.route50_weekends --dataset-dir "$DATASET_DIR" --output-dir artifacts/route50-weekends-<new-run>`.
Используются сохранённые B2 OOF серии v3 и проверенный incumbent из `quality-085`.
Сравниваются 28/56-дневные почасовые средние и смеси 25/50/75/100%, строго до
origin. Только обычные выходные № 50 допускают изменение; 01.11, праздники,
переносы и остальные маршруты сохраняются. Итог `r03`: R8-100 даёт +0,00107194
на S1–S4, но −0,00397327 на повторном D; допуск не получен. Дополнительное
31-дневное октябрьское окно подтверждает пользу свежего R4-профиля после
наблюдения сентября (+0,00747368), но не используется для выбора. Новый
submission не создан. [Полный отчёт и почасовые сравнения](reports/route50-weekends-2026-09-26.md).

## Адаптивная проверка выходных № 50

В следующем отдельном опыте `scripts.route50_adaptive` свежий 4-недельный профиль
включается только после устойчивого снижения: оба средних дня недели и каждый
из последних шести дней трёх полных уикендов ≤35% прежнего уровня. Прежний
уровень — медианы предшествующих 84 дней, строго раньше свежего 28-дневного
окна. В правиле нет даты смены режима. [Протокол](reports/route50-adaptive-protocol-2026-09-26.md)
и [config](experiments/route50-adaptive.json) зафиксированы до запуска.

```sh
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 .venv/bin/python -m scripts.route50_adaptive \
  --dataset-dir "$DATASET_DIR" \
  --output-dir artifacts/route50-adaptive-<new-run>
```

Итог `r01`: первое включение 22.09, на прежних S1–S4/D прогноз совпадает с B2.
На основном дополнительном срезе октября из origin 29.09 общий score
0,87130204 → 0,87777856; MAE выходных № 50 261,71 → 38,85. Origins 08/15/22/29.09
и 01.10 используют пересекающийся октябрь: это один наблюдаемый низкий период.
Проверки дали допуск **исследовательского**, а не основного CSV:
`artifacts/route50-adaptive-20260926-r01/submission-route50-adaptive-research.csv`,
14 640 строк, preflight прошёл, SHA-256
`42ab12fbbe68afdbec9b915394fec66974f17e698506e76d80f2279af8d868da`.
Основной CSV, № 5, остальные маршруты, 01.11 и праздники сохранены;
platform score неизвестен. [Полный отчёт](reports/route50-adaptive-2026-09-26.md).

## Серия score-improvement-v2

Команда `improve-score` реализует отдельный протокол из
[ТЗ](../docs/team-specs/score-improvement-v2.md). Старые `SELECTION_FOLDS`, имена
моделей и формат handoff остаются прежними. Новые модели имеют имена
`score_profile_v2`, `score_level_v2`, `score_hgbt_v2`, `score_catboost_v2`,
`score_blend_v2`, `score_direct_v2`; их конфигурации принимает общий factory,
`train --evaluation-report` и обычный batch/export.

Используйте Python 3.12. CatBoost — отдельная необязательная зависимость:

```sh
python3.12 -m venv artifacts/.score-venv
artifacts/.score-venv/bin/python -m pip install -r ml/requirements-score.txt
export DATASET_DIR="/absolute/path/to/unpacked/dataset"
export SCORE_RUN="artifacts/experiments/score-improvement-v2-run01"
LOKY_MAX_CPU_COUNT=4 OMP_NUM_THREADS=4 artifacts/.score-venv/bin/python -m ml improve-score \
  --dataset-dir "$DATASET_DIR" --config ml/experiments/score-improvement-v2.json \
  --baseline-artifact artifacts/calendar-holiday-priority-v1 \
  --baseline-submission artifacts/submission-calendar-holiday-priority-v1.csv \
  --output-dir "$SCORE_RUN"
```

Config фиксирует четыре 61-дневных окна S1–S4, конечную сетку опытов, seed,
пороговые значения, четыре CPU-потока и buffered weather snapshot. Проверяются
свежие 28/56-дневные профили и смеси, поправка уровня, три HGBT без категории
месяца, восемь CatBoost MAE, разрешённые пары ансамбля, W02 и его смеси. D-direct
запускается только при отсутствии допущенного улучшения P1 и доступном CatBoost.
Недоступные зависимости/источники отмечаются явно. F-events — отдельное исследование
официальных источников с локальными snapshots; runner не назначает коэффициенты
неподтверждённым событиям. T-clean требует проверенной маски технологических валидаций.

Профили используют `день недели × официальный рабочий/нерабочий день`; менее трёх
сопоставимых дат ведут к fallback по официальному типу дня, затем к W00. Нулевой
маршрут сохраняется. H1–H3 и CatBoost определяют число итераций по последним
28 дням внутри train и переобучаются на всей доступной части. Для W00 сохранена
исходная реализация sklearn, включая внутреннюю случайную проверку; внешний
fold ей недоступен. Поэтому сравнение H с W00 включает также изменение внутренней
процедуры остановки, это не чистая оценка эффекта удаления месяца. У CatBoost
финальное число итераций — медиана внутренних результатов четырёх folds.

`folds/` хранит модели, полные OOF и время/пик RSS процесса; `experiments/` — OOF
всех смесей, метрики до/после округления, срезы и причины допуска/отказа.
`experiment-log.csv` ссылается на полные записи. Метрика суммирует ошибки и target
по всем прогнозным задачам; повторные даты разных origins учитываются отдельно.
Bootstrap переносит одинаковые семидневные календарные блоки совместно между
folds. Это зависимые, ранее исследованные окна, а не новый независимый тест.

Повторный запуск требует другого каталога. `--resume` разрешает только точное
совпадение config, исходников ML, файлов данных, зависимостей, baseline и погоды;
готовые fold-файлы проверяются по checksum. Завершённые опыты не перезаписываются.
После изменения исходников используйте новое имя run. Незавершённые `.pending-*`
не используются как кэш. Данные, OOF, модели и snapshots остаются в `artifacts/`.

`selection.json` фиксируется до повторной диагностической оценки сентября–октября.
`diagnostic.json` запрещает рекомендацию при ухудшении более 0.003; другой кандидат
по этой диагностике не выбирается. `stability.json` содержит повтор с seed 20250926,
который не участвует в выборе. `complete.json` сообщает итоговое решение. Платформенный
score нового результата остаётся `null` до независимой проверки на платформе.

Только после проверки решения создайте новый release; при отказе сохраните
исходный baseline, а исследовательский CSV обозначьте как нерекомендованный:

```sh
export SCORE_MODEL="artifacts/score-improvement-v2-run01"
artifacts/.score-venv/bin/python -m ml train --dataset-dir "$DATASET_DIR" \
  --evaluation-report "$SCORE_RUN/selection.json" --artifact-dir "$SCORE_MODEL"
artifacts/.score-venv/bin/python -m ml submission --artifact-dir "$SCORE_MODEL" \
  --template "$DATASET_DIR/test_submission.csv" \
  --output "$SCORE_RUN/submission-score-improvement-v2.csv" \
  --preflight-output "$SCORE_RUN/submission-score-improvement-v2.preflight.json"
artifacts/.score-venv/bin/python -m ml forecast --artifact-dir "$SCORE_MODEL" \
  --start 2025-11-01 --end 2025-12-31 --output "$SCORE_RUN/forecast-for-backend.csv"
python -m scripts.package_ml_handoff --artifact-dir "$SCORE_MODEL" \
  --forecast "$SCORE_RUN/forecast-for-backend.csv" --output "$SCORE_RUN/ml-handoff.zip"
```

Если selection включает осадки, передайте `train --weather-factors` из того же
snapshot, checksum которого записан в selection. Компоненты ансамбля, профили,
погода и q90 финального ансамбля сохраняются в `model.joblib`; manifest по-прежнему
содержит ровно три model-файла. Backend получает готовый CSV и не исполняет модель.
Готовые submission, preflight и forecast больше не перезаписываются.

Фактические результаты серии: [отчёт](reports/score-improvement-v2.md).
