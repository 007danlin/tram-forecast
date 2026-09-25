# Backend — Толя

FastAPI вызывает ML внутри своего процесса. Запускайте из корня репозитория.
Вызов проходит через `ml.adapter.predict_for_api_v1()`: несовместимая версия synthetic-провайдера отклоняется до inference с прежним HTTP 503. Ответ затем проверяется Pydantic; формат HTTP v1 сохранён. Этот адаптер ещё не загружает реальные артефакты.
Команды, конфигурация и контракт: [INTEGRATION.md](../INTEGRATION.md).
`requirements.in` фиксирует прямые зависимости; `requirements.txt` фиксирует весь установленный граф. При обновлении пересоздайте lock в чистом окружении и проверьте интеграцию.

## Подготовка v2 — BE-01

[Пакет согласования](contracts/README.md) содержит Pydantic-схемы,
[OpenAPI draft](contracts/generated/openapi-v2-draft.json) и
[синтетические примеры](contracts/generated/examples-v2-draft.json).
Это проект `2.0-draft.1`, не принятый командой. Runtime по-прежнему предоставляет
только v1; draft не регистрируется в приложении и не определяет формат ML/датасета.

```sh
.venv/bin/python -m backend.contracts.openapi --check
.venv/bin/python -m unittest discover -s backend/tests -v
```

После правки схем пересоздайте артефакты командой
`.venv/bin/python -m backend.contracts.openapi`, затем выполните обе проверки
и существующие интеграционные тесты. Новые библиотеки не добавлены.
