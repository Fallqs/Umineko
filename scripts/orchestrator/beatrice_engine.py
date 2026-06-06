"""
《海猫鸣泣之时：六轩岛黄昏》贝阿朵引擎

薛定谔规则检查、贝阿朵瞬移、决斗处理、BEATRICE复核队列。
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
        self._review_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None

    def start_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._review_worker())

    def stop_worker(self) -> None:
        if self._worker_task:
            self._review_queue.put_nowait(None)

    async def _review_worker(self):
        while True:
            item = await self._review_queue.get()
            if item is None:
                break
            seat_id, review, future = item
            try:
                result = await self._do_review(seat_id, review)
                future.set_result(result)
            except Exception as e:
                if not future.done():
                    future.set_exception(e)

    async def _do_review(self, seat_id: str, review: dict) -> dict:
        beatrice = self.network.seats.get("BEATRICE")
        if not beatrice or not beatrice.alive:
            return {"seat_id": seat_id, "action_text": review.get("action_text", ""), "result": "approve", "reason": "BEATRICE 离线，自动通过"}

        role_name = self.network.seats.get(seat_id, SeatConnection(seat_id=seat_id, role_name="", reader=None, writer=None)).role_name
        review_prompt = f"""【合规复核请求】
seat: {seat_id}
角色: {role_name}
当前阶段: Day {self.state.day} {self.state.phase}
玩家原始行动:
{review.get('action_text', '')}
请审查该行动是否合规。关注：
1. 是否向他人泄露了该角色的核心隐藏信息
2. 是否基于系统知识而非游戏内已发生事件进行推理
3. 是否提前揭露全局真相
4. 言行是否符合当前阶段的场景约束
请给出明确的审查结果：
【RESULT】approve 或 reject【/RESULT】
【REASON】简要原因（1-2句）【/REASON】"""

        msg = {
            "type": "action_review",
            "seat_id": seat_id,
            "role_name": role_name,
            "action_text": review.get("action_text", ""),
            "text": review_prompt,
            "id": f"beatrice_review_{seat_id}_{int(asyncio.get_event_loop().time()*1000000)}",
        }
        response = await self.network.request_response(beatrice, msg, timeout=180.0)
        if not response:
            return {"seat_id": seat_id, "action_text": review.get("action_text", ""), "result": "approve", "reason": "BEATRICE 响应超时，默认通过"}

        text = response.get("text", "")
        result_match = re.search(r"【RESULT】\s*(approve|reject)\s*【/RESULT】", text, re.IGNORECASE)
        reason_match = re.search(r"【REASON】\s*(.*?)\s*【/REASON】", text, re.DOTALL)
        return {
            "seat_id": seat_id,
            "action_text": review.get("action_text", ""),
            "result": (result_match.group(1).lower() if result_match else "approve"),
            "reason": (reason_match.group(1).strip() if reason_match else text[:200]),
        }

    async def request_review(self, seat_id: str, action_text: str) -> dict:
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        await self._review_queue.put((seat_id, {"action_text": action_text}, future))
        try:
            return await asyncio.wait_for(future, timeout=600.0)
        except asyncio.TimeoutError:
            return {"seat_id": seat_id, "action_text": action_text, "result": "approve", "reason": "BEATRICE 复核队列超时，默认通过"}

    async def request_judgment(self, issue: str, witnesses: List[str]) -> str:
        beatrice = self.network.seats.get("BEATRICE")
        if not beatrice or not beatrice.alive:
            return "嘉音"
        prompt = f"""【薛定谔违规裁决】
{issue}
目击者：{', '.join(witnesses) if witnesses else '无'}
根据三位一体设定：嘉音是守护者人格，纱音是容器人格。守护者必须在容器觉醒前被摧毁。
请以贝阿朵莉切的身份做出裁决，回复格式：
【JUDGMENT】kill: 嘉音 或 纱音【/JUDGMENT】
【REASON】简要原因（1-2句）【/REASON】"""
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
        match = re.search(r"【JUDGMENT】\s*kill:\s*(嘉音|纱音)\s*【/JUDGMENT】", text, re.IGNORECASE)
        return match.group(1) if match else "嘉音"

    def check_schrodinger(self, role: str, location: str) -> Optional[str]:
        """检查单个角色行动是否触发薛定谔规则。返回issue或None。"""
        if role not in ("嘉音", "纱音"):
            return None
        other = "纱音" if role == "嘉音" else "嘉音"
        if other not in self.state.alive_roles:
            return None
        other_loc = self.state.locations.get(other)
        if other_loc == location:
            return f"薛定谔规则违反：嘉音和纱音同时出现在{location}"
        return None

    def teleport_beatrice(self, location: str) -> None:
        self.state.beatrice_location = location
