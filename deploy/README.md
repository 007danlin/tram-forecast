# Серверный запуск

Инструкции описывают текущую реализацию. Порядок поставки, проверка комплектности
и переход VPS после изменения истории Git — в [release.md](release.md).
Публикация исходников и обновление действующего VPS выполняются отдельно.

25.09.2026 выполнено обновление `tramflow.ru` из кода `88144ef` и установка
`calendar-holiday-priority-v1`; публичный handoff/UI/CSV и повторный updater
прошли проверку. [Протокол, версии и резервные копии](../docs/verification-deployment-2026-09-25.md).

Подготовленная конфигурация для Ubuntu 24.04, Docker Engine с Buildx/Compose
и Caddy как systemd-службы на хосте. 2026-09-21 Даниэль подтвердил health API
и график по публичному IPv4 после ручного развёртывания. Позднее пользователь
подтвердил HTTPS на tramflow.ru; запись сохранена в INTEGRATION.md.
Это сообщения пользователя, не новая автоматическая проверка VPS.
Команды базового запуска ниже обслуживают synthetic v1. Для выдачи готового ML CSV
нужны отдельный пакет, его импорт и `compose.handoff.yaml`; полный порядок —
[в инструкции handoff](../backend/handoff/README.md#командиру-файлы-и-запуск-на-сервере).
Текущий frontend обращается к handoff. Без установленного пакета он показывает
ошибку готовности и возможность повтора; synthetic v1 остаётся доступным через API.

Схема: Caddy → React в `/srv/tramflow`; `/api/*` → FastAPI на `127.0.0.1:8000`.
Префикс `/api` сохраняется. Node нужен только в контейнере сборки.
Vite preview на сервере не запускается.

Подготовлен отдельный [вариант защищённого доступа жюри](access.md)
(`Caddyfile.protected`). Он проверен локально и не включён автоматически на VPS.
Для защищённого сайта `update.sh` использует закрытый `TRAMFLOW_NETRC_FILE`;
проверка доступа выполняется до изменения сервисов. Пароли в репозитории не хранятся.

## Отдельный ML-инференс на VPS

Отдельный Docker-инференс B2 установлен и проверен на действующем VPS 27.09.2026:
`tramflow-inference:b2-20260927`, Linux AMD64. Исходники находятся в `/opt/tramflow`,
веса/sample и результаты — отдельно в `/srv/tramflow-data/inference/b2-20260927-r01/`.
[Проверки, измерения и команды повторного расчёта](../docs/submission-final/docker-inference-verification.md#публикация-и-проверка-на-vps--27092026).
Это явно запускаемый batch CLI; для его использования `deploy/update.sh`
и перезапуск веб-сервиса не нужны. Действующий HTTP продолжает выдавать B2 handoff.

## Первый запуск

Команды выполнять на сервере из `/opt/tramflow` под root.
Не запускайте одновременно локальный `compose.yaml`: он использует тот же порт backend.

```sh
docker build -f deploy/frontend.Dockerfile --output type=local,dest=/srv/tramflow .
chmod -R a+rX /srv/tramflow
docker compose -f compose.server.yaml up -d --build --wait --wait-timeout 120
curl --fail http://127.0.0.1:8000/api/v1/health
caddy validate --config /opt/tramflow/deploy/Caddyfile.http --adapter caddyfile
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-tramflow
cp deploy/Caddyfile.http /etc/caddy/Caddyfile
systemctl reload caddy
curl --fail http://127.0.0.1/api/v1/forecast
```

В браузере по IPv4 должны появиться карта и экран прогноза. Для значений графика
и таблицы установите ML-пакет по инструкции handoff; без него ожидается сообщение
о недоступных данных.
Проверьте доступность с другого компьютера. До HTTPS не вводите чувствительные данные.

## HTTPS после обновления DNS

`tramflow.ru` должен указывать на IPv4 VPS, порты 80/443 должны быть доступны извне.
AAAA допустима только при рабочем IPv6. Шаблон обслуживает основной домен;
поддержка `www` пока не включена.

```sh
caddy validate --config /opt/tramflow/deploy/Caddyfile.https --adapter caddyfile
cp deploy/Caddyfile.https /etc/caddy/Caddyfile
systemctl reload caddy
journalctl -u caddy -n 60 --no-pager
curl --fail https://tramflow.ru/api/v1/health
```

Caddy получает и продлевает сертификат автоматически. Сохраняйте его состояние
в `/var/lib/caddy`. DomainSSL Рег.ру не используется.

## Эксплуатация и ограничения

- `restart: unless-stopped` запускает backend после перезапуска Docker/сервера,
  если контейнер не остановлен вручную. Healthcheck не перезапускает зависший процесс.
- Docker-логи backend ограничены тремя файлами по 10 МБ.
- Лимиты CPU/RAM не заданы; подобрать их после измерения потребления модели.
- `docker compose -f compose.server.yaml logs --tail=100 backend` — диагностика API.
- Обновления приложения ручные; GitHub Actions выполняет только CI.
- Перед обновлением сохраняйте прежнюю статику и версию backend для отката.
  Сборка в `/srv/tramflow` не обеспечивает атомарное переключение версий.
- Данные и веса не входят в Git/образ. Для handoff предусмотрены отдельные каталоги
  incoming/releases и read-only mount; их резервировать отдельно от образа.
  Установка пакета на VPS и пределы потребления RAM здесь не подтверждены.

## Обновление одной командой

Текущий updater подключает `compose.handoff.yaml`, если явно задан
`TRAMFLOW_HANDOFF_HOST_DIR` или такой mount есть у существующего backend.
Учитывается и остановленный контейнер. Новый пакет проверяется до замены сервиса;
после запуска сверяется готовность ожидаемого run напрямую и через сайт.
Для первой установки и смены release укажите путь явно. Если контейнер удалён,
автоматически восстановить выбранный путь нельзя — задайте его из резервной копии.

После публикации проверенной версии в `main`, из `/opt/tramflow` под root
(первый переход со старого checkout описан в [release.md](release.md)):

```sh
bash deploy/sync-source.sh --apply && bash deploy/update.sh
```

Команда проверяет и получает код с готовой картой, собирает frontend в отдельной папке, проверяет,
что карта попала в сборку, пересобирает backend и ждёт healthcheck. Затем переключает
статику и сверяет HTML и карту по HTTPS с файлами на диске. Для другого домена задайте
`SITE_URL`. Node/Python на VPS для подготовки карты не требуются.

Прежняя статика сохраняется в `/srv/tramflow-before-*` и `/opt/tramflow-backups/`,
образ backend получает тег `tramflow-backend:backup-*`. Срок хранения пока ручной.
Переключение каталогов имеет короткое окно недоступности; backend и frontend
обновляются последовательно, автоматического отката backend нет. При ошибке
скрипт останавливается и не сообщает об успехе.

Первый переход со старого ручного деплоя: сохраните `compose.server.yaml`, `deploy/`
и локальную карту вне checkout перед первым pull, если Git сообщает, что они
будут перезаписаны. Не используйте `reset --hard` или `clean` для обхода конфликта.
Сервер должен быть на ветке `main`; изменения команды сначала сливаются туда.

Полная карта Артёма поставляется вместе с кодом. Перед использованием на VPS
получите main с этими изменениями. Сам `git pull` не пересобирает сервисы.

Если исходный образ работающего backend уже удалён, скрипт резервирует сам
контейнер через `docker container commit` (кратко приостанавливая его на время
snapshot). Mounted volumes в snapshot не входят; каталог handoff-пакета
потребует отдельной резервной копии.
