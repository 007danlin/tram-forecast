# tram-forecast
TramFlow — AI Passenger Flow Forecasting

Минимальная заготовка для двухдневного хакатона команды из пяти человек.
Все значения синтетические: обученной модели и реального прогноза пока нет.

## Получить и запустить

Нужны Git, Python 3.12+ и Node.js 22.12+. Команды ниже для macOS/Linux.

```sh
git clone git@github.com:MISISion-Possible/tram-forecast.git
cd tram-forecast
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

В другом терминале из корня репозитория:

```sh
cd frontend
npm ci
npm run dev
```

Откройте [страницу](http://localhost:5173): статус подключения, тестовый график и таблица должны появиться после загрузки API.
Переменные необязательны; при необходимости скопируйте `.env.example` в `.env` в корне.
Параметры интеграции и API описаны только в [INTEGRATION.md](INTEGRATION.md).

Альтернатива с запущенным Docker Desktop / Docker Engine:

```sh
docker compose up --build
# Остановить и удалить контейнеры:
docker compose down
```

Адрес страницы тот же. Это локальная заготовка, контейнер frontend использует Vite preview.

## Кто где работает

| Участник | Область |
|---|---|
| Артём | `frontend/` |
| Толя | `backend/` |
| Георгий | Модель, признаки и оценка в `ml/` |
| Даниэль | Интерфейс ML, интеграция, архитектура |
| Игорь | `data/`, проверки данных и `tests/integration/` |

Каждый поддерживает документацию своей части и соответствующий раздел `INTEGRATION.md`.

## Короткая ветка и небольшой PR

1. Обновите основную ветку команды: `git switch main`, затем `git pull --ff-only` (если основная ветка называется иначе, используйте её имя).
2. Создайте ветку для одной задачи: `git switch -c codex/forecast-loading`.
3. Сделайте небольшое законченное изменение и проверьте его:

   ```sh
   .venv/bin/python -m unittest discover -s tests/integration -v
   npm run build --prefix frontend
   docker compose config --quiet
   ```

4. Для изменений UI откройте страницу; остановите backend, нажмите «Повторить запрос» и проверьте понятную ошибку. После запуска backend повторный запрос должен восстановить график.
5. При изменении интерфейса, формата, конфигурации или запуска обновите свой раздел `INTEGRATION.md` **в том же PR**. Несовместимое изменение сначала согласуйте с владельцем принимающей части.
6. Просмотрите `git diff` и `git status`, исключите реальные данные и секреты. Сделайте commit, отправьте свою ветку и откройте небольшой PR по шаблону. Попросите проверить владельца затронутой части.

Команды commit/push участник выполняет сам; подготовка заготовки их не выполняет.

[Что подготовлено заранее](docs/preparation.md) · [Правила данных](data/README.md) · [Лицензия](LICENSE)
