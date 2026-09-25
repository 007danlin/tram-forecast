# Реальный ML-пакет на tramflow.ru — 25.09.2026

Статус: **развёрнуто и проверено по публичному HTTPS**. Исполнитель — Codex
по прямому поручению Даниэля установить ML-пакет и исходники из GitHub на VPS.
Время основных проверок: 23:32–23:35 МСК. Это техническая проверка поставки,
не независимая приёмка качества модели Игорем.

## Версии и сохранность

- Прежний серверный checkout: `bdf2a3228503e8635cc12bf3b1ee80a3ba40af6c`,
  синтетический frontend/API, без ML mount.
- Исходники приложения, собранного на VPS: `88144ef30915a36cc31dfe2edd339c416c80acbb`
  в GitHub `main`. Его дерево точно совпало с проверенным `bac8b2c`;
  merge сохранил историю `main` и финальные протоколы/lifecycle-проверку.
- Следующий коммит фиксирует этот протокол и документацию; исполняемый код,
  Dockerfiles, зависимости и конфигурация сервисов им не меняются.
- Каталог кода на сервере: `/opt/tramflow`, ветка `main`; frontend `/srv/tramflow`.
- Docker Engine 29.8.1, Compose 5.5.1. Перед запуском корневой раздел имел
  72 GiB свободного места из 79 GiB. Новое нагрузочное испытание VPS не проводилось.

`sync-source.sh` обнаружил переписанную историю, нашёл точное прежнее дерево
в `8eebb2a88c5eac6d00b021199306b43fdfa7b234` и сохранил старый commit
в `refs/tramflow-backups/before-sync-20260925T203243Z-684796` перед переходом.
`reset --hard`, очистка локальных настроек и force push не использовались.

## Установленный пакет

| Поле | Значение |
|---|---|
| Архив | `/srv/tramflow-data/incoming/calendar-holiday-priority-v1.zip` |
| SHA-256 ZIP | `c5beb99d3fc10bca689b234caf71990378e9a705076481951b86edae8d61d5a9` |
| Release | `/srv/tramflow-data/releases/calendar-holiday-priority-v1` |
| Run | `handoff-4c8d04b97381c5f0aa654f1128d6c7833a46650a418e973af3287d59d4f6daf2` |
| SHA-256 forecast CSV | `81f26a3c327e90e68f776f284e9d5e7c5e70c08102ad83f6f8c9475f310864b7` |
| Состав прогноза | 14 640 строк, 10 маршрутов, 01.11–31.12.2025 |
| Модель | `calendar_holiday_hgbt`, operational, без погоды; № 5 — нулевой baseline |

Архив передан по SSH отдельно от Git, checksum сверен до импорта. Incoming и
releases закрыты правами родительских каталогов; они находятся вне корня сайта.
Backend получает release как `/data/handoff`, `RW=false`. HTTP читает проверенный
CSV, не исполняет joblib; `model_loaded=false` в ready здесь ожидаем.

## Выполненные команды

Первый переход со старой истории выполнялся через проверенный
`deploy/sync-source.sh`, извлечённый из `origin/main`: сначала `--check`,
затем `--apply`, с проверкой точного целевого SHA до сборки.
`python3 -m scripts.check_delivery` на VPS прошёл.

```sh
cd /srv/tramflow-data/incoming
sha256sum -c calendar-holiday-priority-v1.zip.sha256
cd /opt/tramflow
docker compose -f compose.server.yaml build backend
docker compose -f compose.server.yaml run --rm --no-deps -T \
  -v /srv/tramflow-data:/handoff \
  backend python -m backend.handoff.install \
  /handoff/incoming/calendar-holiday-priority-v1.zip \
  --output /handoff/releases/calendar-holiday-priority-v1
TRAMFLOW_HANDOFF_HOST_DIR=/srv/tramflow-data/releases/calendar-holiday-priority-v1 \
  bash deploy/update.sh
# Повтор в новой SSH-сессии: путь должен восстановиться из mount.
env -u TRAMFLOW_HANDOFF_HOST_DIR bash deploy/update.sh
```

Импорт не перезаписывает существующий release; эти команды описывают выполненный
запуск. Для следующей модели нужен новый каталог. Для обычного обновления кода
текущего пакета использовать [порядок поставки](../deploy/release.md).

## Результаты проверки

- `https://tramflow.ru/` отдаёт новую сборку; HTML и готовая карта побайтно
  совпали с файлами VPS. Сборка прошла `npm ci`, TypeScript/Vite и проверку карты.
- Публичный `/api/v2/handoff/ready`: HTTP 200, ожидаемый run, 14 640 строк.
- Backend healthy, `RestartCount=0`, `OOMKilled=false`, порт 8000 привязан
  только к `127.0.0.1`. Caddy-конфигурация побайтно сохранена, доступ не менялся.
- `backend.handoff.check` через **публичный HTTPS** сопоставил исходный локальный
  CSV, почасовой API, дневные суммы и экспорт для всех 10 маршрутов
  01.11.2025 и 31.12.2025.
- Отдельный Chrome проверил реальный день, неделю, оба месяца, № 5 и последний
  день, значения таблицы/total и скачанный CSV. Допуск чисел:
  `1e-9 + 1e-12*abs(expected)`. Карта сохранялась; проверены 1366×768,
  390×844 и зона America/Los_Angeles; ошибок JavaScript нет. В публичном smoke
  ответы не подменялись, искусственные ошибки в production не создавались.
- Повторный `update.sh` без переменной пути восстановил mount из существующего
  контейнера и успешно проверил тот же run напрямую и через HTTPS.

Команда сквозной сверки с разрешённой локальной копией release:

```sh
python -m backend.handoff.check --base-url https://tramflow.ru \
  --release artifacts/releases/calendar-holiday-priority-v1
```

Скриншоты и одноразовый browser smoke сохранены локально в
`artifacts/verification/vps-2026-09-25/`, вне Git.

## Резервные копии и пределы проверки

Полная исходная резервная копия до установки ML:
`/opt/tramflow-backups/pre-handoff-20260925T203206Z-88144ef`.
Она содержит прежние frontend, Caddyfile, Compose, Git bundle, описание контейнера
и ссылку на прежний образ `tramflow-backend:pre-handoff-88144ef`.

Этот образ действительно запущен на отдельном временном loopback-порту VPS:
health и прежние шесть значений synthetic API совпали. Тестовый контейнер затем
остановлен и удалён. Наличие прежней статики и неизменность Caddy подтверждены.
**Полное переключение живого сайта назад не выполнялось**; автоматического
отката обоих компонентов updater не добавляет.

Дополнительные backup-каталоги updater:
`/opt/tramflow-backups/20260925-233318-88144ef` и
`/opt/tramflow-backups/20260925-233458-88144ef`.
Первый соответствует переходу со старого приложения, второй — уже новой версии
с ML. При восстановлении нельзя смешивать image, frontend и release разных копий.
Прежние каталоги `/srv/tramflow-before-*` сохранены.

Публичный сервер не подвергался нагрузке 200 RPS. Локальные цифры и ограничения —
[в нагрузочном протоколе](verification-load.md). Маска ночных технологических
валидаций и независимая приёмка обучения остаются отдельными задачами;
деплой не меняет измеренное качество или ограничения модели.
