# B2 — передача G0/G2, 26.09.2026

**Champion: исходный `calendar_interaction_ensemble`. Platform score 0,84260
связан с champion.csv подтверждением Даниэля и снимком успешной строки.**
Стабильного submission ID/receipt формы нет; PNG отсутствует в этом checkout,
поэтому приложены только документы его независимой приёмки. Adaptive № 50
(сообщённые 0,83543 без receipt/скрина) отклонён и лежит
только в `evidence/adaptive/rejected-submission.csv` — не основной файл.

## Что передано

- `model/`: exact исходный joblib, metadata, schema и manifest.
- `config-extracted.json`: реальные параметры обоих компонентов/seed 20250925.
- `source/`, `provenance.json`, `requirements-inference.lock`: код/версии/hashes.
- `forecast-float.csv`: float, reference, interval, priority, status.
- `champion.csv`: конкурсный CSV 14 640 строк, все 1464 строки № 5 нулевые.
- `model-to-csv-manifest.json`: связь model→float→DS; `bundle-manifest.json`: все SHA.
- `verification/`: два независимых inference, preflight, stdout, версии, pip-check.
- `handoff-b2.zip`: штатный float handoff; локальный import receipt рядом.
- `G2-model-passport.md`, `sources/`: источники, receipts, абляции, ограничения.
- `v3-status-and-G1.md`, `evidence/`: завершённый v3 и отдельный отрицательный G1.
- `year-scenarios.json`: три качественных сценария, без численного прогноза.

## Повторить inference без обучения

Из корня распакованного пакета (выходные пути должны быть новыми):

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

Ожидаемый SHA: **`505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94`**.
Оба чистых запуска его воспроизвели; `floor(float+0.5)` совпал со всеми 14 640 DS строками.
Float SHA: `f60caf48d1ce5d5066eaa4c6e74dc34454648b372d715efb1ad2b735dbf3ac4c`.
Model SHA: `39edd75e265102f5973d14acd94bd4ae75a0473f12b7d07e47e2dc8b32eb9942`.
Сумма DS predictions 11 365 837. Не загружать joblib из недоверенного источника.

S1–S4 rounded **0,84484148**, reused D **0,82900943**; platform **0,84260 со слов**.
Это разные оценки. S-окна перекрываются, D уже использовался; нового blind holdout нет.
Серия v3 завершена без улучшения, но не все предложенные направления исследованы.
Новых fits не выполняли; пакет не подменён старым серверным release.

## Что отсутствует и что не выполнялось

Отсутствуют стабильный platform ID/receipt формы и сами байты упомянутого PNG,
receipt adaptive, exact original training commit/dirty state
и полный lock того обучения. Записанный commit `5bba4fd…` относится к исходникам
повторного inference; SHA файлов фиксируют точный состав. Новая B2 calendar-off
абляция не запускалась. Норма government.ru и T01 дали timeout; доступный официальный
календарь ЦБ сохранён и сверен. Трафик/события и timezone raw не подтверждены полностью.
Подробности, команды обучения *нового* артефакта и передачи Толе — `G0-detailed-readme.md`.

Годовые `recent_level/lower_service/higher_demand` означают сохранение профиля /
условное снижение обслуживания / условный рост спроса. `value=null`: это не ML-оценки,
не вероятности и не интервалы. Ручные коэффициенты — допущения пользователя,
не обученные эффекты и не прирост score; в champion.csv они не входят.

Commit/push/публикация/конкурсная отправка и серверное обновление **не выполнялись**.
API/UI-приёмка у Толи и разрешённое размещение бинарников остаются отдельными шагами.
Реальные модели/OOF/CSV в этом локальном архиве не предназначены для добавления в Git.
