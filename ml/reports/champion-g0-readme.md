# B2: воспроизводимый пакет исходного ансамбля

26.09.2026. Champion `calendar_interaction_ensemble` сохранён, новый fit не выполнялся.
Даниэль подтвердил связь champion.csv с platform **0,84260**; снимок успешной
строки от 18:50 описан в командной приёмке. Стабильного ID/receipt формы нет,
а байты PNG в этом checkout отсутствуют. Adaptive 0,83543 остаётся `reported_by_user`.
Адаптивный № 50: **0,83543**, отклонён; исходный CSV остаётся лучшим.

## Быстрый запуск без обучения

Распаковать комплект в новый каталог. Из корня распакованного пакета:

```sh
python3.12 -m venv /absolute/path/to/new-venv
/absolute/path/to/new-venv/bin/python -m pip install -r requirements-inference.lock
cd source
/absolute/path/to/new-venv/bin/python -m ml submission \
  --artifact-dir ../model --template ../template.csv --scope sample \
  --output /absolute/path/to/new-output/submission.csv \
  --preflight-output /absolute/path/to/new-output/preflight.json
shasum -a 256 /absolute/path/to/new-output/submission.csv
```

Ожидаемый SHA-256:
`505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94`.
14 640 строк; сумма 11 365 837; все 1464 строки № 5 нулевые.
Python 3.12, joblib 1.5.2, numpy/pandas 2.3.3, sklearn 1.7.2.
Полный lock относится к проверенному inference, не выдуманному training environment.
Не загружать непроверенный joblib: это исполняемая сериализация.

`verification/` содержит два независимых CLI inference/preflight, stdout,
версии и проверку всех 14 640 равенств `DS=floor(float+0.5)`.
`model/` — исходные четыре файла без изменения байтов; `bundle-manifest.json`
содержит SHA каждого передаваемого файла, ZIP имеет внешний `.sha256`.
Исходный metadata сохранил устаревший статус № 5: уточнение команды о разрешённых
нулях вынесено в `provenance.json`, а не внесено задним числом в артефакт.

## Выбор и оценка

Смесь `0.96 × (0.425 × calendar_holiday_hgbt + 0.575 × interaction_squared_hgbt)`.
Seed 20250925; train 01.01–31.10.2025. Target — успешные посадки, не загрузка салона.
Сохранены исходные evaluation/config/schema; параметры компонентов описаны
в `source/ml/reports/model-card.md`. Training commit/dirty state исходным manifest
не записаны: `provenance.json` оставляет их неизвестными. Commit снимка кода для
inference и точные hashes исходников записаны отдельно; это не training provenance.

| Проверка | Rounded score | Raw score | Строк | Σy | Rounded SAE |
|---|---:|---:|---:|---:|---:|
| B2 S1–S4 | 0,84484148 | 0,84483514 | 52 704 | 44 560 499 | 6 913 941 |
| B2 D, повторная диагностика | 0,82900943 | 0,8290147 | 13 176 | 12 754 481 | 2 180 896 |
| Платформа, подтверждение владельца + снимок строки | 0,84260 | — | — | неизвестно | неизвестно |

S1–S4: train заканчивается 30.04 / 31.05 / 30.06 / 31.07, origin следующий день,
горизонт каждого окна 61 день. D: origin 01.09, сентябрь–октябрь повторно использован
после прежних PR. S1–S4 пересекаются (153 уникальные даты), D пересекается с S4;
независимого blind holdout нет. `evidence/score-v3/` содержит завершённые
selection/journal/complete/fingerprint, OOF и fold-records. Серия не запускалась заново.
Лучший новый F1-B2: 0,84544143 (+0,00059995), ниже допуска +0,002.
Direct/daily/regime не дали принятой модели. Исторический отбор quality-085 на двух
окнах хранится отдельно; его 0,85055 нельзя смешивать с четырёхоконным результатом.

Для обучения *нового* артефакта, не как доказательства старого receipt:

```sh
python -m ml train --dataset-dir /absolute/path/to/dataset \
  --evaluation-report ../evidence/quality-085/evaluation.json \
  --artifact-dir /absolute/path/to/new-model
```

Исходный train/test не вложены и в этом run заново не сканировались.
Их исторические SHA есть в model/manifest; текущие hashes labels — в provenance.

## Передача Толе: только локальная приёмка

`forecast-float.csv` — внутренний неокруглённый прогноз с reference/interval/status.
`handoff-b2.zip` собран штатным `scripts.package_ml_handoff` по `ml-handoff-v1`.
Legacy-имена внутри ZIP — контракт упаковки, не имя фактической модели.
Точные run/model/CSV hashes: `verification/result.json` и
`handoff-local-check/receipt.json`. Установщик локально проверил manifest,
полную сетку 10×61×24, единственный baseline № 5 и Europe/Moscow.

```sh
python -m backend.handoff.install /absolute/path/to/handoff-b2.zip \
  --output /absolute/path/to/new-local-release
# После отдельного согласования подключения локального backend:
python -m backend.handoff.check --base-url http://127.0.0.1:8000 \
  --release /absolute/path/to/new-local-release
```

Сервер не обновлялся. По входному аудиту сайт использовал прежний
`calendar-holiday-priority-v1`, model SHA `70529f3ba3543a94645b3b064d745c79631a641bf7380b76c179bc59e01f3c5e`.
Это исторический снимок аудита, не новая проверка VPS. Score 0,84260 к нему не переносится.

## Ограничения и недостающая приёмка

9 моделируемых маршрутов + технический ноль № 5; прогноз 01.11–31.12.2025.
Суточные/месячные суммы — агрегаты часов, год только качественный. Stop/direction
не поддержаны; неизвестный маршрут/город/год требует mapping, календаря и валидации.
Raw timezone не подтверждён; скрытая конвертация не выполнялась, контракт продукта МСК.
Интервалы не гарантированные и не суммируются: историческое покрытие около 81,66%
при номинальных 90%. Новые сценарии ими не валидированы.
Из внешних факторов B2 использует только календарь; погода/трафик/события не включены.
Паспорт G2 передаётся дополнением без задержки этого пакета G0.

Открыто: стабильный submission ID/receipt формы и сам PNG в этом checkout;
receipt adaptive; оригинальный training commit/full lock;
сквозная приёмка Толи после разрешённого подключения; разрешённое размещение бинарников.
Без этих подтверждений не заявлять полный deployment или проверенный platform receipt.
