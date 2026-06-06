"""
《海猫鸣泣之时：六轩岛黄昏》令牌环引擎

实现"同一地点内串行行动"的核心机制。
"""

import asyncio
import random
from typing import List, Optional, Protocol

from .network import NetworkLayer, SeatConnection
from .state import GameState


class TokenCallbacks(Protocol):
    async def on_action_received(self, role: str, action_msg: dict, location: str, slot: str) -> None: ...


class TokenRingEngine:
    def __init__(self, game_state: GameState, network: NetworkLayer, callbacks: TokenCallbacks):
        self.state = game_state
        self.network = network
        self.cb = callbacks
        self._action_buffer: List[dict] = []
        self._action_event = asyncio.Event()

    async def run(self, location: str, players: List[str], slot: str, rounds: int = 2) -> None:
        if not players:
            return
        players = list(players)
        random.shuffle(players)
        print(f"[TokenRing] 📍 {location} 令牌环开始，玩家: {players}，轮数: {rounds}")

        for round_num in range(1, rounds + 1):
            for role in players:
                if role in self.state.sleeping:
                    continue
                seat_id = self.state.role_controller.get(role)
                if not seat_id:
                    continue
                seat = self.network.seats.get(seat_id)
                if not seat or not seat.alive:
                    continue

                nearby = [r for r in players if r != role]
                ap = self.state.action_points.get(role, 0)
                cost_multiplier = 2 if role in self.state.night_owl else 1

                context = self._build_context(role, location, slot, round_num, rounds, nearby, ap, cost_multiplier)
                msg_id = f"turn_d{self.state.day}_{slot}_{seat_id}_r{round_num}"
                msg = {
                    "type": "turn_token",
                    "seat_id": seat_id,
                    "role_name": role,
                    "time_slot": slot,
                    "day": self.state.day,
                    "location": location,
                    "action_points": ap,
                    "token_round": round_num,
                    "token_total_rounds": rounds,
                    "nearby_players": nearby,
                    "context": context,
                    "id": msg_id,
                }
                if role in ("嘉音", "纱音"):
                    msg["can_duel_beatrice"] = True

                print(f"[TokenRing] 🎫 turn_token -> {seat_id}({role}) at {location} round {round_num}/{rounds}")
                await self.network.send_and_drain(seat, msg)

                action_msg = await self._wait_for_action(seat, msg_id, timeout=180.0)
                if action_msg:
                    await self.cb.on_action_received(role, action_msg, location, slot)
                else:
                    print(f"[TokenRing] ⏱️ {seat_id}({role}) 未响应，跳过")

        print(f"[TokenRing] 📍 {location} 令牌环结束")

    def _build_context(self, role, location, slot, round_num, total_rounds, nearby, ap, cost_multiplier) -> str:
        parts = [
            f"【第{self.state.day}天 - {slot}】",
            f"你在{location}。",
            f"同场的有：{', '.join(nearby)}。" if nearby else "这里只有你一个人。",
            f"当前是第 {round_num}/{total_rounds} 轮行动。",
            f"你剩余 {ap} 行动点。",
        ]
        if cost_multiplier > 1:
            parts.append("【熬夜惩罚】你的所有行动消耗变为2倍！")
        parts.extend([
            "",
            "你可以选择：",
            "1. 调查当前地点（消耗2点）",
            "2. 发言（不消耗点数，同地点所有人能听到）",
            "3. 跳过回合",
            '如果你希望下个时间点移动到其他地点，请在描述末尾声明："下轮移动：{地点名}"',
        ])
        if role in ("嘉音", "纱音"):
            parts.append("4. 【特殊】向贝阿朵发起决斗（你将死亡，另一位存活）")
        parts.extend(["", "请用自然语言描述你的行动和发言。"])
        return "\n".join(parts)

    async def _wait_for_action(self, seat: SeatConnection, parent_id: str, timeout: float = 180.0) -> Optional[dict]:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self._action_event.wait(), timeout=min(remaining, 1.0))
                self._action_event.clear()
                for action in list(self._action_buffer):
                    if action.get("parent_id") == parent_id or action.get("seat_id") == seat.seat_id:
                        self._action_buffer.remove(action)
                        return action
            except asyncio.TimeoutError:
                continue
        return None

    def push_action(self, action_msg: dict) -> None:
        """由Server层调用，将收到的action消息加入缓冲区。"""
        self._action_buffer.append(action_msg)
        self._action_event.set()
