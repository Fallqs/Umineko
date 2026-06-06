"""
《海猫鸣泣之时：六轩岛黄昏》令牌环引擎

实现"同一地点内串行行动"的核心机制。
"""

import asyncio
import random
from typing import List, Optional, Protocol

from .config_loader import ConfigLoader
from .network import NetworkLayer, SeatConnection
from .state import GameState


class TokenCallbacks(Protocol):
    async def on_action_received(self, role: str, action_msg: dict, location: str, slot: str) -> None: ...


class TokenRingEngine:
    def __init__(self, game_state: GameState, network: NetworkLayer, callbacks: TokenCallbacks, config: Optional[ConfigLoader] = None):
        self.state = game_state
        self.network = network
        self.cb = callbacks
        self.config = config
        self._action_buffer: List[dict] = []
        self._action_event = asyncio.Event()

    def _get_rule(self, key: str, default=None):
        if self.config:
            return self.config.get_token_ring_rule(key, default)
        return default

    async def run(self, location: str, players: List[str], slot: str, rounds: Optional[int] = None) -> None:
        if not players:
            return
        players = list(players)
        random.shuffle(players)
        # 从配置读取默认值
        if rounds is None:
            if slot in {"BREAKFAST", "LUNCH", "DINNER"}:
                rounds = self._get_rule("meal_slot_rounds", 5)
            else:
                rounds = self._get_rule("free_slot_rounds", 10)
        max_inv = self._get_rule("investigations_per_slot", 2)
        wait_timeout = self._get_rule("wait_timeout", 30.0)
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
                investigations_remaining = max(0, max_inv - self.state.get_investigations_used(role))

                context = self._build_context(role, location, slot, round_num, rounds, nearby, ap, cost_multiplier, investigations_remaining)
                msg_id = f"turn_d{self.state.day}_{slot}_{seat_id}_r{round_num}"
                # 携带背包信息（供 agent_wrapper 直接展示）
                inventory_ids = self.state.get_inventory(role)
                inventory_names = [self.state.item_registry.get(iid, {}).get("name", iid) for iid in inventory_ids]
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
                    "investigations_remaining": investigations_remaining,
                    "nearby_players": nearby,
                    "context": context,
                    "inventory": inventory_names,
                    "id": msg_id,
                }
                if role in ("嘉音", "纱音"):
                    msg["can_duel_beatrice"] = True

                print(f"[TokenRing] 🎫 turn_token -> {seat_id}({role}) at {location} round {round_num}/{rounds} (inv_remaining={investigations_remaining})")
                await self.network.send_and_drain(seat, msg)

                action_msg = await self._wait_for_action(seat, msg_id, timeout=wait_timeout)
                if action_msg:
                    await self.cb.on_action_received(role, action_msg, location, slot)
                else:
                    print(f"[TokenRing] ⏱️ {seat_id}({role}) 未响应，跳过")

        print(f"[TokenRing] 📍 {location} 令牌环结束")
        # 推进按回合数计算的 buff 持续时间
        self.state.tick_buff_durations("token_ring_end")

    def _build_context(self, role, location, slot, round_num, total_rounds, nearby, ap, cost_multiplier, investigations_remaining: int = 2) -> str:
        parts = [
            f"【第{self.state.day}天 - {slot}】",
            f"你在{location}。",
            f"同场的有：{', '.join(nearby)}。" if nearby else "这里只有你一个人。",
            f"当前是第 {round_num}/{total_rounds} 轮对话/行动。",
            f"你剩余 {ap} 行动点。",
            f"本时间槽还可进行调查：{investigations_remaining}/2 次。",
        ]
        if cost_multiplier > 1:
            parts.append("【熬夜惩罚】你的所有行动消耗变为2倍！")

        # 背包信息
        inventory = self.state.get_inventory(role)
        if inventory:
            item_names = [self.state.item_registry.get(iid, {}).get("name", iid) for iid in inventory]
            parts.append(f"你携带的物品：{', '.join(item_names)}")
        else:
            parts.append("你的背包是空的。")

        # 动态构建可用行动列表
        parts.append("")
        parts.append("你可以选择：")
        action_lines = self.state.build_available_actions(role, investigations_remaining, nearby)
        parts.extend(action_lines)

        # 通用行动（从 game_rules.json 读取，所有角色可用）
        if self.config:
            for action_def in self.config.game_rules.get("universal_actions", []):
                action_name = action_def.get("name", action_def.get("id", ""))
                base_cost = action_def.get("ap_cost", 0)
                actual_cost = self.state.get_action_point_cost(role, base_cost)
                target_type = action_def.get("target_type", "none")
                target_desc = ""
                if target_type == "role":
                    target_desc = f"（目标：{'/'.join(nearby) if nearby else '无'}）"
                parts.append(f"【通用】{action_name}（消耗{actual_cost}点）{target_desc}")

        # 角色专属行动（从 game_rules.json 读取）
        if self.config:
            role_actions = self.config.game_rules.get("role_granted_actions", {}).get(role, [])
            for action_def in role_actions:
                action_name = action_def.get("name", action_def.get("id", ""))
                base_cost = action_def.get("ap_cost", 0)
                actual_cost = self.state.get_action_point_cost(role, base_cost)
                parts.append(f"【专属】{action_name}（消耗{actual_cost}点）")

        parts.append("")
        parts.append("请用自然语言描述你的行动和发言。")
        parts.append('如果你希望下个时间点移动到其他地点，请在描述末尾声明："下轮移动：{地点名}"')
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
