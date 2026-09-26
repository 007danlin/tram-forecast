# Компактный прогноз — вариант A

Выбран пользователем по [экрану Figma](https://www.figma.com/design/SOmpsUHB2S9LMDzoEpKZl2?node-id=2-211).

## Поведение

- Выбор маршрута, даты, горизонта и слоя находится слева от схемы.
- Главное число — выбранный час/день. Сумма периода вынесена к экспорту.
- График, таблица, ползунок, воспроизведение и первый максимум используют один индекс.
- Соседние значения переключают тот же индекс. Смена времени не запрашивает API.
- В сценарии рядом с выбранным значением видны база и разница, на графике — две линии.
- Ручные поправки и проверка выпуска раскрываются по нажатию. На основном экране нет
  общего совета «перераспределить вагоны». Для такого решения нет фактических данных.
- Описание единиц, ограничения, год схемы и паспорт доступны в «О данных».
- На телефоне прогноз и управление доступны сразу, карта расположена ниже.
- CSV содержит выбранные маршрут/период/слой; пропуски не подменяются нулями.

## Проверки

Сборка: `npm ci --prefix frontend && npm run build --prefix frontend`.
Backend: `python -m unittest discover -s backend/tests -v`.
Контракт: `python -m backend.contracts.openapi --check`.
Синтетическая сквозная регрессия с изолированными серверами:

```sh
NODE_PATH="$PWD/frontend/node_modules" QA_BROWSER=chromium python tests/frontend/run_browser.py
```

Она включает API/CSV, stale requests/export, 503/410/409, partial/no_data, клавиатуру,
пик, соседние интервалы, темы, мобильный экран и сохранение экземпляра карты.
`tests/frontend/dispatcher.cjs` дополнительно проверяет сценарии, качественный год
и обзор на заранее установленном реальном пакете B2:

```sh
NODE_PATH="$PWD/frontend/node_modules" node tests/frontend/dispatcher.cjs http://127.0.0.1:5198 artifacts/verification/variant-a-b2
NODE_PATH="$PWD/frontend/node_modules" QA_ENGINE=webkit node tests/frontend/dispatcher.cjs http://127.0.0.1:5198 artifacts/verification/variant-a-webkit
NODE_PATH="$PWD/frontend/node_modules" node tests/frontend/compact-card.cjs http://127.0.0.1:5198 artifacts/verification/variant-a-final
```

26.09.2026: сборка, 43 backend-теста, 9 интеграционных проверок и браузерные
проверки прошли на macOS. После переноса на `main` (fb39e23) сохранены новые
проверки metadata и типизированный OpenAPI; capabilities дополнен схемами сценария/года.
числа UI сравнивались с API, скачанные CSV — с тем же ответом. Тесты B2 используют
ноябрь–декабрь 2025; сам release в Git не добавляется. Скриншоты и CSV остаются
в игнорируемом `artifacts/verification/`. Это проверка интеграции, не качества ML.

## Зависимости

Manual scenario — отдельные `/api/v2/scenarios/query` и `/api/v2/scenarios/export`.
Формула `base × weather × event`, каждый коэффициент от 0,5 до 1,5, шаг 0,05.
Сценарный ID зависит от базового result_id и коэффициентов; экспорт отклоняет
устаревший ID с 409. Границы сценарного интервала равны null. Capabilities
объявляет описание года `qualitative-year-v1`; численный год не поддержан.

Модель, карта, обучение, инфраструктура и конкурсная отправка в этот UI PR не входят.
