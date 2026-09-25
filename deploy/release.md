# Поставка из GitHub и переход действующего VPS

Этот порядок используется после проверки и публикации итоговых изменений в
`main`. Наличие файла в рабочей папке не означает, что GitHub или VPS обновлены.
Данные, модель, release и credentials передаются отдельно от исходников.

## Комплектность исходников

Из корня репозитория:

```sh
python3 -m scripts.check_delivery
```

Проверка завершается ошибкой, если есть неотслеживаемые файлы, пропали обязательные
файлы приложения, документация ссылается на неотправленный файл или в составе
Git оказались локальные данные/веса/credentials. Перед первой отправкой новых
исходников ошибки «Not included in Git» ожидаемы: нужно просмотреть файлы и
включить нужные в поставку. Команда ничего не добавляет, не коммитит и не отправляет.
Игнорируемые `artifacts/`, `output/`, `tmp/`, окружения и зависимости в поставку
не входят. CI повторяет эту проверку на настоящем checkout.
Сгенерированные `output/md/tramflow-team-specs.md` и
`output/pdf/tramflow-team-specs.pdf` также не отслеживаются; исходный комплект
сохранён в [docs/team-specs](../docs/team-specs/README.md). Локальные копии
можно хранить в `output/`, добавлять исключения для них в checker не нужно.

Проверка не доказывает отсутствие любого возможного секрета; содержимое изменений
перед отправкой всё равно просматривается. Файлы данных не надо добавлять в Git
для прохождения проверки. Для реального UI нужен отдельно установленный ML-пакет.

## Получение кода сервером

На VPS работать из `/opt/tramflow`, ветка `main`. `sync-source.sh` по умолчанию
делает только fetch и проверку, не меняя checkout или сервисы:

```sh
bash deploy/sync-source.sh --check
bash deploy/sync-source.sh --apply
```

Если `main` можно передвинуть вперёд, используется fast-forward. Если история
была переписана (например, изменены даты старых коммитов), скрипт сначала ищет
**точно такое же дерево файлов текущего VPS** среди предков нового `origin/main`.
Только при таком совпадении допускается переход. При расхождении кода или
незакоммиченных/неотслеживаемых файлах он останавливается до изменения checkout.

Перед переходом старый commit сохраняется в `refs/tramflow-backups/before-sync-*`.
Используются `merge --ff-only` либо `reset --keep`; `reset --hard`, `clean`
и force push не применяются. Игнорируемые данные и настройки не очищаются.
Скрипт не собирает образы, не меняет Caddy и не перезапускает контейнеры.

### Первый переход, если скрипта ещё нет в старом checkout

После включения скрипта в GitHub `main`, на VPS:

```sh
cd /opt/tramflow
git fetch origin main
sync_script=$(mktemp /tmp/tramflow-sync.XXXXXX)
git show origin/main:deploy/sync-source.sh > "$sync_script"
bash "$sync_script" --check
# После успешной проверки:
bash "$sync_script" --apply
rm -- "$sync_script"
```

Не заменять этот порядок обычным `git pull`, если истории разошлись: merge двух
историй не нужен. Резервную ссылку можно посмотреть командой:

```sh
git for-each-ref --format='%(refname) %(objectname)' refs/tramflow-backups
```

## Установка реального прогноза

На машине автора совместимый архив создаёт `scripts/package_ml_handoff.py`,
а рядом создаётся `<archive>.sha256`. Параметры и ограничения — в
[памятке ML](../ml/README.md) и [контракте handoff](../backend/handoff/README.md).
На сервер отдельно передаются архив и его checksum в `/srv/tramflow-data/incoming/`.
Перед импортом проверить checksum в этом каталоге через `sha256sum -c`.

Из `/opt/tramflow`, после синхронизации кода:

```sh
docker compose -f compose.server.yaml build backend
docker compose -f compose.server.yaml run --rm --no-deps \
  -v /srv/tramflow-data:/handoff \
  backend python -m backend.handoff.install \
  /handoff/incoming/tramflow-ml-handoff-v1.zip \
  --output /handoff/releases/ml-handoff-v1

export TRAMFLOW_HANDOFF_HOST_DIR=/srv/tramflow-data/releases/ml-handoff-v1
bash deploy/update.sh
```

Каталог release должен быть новым: импорт не перезаписывает прежнюю версию.
Upgrader проверяет пакет новым backend-образом до замены работающего контейнера,
сохраняет прежние image/frontend и пути обоих release. После запуска он проверяет
готовность **ожидаемого run**, затем повторяет проверку через публичный HTTPS.
Для защищённого сайта дополнительно нужен закрытый `TRAMFLOW_NETRC_FILE`;
см. [доступ жюри](access.md). Веса не копируются в образ и не исполняются backend.

Для следующих обновлений того же пакета достаточно:

```sh
bash deploy/sync-source.sh --apply
bash deploy/update.sh
```

Updater определяет mount существующего контейнера, в том числе остановленного,
поэтому путь не теряется после выхода из SSH-сессии. Для смены пакета снова
явно задать `TRAMFLOW_HANDOFF_HOST_DIR` с новым release. Если контейнер удалён,
путь нужно указать заново; сохранённые пути есть в резервной копии updater.
Нестандартный mount без явного пути вызывает отказ, а не отключение handoff.

## Приёмка после обновления

```sh
curl --fail https://tramflow.ru/api/v2/handoff/ready
docker compose -f compose.server.yaml -f compose.handoff.yaml \
  exec -T backend python -m backend.handoff.check \
  --base-url https://tramflow.ru --release /data/handoff
```

Для второй команды переменная `TRAMFLOW_HANDOFF_HOST_DIR` должна быть задана
в текущей сессии. На защищённом сайте checker не передаёт Basic Auth: запускать
его с `--base-url http://127.0.0.1:8000` внутри контейнера, а публичную готовность
и интерфейс проверять с разрешённой авторизацией. Updater уже поддерживает netrc
для публичной проверки ready.

В браузере проверить день, неделю, декабрь, baseline маршрута 5 и CSV.
Сверяются версия run и значения исходного пакета, не качество обучения.
HTTP v1/healthy сами по себе не являются приёмкой реального прогноза.

## Границы восстановления

Предыдущие frontend/image и пути release сохраняются в `/opt/tramflow-backups/`,
старая статика также остаётся в `/srv/tramflow-before-*`. Данные release и
состояние Caddy в `/var/lib/caddy` резервируются отдельно; image snapshot не
содержит bind mounts. Старые каталоги не удалять до приёмки новой версии.

Переключение backend и статики последовательное, автоматического отката обоих
компонентов пока нет. При сбое updater останавливается и не сообщает об успехе.
До восстановления выбрать именно предыдущие image, frontend и release из одной
резервной копии; не смешивать их с новым run. Ссылка `before-sync-*` сохраняет
исходники, а не состояние работающего контейнера или данные.
