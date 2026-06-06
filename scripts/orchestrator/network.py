"""
《海猫鸣泣之时：六轩岛黄昏》网络通信层

封装 TCP 通信的最小操作集，不感知游戏逻辑。
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SeatConnection:
    seat_id: str
    role_name: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    alive: bool = True
    registered: bool = False
    pending: Dict[str, asyncio.Future] = field(default_factory=dict)
    review_future: Optional[asyncio.Future] = None

    def __post_init__(self):
        if self.pending is None:
            self.pending = {}


class NetworkLayer:
    """TCP 通信基元，纯 IO 层。"""

    def __init__(self):
        self.seats: Dict[str, SeatConnection] = {}

    def send(self, seat: SeatConnection, msg: dict):
        if seat.writer.is_closing():
            return
        data = json.dumps(msg, ensure_ascii=False) + "\n"
        seat.writer.write(data.encode("utf-8"))

    async def drain(self, seat: SeatConnection):
        if not seat.writer.is_closing():
            await seat.writer.drain()

    async def send_and_drain(self, seat: SeatConnection, msg: dict):
        self.send(seat, msg)
        await self.drain(seat)

    async def request_response(
        self,
        seat: SeatConnection,
        msg: dict,
        timeout: float = 300.0,
    ) -> Optional[dict]:
        request_id = msg.get("id") or f"req_{int(asyncio.get_event_loop().time()*1000)}_{id(msg)}"
        msg["id"] = request_id
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        seat.pending[request_id] = future
        await self.send_and_drain(seat, msg)
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            print(f"[NetworkLayer] Request {request_id} to {seat.seat_id} timed out")
            return None
        finally:
            seat.pending.pop(request_id, None)
