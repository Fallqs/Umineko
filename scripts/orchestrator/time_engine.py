"""
《海猫鸣泣之时：六轩岛黄昏》时间系统引擎

驱动一天内所有时间槽的推进，通过回调让Orchestrator执行具体内容。
"""

from typing import Optional, Protocol

from .config_loader import ConfigLoader
from .state import GameState


# 保留硬编码作为默认回退（当配置缺失时）
_DEFAULT_TIME_SLOTS = [
    "DAWN",
    "MORNING_1",
    "BREAKFAST",
    "NOON_1", "NOON_2",
    "LUNCH",
    "AFTERNOON_1", "AFTERNOON_2",
    "DINNER",
    "SLEEP_CHECK",
    "EVENING_1", "EVENING_2",
    "MIDNIGHT",
]

_DEFAULT_FREE_SLOTS = {
    "MORNING_1",
    "NOON_1", "NOON_2",
    "AFTERNOON_1", "AFTERNOON_2",
    "EVENING_1", "EVENING_2",
}

_DEFAULT_MEAL_SLOTS = {"BREAKFAST", "LUNCH", "DINNER"}

_DEFAULT_SPECIAL_SLOTS = {"DAWN", "SLEEP_CHECK", "MIDNIGHT"}


class TimeCallbacks(Protocol):
    async def on_dawn(self) -> None: ...
    async def on_free_slot(self, slot: str) -> None: ...
    async def on_meal_slot(self, slot: str) -> None: ...
    async def on_sleep_check(self) -> None: ...
    async def on_midnight(self) -> None: ...


class TimeEngine:
    def __init__(self, game_state: GameState, callbacks: TimeCallbacks, config: Optional[ConfigLoader] = None):
        self.state = game_state
        self.cb = callbacks
        self.config = config

    def _get_time_slots(self) -> list:
        if self.config:
            return self.config.get_time_slot_list()
        return _DEFAULT_TIME_SLOTS

    def _get_free_slots(self) -> set:
        if self.config:
            return set(self.config.get_free_slots())
        return _DEFAULT_FREE_SLOTS

    def _get_meal_slots(self) -> set:
        if self.config:
            return set(self.config.get_meal_slots())
        return _DEFAULT_MEAL_SLOTS

    def _get_special_slots(self) -> set:
        if self.config:
            return set(self.config.get_special_slots())
        return _DEFAULT_SPECIAL_SLOTS

    async def run_day(self) -> None:
        time_slots = self._get_time_slots()
        free_slots = self._get_free_slots()
        meal_slots = self._get_meal_slots()
        special_slots = self._get_special_slots()

        for slot in time_slots:
            self.state.phase = slot
            if slot in special_slots and slot == "DAWN":
                await self.cb.on_dawn()
            elif slot in free_slots:
                await self.cb.on_free_slot(slot)
            elif slot in meal_slots:
                await self.cb.on_meal_slot(slot)
            elif slot in special_slots and slot == "SLEEP_CHECK":
                await self.cb.on_sleep_check()
            elif slot in special_slots and slot == "MIDNIGHT":
                await self.cb.on_midnight()

    def is_free_slot(self, slot: str) -> bool:
        return slot in self._get_free_slots()

    def is_meal_slot(self, slot: str) -> bool:
        return slot in self._get_meal_slots()

    def is_special_slot(self, slot: str) -> bool:
        return slot in self._get_special_slots()
