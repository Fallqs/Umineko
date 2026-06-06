"""
《海猫鸣泣之时：六轩岛黄昏》时间系统引擎

驱动一天内所有时间槽的推进，通过回调让Orchestrator执行具体内容。
"""

from typing import Protocol

from .state import GameState


TIME_SLOTS = [
    "DAWN",
    "MORNING_1", "MORNING_2", "MORNING_3",
    "BREAKFAST",
    "NOON_1", "NOON_2", "NOON_3",
    "LUNCH",
    "AFTERNOON_1", "AFTERNOON_2", "AFTERNOON_3",
    "DINNER",
    "SLEEP_CHECK",
    "EVENING_1", "EVENING_2", "EVENING_3",
    "MIDNIGHT",
]

FREE_SLOTS = {
    "MORNING_1", "MORNING_2", "MORNING_3",
    "NOON_1", "NOON_2", "NOON_3",
    "AFTERNOON_1", "AFTERNOON_2", "AFTERNOON_3",
    "EVENING_1", "EVENING_2", "EVENING_3",
}

KEY_MEALS = {"BREAKFAST", "LUNCH", "DINNER"}

SPECIAL_SLOTS = {"DAWN", "SLEEP_CHECK", "MIDNIGHT"}


class TimeCallbacks(Protocol):
    async def on_dawn(self) -> None: ...
    async def on_free_slot(self, slot: str) -> None: ...
    async def on_meal_slot(self, slot: str) -> None: ...
    async def on_sleep_check(self) -> None: ...
    async def on_midnight(self) -> None: ...


class TimeEngine:
    def __init__(self, game_state: GameState, callbacks: TimeCallbacks):
        self.state = game_state
        self.cb = callbacks

    async def run_day(self) -> None:
        for slot in TIME_SLOTS:
            self.state.phase = slot
            if slot == "DAWN":
                await self.cb.on_dawn()
            elif slot in FREE_SLOTS:
                await self.cb.on_free_slot(slot)
            elif slot in KEY_MEALS:
                await self.cb.on_meal_slot(slot)
            elif slot == "SLEEP_CHECK":
                await self.cb.on_sleep_check()
            elif slot == "MIDNIGHT":
                await self.cb.on_midnight()

    def is_free_slot(self, slot: str) -> bool:
        return slot in FREE_SLOTS

    def is_meal_slot(self, slot: str) -> bool:
        return slot in KEY_MEALS

    def is_special_slot(self, slot: str) -> bool:
        return slot in SPECIAL_SLOTS
