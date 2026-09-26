"""Versioned qualitative presentation of ml.cli.command_year_scenario."""
from typing import Literal
from backend.contracts.v2 import ContractModel


class ScenarioCapabilities(ContractModel):
    schema_version: Literal["manual-scenario-v1"]
    min: float
    max: float
    step: float
    source: Literal["dispatcher_assumption"]
    query: str
    export: str


class YearScenario(ContractModel):
    name: Literal["recent_level", "lower_service", "higher_demand"]
    title: str
    assumption: str
    change: str
    needed: str


class YearCapabilities(ContractModel):
    version: Literal["qualitative-year-v1"]
    source: Literal["ml.cli.command_year_scenario"]
    qualitative_available: Literal[True]
    numeric_supported: Literal[False]
    value: None
    history_end: str
    history_months: int
    reason: str
    scenarios: list[YearScenario]


SCENARIO = {"schema_version": "manual-scenario-v1", "min": 0.5, "max": 1.5, "step": 0.05,
            "source": "dispatcher_assumption", "query": "/api/v2/scenarios/query",
            "export": "/api/v2/scenarios/export"}
YEAR = {
    "version": "qualitative-year-v1", "source": "ml.cli.command_year_scenario",
    "qualitative_available": True, "numeric_supported": False, "value": None,
    "history_end": "2025-10-31", "history_months": 10,
    "reason": "Доступны только 10 месяцев истории. Годовая сезонность и годовой интервал неопределённости не проверены.",
    "scenarios": [
        {"name": "recent_level", "title": "Сохранение недавнего уровня",
         "assumption": "Спрос остаётся около последнего проверенного профиля маршрута по часам.",
         "change": "Профиль может измениться при смене расписания или состава пассажиров.",
         "needed": "Нужны новые фактические посадки, расписание и полный сезонный цикл."},
        {"name": "lower_service", "title": "Сокращение предложения",
         "assumption": "Если выпуск сократится, число посадок в затронутые периоды может снизиться. Масштаб не задан.",
         "change": "Спрос может перейти на соседние часы или маршруты; заполненность из посадок не следует.",
         "needed": "Нужны подтверждённые изменения выпуска, интервалы, вместимость и фактические посадки."},
        {"name": "higher_demand", "title": "Рост спроса",
         "assumption": "Спрос может превысить недавний профиль; численный рост не утверждается.",
         "change": "Может потребоваться проверка выпуска и интервалов в периоды роста.",
         "needed": "Нужны подтверждённые факторы роста и наблюдения для проверки их эффекта."},
    ],
}
