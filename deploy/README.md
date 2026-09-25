# Серверный запуск

Подготовленная конфигурация для Ubuntu 24.04, Docker Engine с Buildx/Compose
и Caddy как systemd-службы на хосте. 2026-09-21 Даниэль подтвердил health API
и график по публичному IPv4 после ручного развёртывания. HTTPS ещё не проверен:
ожидается делегирование домена. Это сообщение пользователя, не автоматическая проверка VPS.
Приложение выдаёт синтетический пример, не прогноз обученной модели.

Схема: Caddy → React в `/srv/tramflow`; `/api/*` → FastAPI на `127.0.0.1:8000`.
Префикс `/api` сохраняется. Node нужен только в контейнере сборки.
Vite preview на сервере не запускается.

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

В браузере по IPv4 должны появиться график, таблица и маркировка тестовых данных.
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
- Реальных данных и весов нет. Их хранение, резервное копирование и ограничения
  памяти предстоит определить после выбора модели. Не добавляйте их в Git/образ автоматически.

## Обновление одной командой

После включения серверной конфигурации и полной карты в `main`, из `/opt/tramflow` под root:

```sh
git pull --ff-only origin main && bash deploy/update.sh
```

Команда получает код и готовую карту, собирает frontend в отдельной папке, проверяет,
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
snapshot). Mounted volumes в snapshot не входят; текущий backend их не использует.
