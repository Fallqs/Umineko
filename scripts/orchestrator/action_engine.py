"""
《海猫鸣泣之时：六轩岛黄昏》行动引擎

行动解析、调查、发言广播、信息解锁。
"""

import re
from dataclasses import dataclass
from typing import Optional

from .config_loader import ConfigLoader
from .network import NetworkLayer, SeatConnection
from .state import GameState


@dataclass
class ParsedAction:
    investigate: bool = False
    speech: str = ""
    skip: bool = False
    next_move: Optional[str] = None
    duel_beatrice: bool = False


class ActionEngine:
    def __init__(self, game_state: GameState, config: ConfigLoader, network: NetworkLayer):
        self.state = game_state
        self.config = config
        self.network = network

    def parse(self, text: str) -> ParsedAction:
        result = ParsedAction()
        if not text:
            result.skip = True
            return result

        # 调查
        if any(k in text for k in ["调查", "搜索", "查看", "检查", "探索", "搜寻"]):
            result.investigate = True

        # 跳过
        if "跳过" in text or "不行动" in text or text.lower().strip() == "pass":
            result.skip = True

        # 决斗
        if "决斗" in text and "贝阿朵" in text:
            result.duel_beatrice = True

        # 移动意向
        m = re.search(r"下轮移动[：:]\s*(\S+)", text)
        if m:
            result.next_move = m.group(1).strip()

        # 发言（提取引号内容）
        speeches = re.findall(r'["""]([^"""]+)["""]', text)
        if speeches:
            result.speech = speeches[-1]
        elif not result.investigate and not result.skip and not result.duel_beatrice:
            # 无引号时，取最后一行作为发言
            lines = [l for l in text.split("\n") if l.strip()]
            if lines:
                result.speech = lines[-1][:200]

        return result

    async def execute_investigate(self, role: str, location: str, seat: SeatConnection) -> str:
        day = self.state.day
        infos = self.config.get_location_info(location, day)
        if not infos:
            return f"你仔细调查了{location}，但没有发现新的线索。"

        unlocked = self.state.unlocked_info.get(role, set())
        new_infos = [(iid, desc) for iid, desc in infos if iid not in unlocked]
        if not new_infos:
            return f"你再次调查了{location}，但没有新的发现。"

        iid, desc = new_infos[0]
        self.state.unlock_info(role, iid)
        points = self._get_info_points(iid)
        return f"【调查成功】你发现了新的线索！\n{iid}: {desc}\n（获得 {points} 分）"

    async def broadcast_speech(self, speaker_role: str, speech: str, location: str) -> None:
        if not speech:
            return
        body = f"【{speaker_role}】{speech}"
        for role, seat_id in self.state.role_controller.items():
            if self.state.locations.get(role) == location:
                seat = self.network.seats.get(seat_id)
                if seat and seat.alive:
                    await self.network.send_and_drain(seat, {
                        "type": "notification",
                        "title": "同场发言",
                        "body": body,
                        "location": location,
                    })

    def handle_move_intent(self, role: str, target: str) -> None:
        if target in self.config.locations:
            self.state.pending_moves[role] = target

    @staticmethod
    def _get_info_points(info_id: str) -> int:
        for prefix, pts in {"P-": 1, "S-": 2, "C-": 4}.items():
            if info_id.startswith(prefix):
                return pts
        return 0
