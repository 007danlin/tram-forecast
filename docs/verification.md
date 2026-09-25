# Проверки заготовки · 2026-09-19

Среда: macOS arm64, Python 3.14.7, Node.js 22.22.2, npm 10.9.7.

| Проверка | Результат |
|---|---|
| `python -m unittest discover -s tests/integration -v` | 7 тестов прошли: HTTP health, вызов ML с подменённым результатом, сверка с JSON в INTEGRATION.md, детерминированность, ошибка ML, некорректное время без смещения, OpenAPI |
| `npm run build --prefix frontend` | TypeScript и production-сборка прошли |
| Браузер → Vite-прокси → FastAPI → ML | Отображаются подключение, шесть точек, таблица, подпись тестовых данных |
| Backend остановлен, нажат повтор запроса | График удаляется, появляется понятное сообщение об ошибке |
| Повтор после запуска backend | Данные и график восстанавливаются |
| `npm audit` после обновления Vite до 6.4.3 | 0 известных уязвимостей на момент проверки |
| `python -m pip check` | Конфликтов зависимостей нет |
| `docker compose config --quiet` | Конфигурация валидна |
| `git diff --check` | Ошибок пробелов нет |

**Локальное ограничение:** Docker CLI есть, но daemon не запущен (сокет отсутствует).

**Проверено в GitHub Actions:** [CI #1](https://github.com/MISISion-Possible/tram-forecast/actions/runs/35459889637), commit `82747a5`, успешно завершён за 42 секунды. Прошли тесты backend/ML на Python 3.12, проверка типов и сборка frontend, сборка и запуск Linux-контейнеров Compose с HTTP-проверкой страницы и прогноза через прокси. Workflow запускается при push и в PR.
На Python 3.14 uvicorn 0.34.2 выводит предупреждение об устаревающей функции asyncio; запуск и тесты проходят.
Фиксация зависимостей: `frontend/package-lock.json` и `backend/requirements.txt`.
Синтетическая проверка не является проверкой качества прогнозирования.
