"""
《海猫鸣泣之时：六轩岛黄昏》贝阿朵引擎

薛定谔规则检查、贝阿朵瞬移、决斗裁决。
（已移除中心化 BEATRICE 审查，审查功能由每个 agent 的 GM Session 分布式处理）
"""

import asyncio
import re
from typing import List, Optional

from .network import NetworkLayer, SeatConnection
from .state import GameState


class BeatriceEngine:
    def __init__(self, game_state: GameState, network: NetworkLayer):
        self.state = game_state
        self.network = network

    def start_worker(self) -> None:
        """保留接口兼容，不再启动中心化审查 worker。"""
        pass

    def stop_worker(self) -> None:
        """保留接口兼容。"""
        pass

    async def request_judgment(self, issue: str, witnesses: List[str]) -> str:
        beatrice = self.network.seats.get("BEATRICE")
        if not beatrice or not beatrice.alive:
            return "嘉音"
        prompt = f"""【薛定谔违规裁决】
{issue}
目击者：{', '.join(witnesses) if witnesses else '无'}
根据三位一体设定：嘉音是守护者人格，纱音是容器人格。守护者必须在容器觉醒前被摧毁。
请以贝阿朵莉切的身份做出裁决，回复格式：
<judgment>kill: 嘉音 或 纱音</judgment>
<reason>简要原因（1-2句）</reason>"""
        msg = {
            "type": "schrodinger_judgment",
            "seat_id": "BEATRICE",
            "text": prompt,
            "id": f"schrodinger_judge_{self.state.day}_{self.state.phase}",
        }
        try:
            result = await asyncio.wait_for(self.network.request_response(beatrice, msg, timeout=300.0), timeout=300.0)
        except asyncio.TimeoutError:
            return "嘉音"
        if not isinstance(result, dict):
            return "嘉音"
        text = result.get("text", "")
        match = re.search(r"<judgment>\s*kill:\s*(嘉音|纱音)\s*</judgment>", text, re.IGNORECASE)
        return match.group(1) if match else "嘉音"

    def check_schrodinger(self, role: str, location: str) -> Optional[str]:
        """检查是否需要强制隐藏 revealed 角色。返回强制隐藏提示文本或 None。"""
        if role not in ("嘉音", "纱音"):
            return None
        if role not in self.state.schrodinger_revealed:
            return None
        # 检查该地点是否有非贝阿朵莉切的第三人
        third_parties = [
            r for r in self.state.alive_roles
            if r != role and r != self.state.get_schrodinger_other(role)
            and self.state.locations.get(r) == location
            and r != "贝阿朵莉切"
        ]
        if third_parties:
            self.state.force_conceal(role)
            return "一股宿命的力量将你剥离现实，众人的声音仿佛离你远去，你的身躯无法触碰真实。"
        return None

    def teleport_beatrice(self, location: str) -> None:
        self.state.beatrice_location = location
