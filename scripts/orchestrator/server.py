"""
《海猫鸣泣之时：六轩岛黄昏》TCP服务器

启动/停止TCP Server，管理客户端连接，消息路由分发。
委托具体消息处理给MessageHandler。
"""

import asyncio
import json
from typing import Dict, Optional, Protocol

from .network import NetworkLayer, SeatConnection


class MessageHandler(Protocol):
    async def on_register(self, seat: SeatConnection, msg: dict) -> None: ...
    async def on_action(self, seat: SeatConnection, msg: dict) -> None: ...
    async def on_action_review(self, seat: SeatConnection, msg: dict) -> None: ...
    async def on_gm_output(self, seat: SeatConnection, msg: dict) -> None: ...
    async def on_orchestration_request(self, seat: SeatConnection, msg: dict) -> None: ...
    async def on_action_review_result(self, seat: SeatConnection, msg: dict) -> None: ...
    async def on_schrodinger_judgment_result(self, seat: SeatConnection, msg: dict) -> None: ...
    async def on_pre_parse(self, seat: SeatConnection, msg: dict) -> None: ...


class GameServer:
    def __init__(self, host: str, port: int, network: NetworkLayer, msg_handler: MessageHandler, access_token: Optional[str] = None):
        self.host = host
        self.port = port
        self.network = network
        self.msg_handler = msg_handler
        self.access_token = access_token
        self.server: Optional[asyncio.Server] = None
        self._shutdown_event = asyncio.Event()
        self._handler_tasks: set = set()

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port, reuse_address=True)
        addrs = ", ".join(str(sock.getsockname()) for sock in self.server.sockets)
        print(f"[GameServer] TCP server serving on {addrs}")

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            # 强制取消所有活跃 handler，避免 Windows 下 wait_closed() 无限挂起
            for task in list(self._handler_tasks):
                if not task.done():
                    task.cancel()
            try:
                await asyncio.wait_for(self.server.wait_closed(), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass
        for seat in list(self.network.seats.values()):
            try:
                seat.writer.close()
                # Windows 下 await wait_closed() 可能挂起，仅关闭不等待
            except Exception:
                pass

    async def serve(self) -> None:
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    def shutdown(self) -> None:
        self._shutdown_event.set()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        task = asyncio.current_task()
        if task:
            self._handler_tasks.add(task)
        addr = writer.get_extra_info("peername")
        print(f"[GameServer] Client connected from {addr}")
        seat: Optional[SeatConnection] = None
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                await writer.wait_closed()
                return
            try:
                msg = json.loads(line.decode("utf-8").strip())
            except json.JSONDecodeError:
                writer.close()
                await writer.wait_closed()
                return

            if msg.get("type") != "register":
                writer.close()
                await writer.wait_closed()
                return

            # access_token 验证
            if self.access_token is not None:
                token = msg.get("access_token", "")
                if token != self.access_token:
                    print(f"[GameServer] Invalid access_token from {msg.get('seat_id', '?')}, closing")
                    try:
                        data = json.dumps({"type": "register_denied", "reason": "invalid token"}) + "\n"
                        writer.write(data.encode("utf-8"))
                        await writer.drain()
                    except Exception:
                        pass
                    writer.close()
                    await writer.wait_closed()
                    return

            seat_id = msg.get("seat_id", "")
            role_name = msg.get("role_name", "")

            # 处理重连
            if seat_id in self.network.seats:
                old = self.network.seats[seat_id]
                old.alive = False
                try:
                    old.writer.close()
                    await old.writer.wait_closed()
                except Exception:
                    pass

            seat = SeatConnection(
                seat_id=seat_id,
                role_name=role_name,
                reader=reader,
                writer=writer,
                registered=True,
            )
            self.network.seats[seat_id] = seat
            print(f"[GameServer] Registered seat: {seat_id} ({role_name})")
            await self.network.send_and_drain(seat, {"type": "register_ok", "seat_id": seat_id})

            # 触发注册回调
            await self.msg_handler.on_register(seat, msg)

            # 启动读取循环
            reader_task = asyncio.create_task(self._seat_reader_loop(seat))
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[GameServer] Client handler error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if task:
                self._handler_tasks.discard(task)
            if seat:
                seat.alive = False
                self.network.seats.pop(seat.seat_id, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            print(f"[GameServer] Client disconnected: {addr}")

    async def _seat_reader_loop(self, seat: SeatConnection):
        try:
            while seat.alive and not seat.reader.at_eof():
                try:
                    # 延长超时以容纳 agent 处理 turn_token 所需的 LLM 推理时间
                    line = await asyncio.wait_for(seat.reader.readline(), timeout=300.0)
                except asyncio.TimeoutError:
                    break
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8").strip())
                except json.JSONDecodeError:
                    continue
                await self._dispatch_message(seat, msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[GameServer] Seat reader error for {seat.seat_id}: {e}")

    async def _dispatch_message(self, seat: SeatConnection, msg: dict):
        msg_type = msg.get("type")

        # 先检查是否是响应
        req_id = msg.get("id")
        if req_id and req_id in seat.pending:
            future = seat.pending.pop(req_id)
            if not future.done():
                future.set_result(msg)
            return
        parent_id = msg.get("parent_id")
        if parent_id and parent_id in seat.pending:
            future = seat.pending.pop(parent_id)
            if not future.done():
                future.set_result(msg)
            return

        if msg_type == "action":
            await self.msg_handler.on_action(seat, msg)
        elif msg_type == "action_review":
            await self.msg_handler.on_action_review(seat, msg)
        elif msg_type == "gm_output":
            await self.msg_handler.on_gm_output(seat, msg)
        elif msg_type == "orchestration_request":
            await self.msg_handler.on_orchestration_request(seat, msg)
        elif msg_type == "action_review_result":
            await self.msg_handler.on_action_review_result(seat, msg)
        elif msg_type == "schrodinger_judgment_result":
            await self.msg_handler.on_schrodinger_judgment_result(seat, msg)
        elif msg_type == "pre_parse":
            await self.msg_handler.on_pre_parse(seat, msg)
        else:
            print(f"[GameServer] Unknown message type from {seat.seat_id}: {msg_type}")
