# Контейнерное воспроизведение B2 — 27.09.2026

**B2 воспроизведён в Docker и подключён к локальному handoff.**
Отдельный образ Python 3.12.14 выполнил два независимых полных расчёта B2
без fit, сети и доступа к готовым ответам. Submission и float совпали **побайтно**
с принятыми CSV. Это локальная приёмка batch inference; score платформы не
пересчитывался, первоначальное обучение не повторялось.

Полные команды — [ml/inference/README.md](../../ml/inference/README.md).
Проверка: `python3 -m scripts.verify_container_inference prepare|run|compare`;
на хосте нужны только стандартная библиотека Python 3.11+ и Docker CLI.

После отдельного разрешения выполнены публикация в Git и такая же приёмка
на Linux AMD64 VPS: [серверные результаты и команды](#публикация-и-проверка-на-vps--27092026).
Локальный протокол ниже сохранён как отдельный этап.

## Модель, входы и изоляция

Исходник — G0 из локальной приёмки B2 26 сентября, каталог
`artifacts/submission-final/b2-acceptance-20260926/g0/`. Все **303** записи
`bundle-manifest.json` повторно проверены. Ни один файл исходного G0 не изменён.
Связь champion.csv с 0,84260 основана на прежнем подтверждении Даниэля,
описанном в [приёмке B2](b2-acceptance.md); исследовательские v4 не выбирались.

| Файл | SHA-256 |
|---|---|
| model.joblib | `39edd75e265102f5973d14acd94bd4ae75a0473f12b7d07e47e2dc8b32eb9942` |
| Исходный sample | `71c8126bb51068c936462a170da885bad860fc91a58b3d2ac731876d324d7ec3` |
| submission.csv | `505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94` |
| forecast.csv | `f60caf48d1ce5d5066eaa4c6e74dc34454648b372d715efb1ad2b735dbf3ac4c` |

База `python:3.12.14-slim-bookworm`, OCI index digest
`sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e`;
платформенный manifest linux/arm64/v8
`sha256:eb5be8e5b4d0a159c237946bbdd06356dda5d19c30fc4f7843e8046d3a590333`.
Image ID первой приёмки:
`sha256:5d49186648d206237ac911016e1c022733a56c26994a3d96676424b9826cd6a9`.
Python **3.12.14**, Linux aarch64, Docker Engine 29.4.0 / Desktop 4.70.0,
kernel 6.12.76-linuxkit. VM: 10 видимых CPU, 8 321 712 128 bytes RAM;
это ресурсы VM, не выделенный контейнеру профиль. Все 15 inference pins сохранены,
Linux wheels установились, `pip check` прошёл.

Каждый вызов — новый контейнер с `NetworkMode=none`, 2 CPU, memory=memory-swap=
4 294 967 296 bytes, read-only rootfs и отдельным `/tmp` tmpfs. Cgroup подтвердил
`cpu.max=200000 100000`, `memory.swap.max=0`. OMP/OpenBLAS/MKL/NumExpr/LOKY = 2.
`/model` содержит ровно четыре неизменённых файла, sample — отдельный read-only
file mount. Каждый успешный вызов получает новый пустой выходной подкаталог: submission
не видит даже float предыдущего вызова. Записывается только этот каталог. Inspect каждого
контейнера проверен программно; G0, репозиторий, Downloads и эталоны не смонтированы.
Образ копирует явный список исходников и requirements; исходный `.dockerignore`
сохранён. Текущий backend Dockerfile не превращён в ML-сервис.

## Результаты автоматизированной проверки

| Проверка | Результат |
|---|---|
| Два полных forecast + submission | Четыре разных контейнера, 14 640 строк в каждом файле; SHA равны эталонам и друг другу |
| Ключи, порядок, округление | Полная сетка 61 × 10 × 24; все DS = floor(float + 0.5), оба preflight passed |
| Float | Prediction, reference, lower/upper, priority и status точны; 0 численных различий, max absolute/relative error 0 |
| № 5 | 1 464 нуля, `cold_start_zero_baseline`; это fallback, не обученная модель маршрута |
| 01.11, 15.11, 31.12 отдельно | По 240 строк, все поля и порядок совпали со срезами полного расчёта |
| Подмена prediction в копии sample | Контрольные 900000+i не повлияли на SHA submission; preflight passed |
| Ошибочные входы | Отсутствующий model, повреждённый model, неверная checksum и дубли sample возвращают ошибку; успешного preflight/fallback нет |
| Существующие выходы | Forecast, submission и preflight не перезаписаны |
| Неизменность | SHA исходных и отдельно смонтированных model/sample до/после равны |
| Fit | Python-вызовы fit/partial_fit/fit_transform ML/sklearn запрещены наблюдателем; попыток 0 |

Первый этап `run` проверяет выполнение сценариев, второй `compare` независимо
читает эталоны. Оба завершились exit 0. Численный допуск не вводился; при
расхождении сравнение сохраняет diff и возвращает exit 1. Успех запуска без
успеха отдельного сравнения не считается воспроизведением B2.

## Измерения итогового прогона r02

| Вызов | docker start --attach, с | CLI с импортами и записью, с | predict_artifact, с | Пик RSS процесса, KiB |
|---|---:|---:|---:|---:|
| forecast 1 | 3,150 | 2,786 | 1,375 | 188 728 |
| submission 1 | 3,282 | 2,940 | 1,417 | 188 800 |
| forecast 2 | 3,050 | 2,719 | 1,400 | 188 820 |
| submission 2 | 3,188 | 2,847 | 1,376 | 188 764 |

Полный forecast — 14 640 строк, обе даты CLI включены. `predict_artifact`
включает проверку manifest, загрузку модели, prediction/reference и интервалы;
это не время только вызова sklearn.predict. Время `docker create` отдельно
сохранено в JSON и не входит в колонку start/attach. Измерения включают лёгкий
Python profile-наблюдатель; прямой entrypoint также проверяется отдельно.
Пик RSS измерен Linux `getrusage`, максимум четырёх вызовов **184,39 MiB**.
Cgroup memory.peak отдельно 141 627 392–141 963 264 bytes; shared-page/RSS и
cgroup accounting различаются, эти величины не смешиваются. OOM/oom_kill = 0.
Это четыре наблюдения на локальной машине, **не p95, не RPS и не VPS**.
Предыдущие 200 RPS/p95 относятся к выдаче готового handoff.

## Доказательства и комплект

Рабочий корень: `artifacts/inference-docker/b2-20260927-r02/` (исключён из Git).

- `prepared/report.json` — проверка 303 G0 hashes, выделенные входы и эталоны.
- `build.log` — установка pins, pip check, образ.
- `acceptance/report.json`, `acceptance/commands/`, `*.metrics.json` — команды,
  exit codes, stdout/stderr, inspect, ресурсы, версии, preflight, hashes.
- `comparison/report.json` — независимая сверка обоих запусков и трёх дат.
- `web/` — новый ZIP/release, API/CSV и браузерные доказательства.
- `delivery/` — отдельные sources.zip, inputs, references и evidence;
  `SHA256SUMS` связывает файлы. Модель/sample/прогнозы не входят в source ZIP.

## Локальный handoff и браузер

Вычисленный `acceptance/run-1/forecast/forecast.csv` упакован существующим
`scripts.package_ml_handoff` и импортирован `backend.handoff.install` в новый
`web/release/`. ZIP SHA `7a4cdefbc8de5348242cafd023a5eae98498821e3aa4ff7b954c7e4356241262`.
Новый каталог смонтирован read-only в **отдельный** `tramflow-inference-qa`.
Из-за точного совпадения пяти файлов остался прежний run
`handoff-dd668e2870ae1b4069c689811d15ae6c5f6ff7668e4db04c64a452d4e30d03ed`;
время нового импорта — `2026-09-27T08:24:56.660910Z`.

Штатный handoff-check через frontend-прокси подтвердил 10 маршрутов,
01.11/31.12: исходный новый CSV = hourly API = daily sums = pinned export.
Браузер показал те же model/float SHA и новый импорт в паспорте. Суммы № 1:
18 852,50967383226 за 01.11 и 5 284,962178627168 за 31.12; № 5 — 0 с подписью
об отсутствии истории. Эти DOM-значения независимо сверены с новым float.
Ошибок JavaScript нет. Снимки и `web/browser.json`, `web/verification.json`
сохранены локально. Это ограниченный просмотр продукта, не новый полный
браузерный регрессионный прогон. Публичный сайт и прежние локальные проекты не менялись.

Первый web-smoke выявил только ограничения тестовой накладки: internal network
Docker Desktop не публиковала loopback-порты, а Vite отклонял hostname frontend.
Итоговая явная накладка использует отдельную bridge-сеть, localhost-порты
15187/18107 и разрешает ровно frontend; мониторинг выключен. После исправления
проверка прошла. Вычислительные контейнеры по-прежнему имеют network none.

## Проверенная поставка исходников

`scripts.package_submission_prep` проверил ZIP CRC, точный состав и SHA каждого
из 323 файлов исходников/документации. Dockerfile, measure.py, stdlib verifier,
web-overlay, pins и инструкция включены. Новые файлы добавлены в проверенный
include-list; пропущенный untracked Dockerfile теперь останавливает упаковку.
Данные и веса исключены из source ZIP. 38 tooling-тестов прошли, включая
проверки ложного успеха сравнения и фактического содержимого исходного архива.

В `clean-final/` распакован проверенный итоговый source ZIP, model/sample и эталоны
переданы отдельно. Образ собран `--no-cache` без developer-venv; его отдельный image ID
и метаданные записаны в `clean-final/acceptance/report.json`.
Из этого каталога повторены все 15 контейнерных сценариев и отдельный compare:
оба этапа passed, те же SHA и нулевые различия. Нет обращения к личным Downloads,
host Python исполнял только stdlib-проверку. Логи `clean-build.log`,
`clean-final/acceptance/` и `clean-final/comparison/` сохраняют отдельный повтор.
Различный ID при повторной сборке не означает смену модели; проверены версии,
входы и точные выходные байты. Побайтная воспроизводимость слоёв образа не заявляется.

Финальное дополнение `delivery/` содержит итоговый sources.zip с последней
документацией, отдельные inputs/references и оба набора evidence. README комплекта
даёт запуск без исходного Git checkout. Сборка/прямой entrypoint из его распаковки
фиксируются в `delivery/evidence/final-source/verification.json`; проверка
MANIFEST.sha256 и сверка runtime-файлов связывают этот архив с полным повтором.
Рядом создаётся `tramflow-b2-docker-20260927.zip` и его SHA256; это локальный
дополнительный комплект, не публикация и не замена прежних A1–A6/receipt.

Первый инженерный проход `b2-20260927-r01` сохранён отдельно: там два вызова
одной пары видели общий output. После ревью mounts это исправлено, добавлена
регрессия отказа от повторного использования каталога. Итоговая приёмка r02
и чистый повтор используют отдельный пустой output для каждого расчёта;
первый проход не используется как доказательство этой изоляции.

## Публикация и проверка на VPS — 27.09.2026

Реализация `63df056` объединена с обновлённым `main` в `a75fa75` и отправлена
в `main` / `server-deployment`. Новые G0/G2 материалы и исправление browser
contract сохранены. Для этого commit успешны CI
([main](https://github.com/MISISion-Possible/tram-forecast/actions/runs/36306953789),
[server-deployment](https://github.com/MISISion-Possible/tram-forecast/actions/runs/36306953648))
и Handoff browser contract
([main](https://github.com/MISISion-Possible/tram-forecast/actions/runs/36306953631),
[server-deployment](https://github.com/MISISion-Possible/tram-forecast/actions/runs/36306953698)).
Локальные 38 tooling-тестов и проверка комплектности прошли после объединения.

Серверный `/opt/tramflow` перешёл с `98cd152` штатным fast-forward;
резервная ссылка `refs/tramflow-backups/before-sync-20260927T084124Z-939610`.
Образ собран из commit `a75fa75` с `--no-cache --platform linux/amd64`,
тег `tramflow-inference:b2-20260927`, ID
`sha256:542334d87b51e306fde5f4074f752ad4364627a21f55a57aaaa625cf80d9e43e`.
База и 15 pins те же, `pip check` passed. VPS: x86_64, AMD EPYC 7763,
4 видимых CPU, 8 219 213 824 bytes RAM, kernel 6.8.0-139-generic,
Docker 29.8.1; host Python 3.12.3 исполняет только stdlib-проверку.
Контейнерный Python 3.12.14, лимиты 2 CPU / 4 GiB / swap 0, пять thread
settings = 2, network none, узкие read-only model/sample и отдельные outputs.

Все **15** сценариев `run` и независимый `compare` прошли без допуска.
Оба float и DS дали исходные SHA из таблицы выше, 14 640 строк, 0 численных
различий и точное округление; № 5 — 1 464 нуля. Проверены три отдельных дня,
подмена prediction sample, повреждённые/отсутствующие входы и защита outputs.
Fit attempts и OOM = 0. Отдельные прямые forecast/submission через обычный
entrypoint без wrapper также дали точные SHA и preflight passed.

| Вызов | docker start --attach, с | CLI, с | predict_artifact, с | Пик RSS, KiB |
|---|---:|---:|---:|---:|
| forecast 1 | 11,255 | 10,393 | 5,315 | 191 276 |
| submission 1 | 11,910 | 11,063 | 5,482 | 191 140 |
| forecast 2 | 10,753 | 9,885 | 5,093 | 191 288 |
| submission 2 | 12,011 | 10,981 | 5,464 | 191 152 |

Максимум RSS **186,80 MiB**; cgroup memory.peak отдельно
140 132 352–140 591 104 bytes. Это четыре наблюдения VPS с измерительным
wrapper, не p95/RPS и не нагрузочный тест HTTP.

Входы переданы с отдельного явного разрешения в закрытый каталог
`/srv/tramflow-data/inference/b2-20260927-r01/`; SHA всех семи файлов проверены
до вычислений. Там сохранены `prepared/`, `acceptance/`, `comparison/`,
`direct/`, build/run/compare logs и `service-verification.json`.
Локальная копия доказательств — `artifacts/inference-docker/b2-vps-20260927-r01/`.
Этот серверный этап не переписывает ранее собранный локальный ZIP r02.

Повторить расчёт на VPS (новое имя output обязательно):

```sh
cd /opt/tramflow
export B2_INPUTS=/srv/tramflow-data/inference/b2-20260927-r01/prepared
export B2_REPEAT=/srv/tramflow-data/inference/b2-repeat-$(date -u +%Y%m%dT%H%M%SZ)
umask 077
mkdir "$B2_REPEAT"
python3 -m scripts.verify_container_inference run \
  --image tramflow-inference:b2-20260927 \
  --model-dir "$B2_INPUTS/model" --template "$B2_INPUTS/input/test_submission.csv" \
  --output-dir "$B2_REPEAT/acceptance"
python3 -m scripts.verify_container_inference compare \
  --run-dir "$B2_REPEAT/acceptance" \
  --reference-forecast "$B2_INPUTS/references/forecast.csv" \
  --reference-submission "$B2_INPUTS/references/submission.csv" \
  --output-dir "$B2_REPEAT/comparison"
```

Действующий сервис сохранён: ID, image, StartedAt и RestartCount backend
до/после совпали; SHA всех файлов `/srv/tramflow` равны. Публичный HTTPS ready
возвращает прежний B2/run, штатный handoff-check прошёл. Веб-контейнер не
перезапускался, release не заменялся. После проверки остался только прежний
backend; вычислительные контейнеры завершены и удалены, образ и входы сохранены.

## Ограничения

Модель, HTTP-контракты, CSV-формат, интерфейс, веса и округление не менялись.
Контейнерный batch не исполняется на каждом HTTP-запросе. Сеть при сборке допустима;
выполнение готового образа автономно. Параметризованные даты не являются тестом
неописанного потокового протокола организаторов, NDTP или онлайн-обучения.
Проверены Linux ARM64 и Linux AMD64 на указанном VPS. Другие архитектуры,
первоначальное обучение, качество на новых данных, рост score и полное
прохождение проверки жюри не подтверждаются. Commit/push и серверная установка
отдельного inference выполнены на следующем этапе выше; конкурсной отправки не было.
