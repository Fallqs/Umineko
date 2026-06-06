#!/usr/bin/env python3
"""
Agent Wrapper for 海猫剧本杀 - v3 (TCP Client 模式)

统一架构：
- 每个席位一个 agent 进程，作为 TCP client 连接到 orchestrator
- 进程内维护一个 GM Session（必需）和一个可选的 User Session（auto 模式）
- 支持四种模式：auto / human / beatrice / npc
- beatrice 模式：贝阿朵莉切作为普通角色参与，拥有红字/金字特权
- 核心优化：休眠-激活机制（未收到 turn_token 时零 API 调用）

通信协议：
- agent 启动后向 orchestrator 发送 {"type": "register", "seat_id": "P1", "role_name": "..."}
- 所有消息以 \n 分隔的 JSON line 传输
"""

import argparse
import asyncio
import json
import re
import shutil
import sys
import tempfile
import traceback
from collections import deque
from pathlib import Path
from typing import List, Optional

from kaos.path import KaosPath
from kimi_cli.app import KimiCLI, enable_logging
from kimi_cli.config import Config, load_config
from kimi_cli.session import Session
from kimi_cli.wire.types import TextPart, ThinkPart, ToolCall, ToolCallPart


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _prepare_md_work_dir(
    role_dir: Path,
    md_name: str,
    append_name: Optional[str] = None,
    prepend_shared: Optional[str] = None,
    append_shared: Optional[List[str]] = None,
    shared_docs_dir: Optional[Path] = None,
) -> Path:
    """创建临时目录，将指定的 .md 文件作为 AGENTS.md 加载。"""
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"umi_{md_name}_{role_dir.name}_"))
    for src in role_dir.iterdir():
        dst = tmp_dir / src.name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    shared_dir = shared_docs_dir or (role_dir.parent.parent / "shared" / "docs")
    src_md = tmp_dir / f"{md_name}.md"
    agents_md = tmp_dir / "AGENTS.md"

    parts: list[str] = []

    if prepend_shared:
        prepend_path = shared_dir / prepend_shared
        if prepend_path.exists():
            with open(prepend_path, "r", encoding="utf-8") as f:
                parts.append(f.read())

    if src_md.exists():
        with open(src_md, "r", encoding="utf-8") as f:
            parts.append(f.read())
    else:
        print(f"[Agent] Warning: {md_name}.md not found in {role_dir}")

    if append_name:
        append_md = tmp_dir / f"{append_name}.md"
        if append_md.exists():
            with open(append_md, "r", encoding="utf-8") as f:
                parts.append(f.read())

    for shared_name in append_shared or []:
        append_path = shared_dir / shared_name
        if append_path.exists():
            with open(append_path, "r", encoding="utf-8") as f:
                parts.append(f.read())

    if parts:
        with open(agents_md, "w", encoding="utf-8") as out:
            out.write("\n\n".join(parts))

    (tmp_dir / ".git").mkdir(exist_ok=True)
    return tmp_dir


def _extract_orchestration_requests(text: str) -> list[dict]:
    """从 GM 输出中提取 【ORCHESTRATION_REQUEST】块，并去重。"""
    pattern = r"【ORCHESTRATION_REQUEST】\s*(.*?)\s*【/ORCHESTRATION_REQUEST】"
    matches = re.findall(pattern, text, re.DOTALL)
    requests = []
    seen = set()
    for raw in matches:
        action_match = re.search(r"action\s*[:：]\s*(\S+)", raw)
        params_match = re.search(r"params\s*[:：]\s*(\{.*?\})", raw, re.DOTALL)
        if action_match:
            req = {"action": action_match.group(1).strip()}
            if params_match:
                try:
                    req["params"] = json.loads(params_match.group(1).strip())
                except json.JSONDecodeError:
                    req["params_raw"] = params_match.group(1).strip()
            else:
                req["params"] = {}
            key = (req["action"], json.dumps(req.get("params", {}), sort_keys=True, ensure_ascii=False))
            if key not in seen:
                seen.add(key)
                requests.append(req)
    return requests


def _extract_player_input(text: str) -> Optional[str]:
    """提取 【PLAYER_INPUT】块内容（人类模式）。"""
    pattern = r"【PLAYER_INPUT】\s*(.*?)\s*【/PLAYER_INPUT】"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else None


def _strip_blocks(text: str) -> str:
    """移除 orchestration/player_input 块，返回干净文本。"""
    text = re.sub(r"【ORCHESTRATION_REQUEST】\s*.*?\s*【/ORCHESTRATION_REQUEST】", "", text, flags=re.DOTALL)
    text = re.sub(r"【PLAYER_INPUT】\s*.*?\s*【/PLAYER_INPUT】", "", text, flags=re.DOTALL)
    return text.strip()


# ---------------------------------------------------------------------------
# Session 包装
# ---------------------------------------------------------------------------

class SessionWrapper:
    def __init__(self, name: str, work_dir: Path, session_id: str):
        self.name = name
        self.work_dir = work_dir
        self.session_id = session_id
        self.instance: Optional[KimiCLI] = None

    async def init(self, config: Optional[Config], model_name: Optional[str], thinking: bool, yolo: bool):
        kaos_dir = KaosPath.unsafe_from_local_path(self.work_dir)
        session = await Session.find(kaos_dir, self.session_id)
        if session is None:
            session = await Session.create(kaos_dir, self.session_id)
        self.instance = await KimiCLI.create(
            session, config=config, model_name=model_name, thinking=thinking, yolo=yolo,
        )
        print(f"[Agent] [{self.name}] Session ready: {session.id}")

    async def run_once(self, text: str) -> tuple[str, list[str], list[dict]]:
        """运行一次对话，返回 (输出文本, 思考文本, orchestration请求列表)"""
        cancel_event = asyncio.Event()
        output_parts: list[str] = []
        thinking_parts: list[str] = []

        async for wire_msg in self.instance.run(text, cancel_event):
            if isinstance(wire_msg, TextPart):
                output_parts.append(wire_msg.text)
            elif isinstance(wire_msg, ThinkPart):
                thinking_parts.append(wire_msg.text)
            elif isinstance(wire_msg, (ToolCall, ToolCallPart)):
                pass

        full_text = "".join(output_parts)
        orch_reqs = _extract_orchestration_requests(full_text)
        return full_text, thinking_parts, orch_reqs


# ---------------------------------------------------------------------------
# Agent 包装
# ---------------------------------------------------------------------------

class SeatAgent:
    def __init__(
        self,
        role_dir: Path,
        seat_id: str,
        orchestrator_host: str,
        orchestrator_port: int,
        mode: str = "auto",
        yolo: bool = True,
        thinking: bool = False,
        model_name: Optional[str] = None,
    ):
        self.role_dir = role_dir
        self.seat_id = seat_id
        self.orchestrator_host = orchestrator_host
        self.orchestrator_port = orchestrator_port
        self.mode = mode
        self.yolo = yolo
        self.thinking = thinking
        self.model_name = model_name

        # 队列
        self.gm_input_queue: asyncio.Queue[dict] = asyncio.Queue()
        self.user_input_queue: asyncio.Queue[dict] = asyncio.Queue()

        # 休眠状态
        self.is_hibernating: bool = True
        self.hibernation_buffer: deque[dict] = deque(maxlen=200)
        self.pending_notifications: deque[dict] = deque()

        # Sessions
        self.gm: Optional[SessionWrapper] = None
        self.user: Optional[SessionWrapper] = None

        # 网络
        self.orchestrator_reader: Optional[asyncio.StreamReader] = None
        self.orchestrator_writer: Optional[asyncio.StreamWriter] = None

        self._running = True
        self._spectator = False

    async def init(self):
        enable_logging(debug=False, redirect_stderr=False)

        config: Optional[Config] = None
        try:
            config = load_config()
        except Exception:
            pass

        # GM Session（所有模式必需）
        gm_work_dir = _prepare_md_work_dir(
            self.role_dir,
            "GM",
            prepend_shared="scoring_rules.md",
            append_shared=["core_hidden_layer.md", "info_entries.md", "public_map.md", "local_lore.md"],
        )
        gm_sid = f"{self.seat_id}_gm"
        self.gm = SessionWrapper("GM", gm_work_dir, gm_sid)
        await self.gm.init(config, self.model_name, self.thinking, self.yolo)

        # User Session（auto / npc / beatrice 模式）
        if self.mode in ("auto", "npc", "beatrice"):
            user_work_dir = _prepare_md_work_dir(
                self.role_dir,
                "PLAYER",
                append_name="PORTRAITS",
                prepend_shared="scoring_rules.md",
                append_shared=["public_map.md", "local_lore.md"],
            )
            user_sid = f"{self.seat_id}_user"
            self.user = SessionWrapper("USER", user_work_dir, user_sid)
            await self.user.init(config, self.model_name, self.thinking, self.yolo)

        # 连接 orchestrator
        await self._connect_to_orchestrator()
        print(f"[Agent] Seat {self.seat_id} started. mode={self.mode}")

    async def _connect_to_orchestrator(self):
        self.orchestrator_reader, self.orchestrator_writer = await asyncio.open_connection(
            self.orchestrator_host, self.orchestrator_port
        )
        register_msg = {
            "type": "register",
            "seat_id": self.seat_id,
            "role_name": self.role_dir.name,
        }
        self._send_to_orchestrator(register_msg)
        print(f"[Agent] Connected to orchestrator as {self.seat_id}")

    def _send_to_orchestrator(self, msg: dict):
        if self.orchestrator_writer is None:
            print(f"[Agent] Warning: not connected to orchestrator, dropping message")
            return
        data = json.dumps(msg, ensure_ascii=False) + "\n"
        self.orchestrator_writer.write(data.encode("utf-8"))

    async def _drain_orchestrator(self):
        if self.orchestrator_writer:
            await self.orchestrator_writer.drain()

    async def _orchestrator_reader_loop(self):
        """持续读取 orchestrator 发来的消息，放入 GM 队列。"""
        try:
            while self._running:
                line = await self.orchestrator_reader.readline()
                if not line:
                    print(f"[Agent] Orchestrator connection closed")
                    break
                try:
                    msg = json.loads(line.decode("utf-8").strip())
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type", "")
                if msg_type != "register_ok":
                    print(f"[Agent] [{self.seat_id}] Received: {msg_type} {msg.get('id', '')}")
                await self.gm_input_queue.put(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Agent] Orchestrator reader error: {e}")
            traceback.print_exc()

    async def _send_action(self, parent_id: str, action_text: str):
        """向 orchestrator 发送 action 消息（新协议）。"""
        self._send_to_orchestrator({
            "type": "action",
            "seat_id": self.seat_id,
            "role_name": self.role_dir.name,
            "action_text": action_text,
            "parent_id": parent_id,
        })
        await self._drain_orchestrator()

    async def _send_action_review(self, action_text: str, parent_id: str):
        """向 orchestrator 提交玩家行动审查请求（旧协议兼容）。"""
        self._send_to_orchestrator({
            "type": "action_review",
            "seat_id": self.seat_id,
            "role_name": self.role_dir.name,
            "action_text": action_text,
            "parent_id": parent_id,
            "id": f"review_{self.seat_id}_{parent_id}",
        })
        await self._drain_orchestrator()

    async def _send_action_review_result(
        self, request_id: str, result: str, reason: str, action_text: str, parent_id: str
    ):
        """向 orchestrator 返回 action_review 复核结果（仅 beatrice 模式）。"""
        text = f"【RESULT】{result}【/RESULT】\n【REASON】{reason}【/REASON】"
        self._send_to_orchestrator({
            "type": "action_review_result",
            "seat_id": self.seat_id,
            "request_id": request_id,
            "action_text": action_text,
            "result": result,
            "reason": reason,
            "text": text,
            "parent_id": parent_id,
            "id": request_id,
        })
        await self._drain_orchestrator()

    # -----------------------------------------------------------------------
    # 消息处理
    # -----------------------------------------------------------------------

    async def _process_gm_message(self, msg: dict):
        msg_type = msg.get("type", "")

        # turn_token 是唯一的激活入口
        if msg_type == "turn_token":
            await self._handle_turn_token(msg)
            return

        # 休眠状态下：非 turn_token 消息只缓存不调用 AI
        if self.is_hibernating and msg_type in ("notification", "scene"):
            if msg_type == "notification":
                self.hibernation_buffer.append(msg)
            else:
                self.hibernation_buffer.append(msg)
            return

        if msg_type == "scene":
            await self._handle_scene(msg)
        elif msg_type == "action_review":
            await self._handle_action_review(msg)
        elif msg_type == "action_review_result":
            await self._handle_action_review_result(msg)
        elif msg_type == "notification":
            await self._handle_notification(msg)
        elif msg_type == "spectator_mode":
            await self._handle_spectator_mode(msg)
        elif msg_type == "schrodinger_judgment":
            await self._handle_schrodinger_judgment(msg)
        elif msg_type == "player_input":
            await self._handle_player_input(msg)
        elif msg_type == "register_ok":
            print(f"[Agent] [{self.seat_id}] Registered with orchestrator")
        else:
            print(f"[Agent] [{self.seat_id}] Unknown message type: {msg_type}")

    async def _process_hibernation_buffer(self) -> str:
        """将 hibernation_buffer 中的全部消息传给 GM Session 处理。
        返回 GM 认知更新摘要（内部使用，不发给 orchestrator）。"""
        if not self.hibernation_buffer:
            return ""
        if self.gm is None:
            self.hibernation_buffer.clear()
            return ""

        # 整理 buffer 内容
        lines = []
        for msg in self.hibernation_buffer:
            title = msg.get("title", "")
            body = msg.get("body", "")
            text = msg.get("text", "")
            if title and body:
                lines.append(f"- [{title}] {body}")
            elif text:
                lines.append(f"- {text[:200]}")

        buffer_text = "\n".join(lines)
        prompt = f"【系统通知摘要】在你等待行动期间，发生了以下事件：\n\n{buffer_text}\n\n请简要更新你的认知（纯内部思考，不发给别人）。"

        try:
            out_text, _, _ = await self.gm.run_once(prompt)
        except Exception as e:
            print(f"[Agent] [GM] Buffer processing error: {e}")
            out_text = ""

        self.hibernation_buffer.clear()
        return out_text

    async def _handle_turn_token(self, msg: dict):
        """处理 turn_token 消息——轮到该 seat 行动了。
        这是唯一的激活入口。行动结束后自动回到休眠。"""
        msg_id = msg.get("id", "")
        slot = msg.get("slot", "")
        location = msg.get("location", "")
        round_num = msg.get("round", 1)
        total_rounds = msg.get("total_rounds", 2)
        action_points = msg.get("action_points", 0)

        # 激活
        self.is_hibernating = False

        # 观察者模式：跳过行动
        if self._spectator:
            await self._send_action(msg_id, "...（旁观者沉默）")
            self.is_hibernating = True
            return

        # 1. 先让 GM 处理 hibernation_buffer（认知更新）
        gm_summary = ""
        if self.gm:
            gm_summary = await self._process_hibernation_buffer()

        # 2. 构造 prompt
        prompt_parts = [
            f"【轮到你的回合】",
            f"时间：{slot}",
            f"地点：{location}",
            f"轮次：第{round_num}/{total_rounds}轮",
            f"剩余行动点：{action_points}",
        ]

        # 合并未读通知（非紧急的，在 buffer 处理时已经处理了紧急的）
        if self.pending_notifications:
            notif_summary = "\n\n【在你行动期间发生的事件】\n" + "\n".join(
                f"- {n.get('title', '')}: {n.get('body', '')}" for n in self.pending_notifications
            )
            prompt_parts.append(notif_summary)
            self.pending_notifications.clear()

        # 追加 GM 认知更新
        if gm_summary:
            prompt_parts.append(f"\n\n【GM 内部认知更新】\n{gm_summary}")

        prompt_parts.append(
            "\n\n请描述你的行动。行动可以是：\n"
            "- 调查（消耗2行动点）\n"
            "- 发言（消耗0行动点）\n"
            "- 移动（消耗1-3行动点，取决于距离）\n"
            "- 跳过\n\n"
            "请用自然语言描述你的行动，例如：\"我仔细调查了书房的每个角落\"或\"我走向餐厅\"。"
            "如果你希望下个时间点移动到其他地点，请在描述末尾声明：\"下轮移动：{地点名}\""
        )
        prompt = "\n".join(prompt_parts)

        # auto / npc / beatrice 模式：交给 User Session
        if self.mode in ("auto", "npc", "beatrice") and self.user:
            await self.user_input_queue.put({"type": "input", "text": prompt, "id": msg_id})
            # 不需要在这里发送 action，_user_loop 会处理
            return

        # human 模式：交给 GM Session 展示上下文
        if self.mode == "human" and self.gm:
            try:
                out_text, _, _ = await self.gm.run_once(prompt)
                player_input = _extract_player_input(out_text)
                if player_input:
                    await self._send_action(msg_id, player_input)
                else:
                    await self._send_action(msg_id, out_text.strip() or "...（沉默）")
            except Exception as e:
                print(f"[Agent] [GM] Error handling turn_token: {e}")
                await self._send_action(msg_id, f"[处理出错: {e}]")

        # 回到休眠
        self.is_hibernating = True

    async def _handle_scene(self, msg: dict):
        """处理场景消息（旧协议兼容）。"""
        text = msg.get("text", "")
        msg_id = msg.get("id", "")

        if self._spectator:
            if self.gm:
                try:
                    await self.gm.run_once(text)
                except Exception:
                    pass
            return

        # 追加行动点信息
        ap = msg.get("action_points")
        if ap is not None:
            text = text + f"\n\n【系统状态】你当前剩余行动点：{ap}。请根据剩余行动点合理规划行动。\n"

        # 合并未读通知
        if self.pending_notifications:
            notif_summary = "\n\n【在你行动期间发生的事件】\n" + "\n".join(
                f"- {n.get('title', '')}: {n.get('body', '')}" for n in self.pending_notifications
            )
            text = text + notif_summary
            self.pending_notifications.clear()

        if self.mode in ("auto", "npc", "beatrice"):
            if self.user is None or self._spectator:
                return
            user_text = f"{text}\n\n请描述你的行动。"
            await self.user_input_queue.put({"type": "input", "text": user_text, "id": msg_id})
            self._send_to_orchestrator({
                "type": "gm_output",
                "seat_id": self.seat_id,
                "parent_id": msg_id,
                "text": "场景已转交给 User Session 处理。",
                "orchestration_requests": [],
            })
            await self._drain_orchestrator()
            return

        # human 模式
        try:
            out_text, thinking_parts, orch_reqs = await self.gm.run_once(text)
        except Exception as e:
            print(f"[Agent] [GM] Error: {e}")
            traceback.print_exc()
            self._send_to_orchestrator({
                "type": "gm_output",
                "seat_id": self.seat_id,
                "parent_id": msg_id,
                "text": f"[GM 处理出错: {e}]",
                "error": True,
            })
            await self._drain_orchestrator()
            return

        clean_text = _strip_blocks(out_text)
        self._send_to_orchestrator({
            "type": "gm_output",
            "seat_id": self.seat_id,
            "parent_id": msg_id,
            "text": clean_text,
            "thinking": "".join(thinking_parts) if thinking_parts else None,
            "orchestration_requests": orch_reqs,
        })
        await self._drain_orchestrator()

        player_input = _extract_player_input(out_text)
        if player_input:
            await self._send_action_review(player_input, msg_id)

    async def _handle_action_review(self, msg: dict):
        """处理审查请求（beatrice 模式）。"""
        if self.mode != "beatrice":
            return

        text = msg.get("text", "")
        msg_id = msg.get("id", "")
        request_id = msg.get("id", "")
        action_text = msg.get("action_text", "")
        parent_id = msg.get("parent_id", "")

        try:
            out_text, _, _ = await self.gm.run_once(text)
        except Exception as e:
            print(f"[Agent] [BEATRICE] Error: {e}")
            traceback.print_exc()
            await self._send_action_review_result(
                request_id, "approve", "审查出错，默认通过", action_text, parent_id
            )
            return

        result_match = re.search(r"【RESULT】\s*(approve|reject)\s*【/RESULT】", out_text, re.IGNORECASE)
        reason_match = re.search(r"【REASON】\s*(.*?)\s*【/REASON】", out_text, re.DOTALL)
        result = result_match.group(1).lower() if result_match else "approve"
        reason = reason_match.group(1).strip() if reason_match else out_text[:200]

        await self._send_action_review_result(request_id, result, reason, action_text, parent_id)

    async def _handle_action_review_result(self, msg: dict):
        """处理 BEATRICE 返回的审查结果。"""
        result = msg.get("result", "")
        reason = msg.get("reason", "")
        original_action = msg.get("original_action", "")
        msg_id = msg.get("id", "")

        if result == "approve":
            notify_text = f"【GM 审查结果】你的行动已通过。\n原因: {reason}"
            if self.mode in ("auto", "npc", "beatrice") and self.user:
                await self.user_input_queue.put({"type": "input", "text": notify_text, "id": msg_id})
            else:
                try:
                    await self.gm.run_once(notify_text)
                except Exception:
                    pass
        else:
            reject_base = f"【GM 审查结果】你的行动未通过。\n原因: {reason}\n\n你之前的行动:\n{original_action}\n\n请给出修改建议，让该行动合规。"
            if self.mode in ("auto", "npc", "beatrice") and self.user and self.gm:
                try:
                    gm_advice, _, _ = await self.gm.run_once(reject_base)
                except Exception:
                    gm_advice = "请避免泄露核心秘密，只基于游戏内已知信息进行描述。"
                retry_text = (
                    f"【GM 反馈】\n{reason}\n\n"
                    f"【修改建议】\n{gm_advice}\n\n"
                    f"请根据以上反馈重新描述你的行动。"
                )
                await self.user_input_queue.put({"type": "input", "text": retry_text, "id": msg_id})
            else:
                try:
                    await self.gm.run_once(reject_base)
                except Exception:
                    pass

    async def _handle_notification(self, msg: dict):
        """处理 orchestrator 发来的系统通知。"""
        if self.is_hibernating:
            # 休眠时存入 buffer（但如果 buffer 已处理过同类型的，可去重）
            self.hibernation_buffer.append(msg)
            return

        # 非休眠状态下，紧急通知立即处理，非紧急的暂存
        if msg.get("urgent", False):
            if self.mode == "human":
                notif_text = f"【系统通知 - {msg.get('title', '')}】\n{msg.get('body', '')}"
                try:
                    await self.gm.run_once(notif_text)
                except Exception:
                    pass
            else:
                self.pending_notifications.append(msg)
        else:
            self.pending_notifications.append(msg)

    async def _handle_spectator_mode(self, msg: dict):
        """进入观察者模式。"""
        if self._spectator:
            return
        self._spectator = True
        print(f"[Agent] [{self.seat_id}] Entering spectator mode")
        notif_text = f"【系统通知 - {msg.get('title', '观察者模式')}】\n{msg.get('body', '')}"
        if self.gm:
            try:
                await self.gm.run_once(notif_text)
            except Exception:
                pass
        if self.user is not None:
            self.user = None
            print(f"[Agent] [{self.seat_id}] User Session disabled in spectator mode")

    async def _handle_schrodinger_judgment(self, msg: dict):
        """贝阿朵模式：对薛定谔违规进行裁决。"""
        if self.mode != "beatrice":
            return
        text = msg.get("text", "")
        msg_id = msg.get("id", "")
        try:
            out_text, _, _ = await self.gm.run_once(text)
        except Exception as e:
            print(f"[Agent] [BEATRICE] Judgment error: {e}")
            out_text = "【JUDGMENT】kill: 嘉音【/JUDGMENT】\n【REASON】裁决异常，默认执行守护者清除协议。"
        print(f"[Agent] [BEATRICE] Judgment ({msg_id}): {out_text[:120]}...")
        self._send_to_orchestrator({
            "type": "schrodinger_judgment_result",
            "seat_id": self.seat_id,
            "parent_id": msg_id,
            "text": out_text,
        })
        await self._drain_orchestrator()

    async def _handle_player_input(self, msg: dict):
        """处理 orchestrator 发来的人类玩家输入（备用）。"""
        text = msg.get("text", "")
        msg_id = msg.get("id", "")
        if self.mode == "human" and self.gm:
            try:
                out_text, _, _ = await self.gm.run_once(text)
                player_input = _extract_player_input(out_text)
                if player_input:
                    await self._send_action_review(player_input, msg_id)
            except Exception as e:
                print(f"[Agent] [GM] Error handling player_input: {e}")

    # -----------------------------------------------------------------------
    # 内部循环
    # -----------------------------------------------------------------------

    async def _user_loop(self):
        """AI 模式下：消费 user_input_queue，运行 User Session，发送 action。"""
        if self.user is None:
            return
        try:
            while self._running:
                if self._spectator:
                    await asyncio.sleep(1)
                    continue
                msg = await self.user_input_queue.get()
                if msg.get("type") != "input":
                    continue
                text = msg.get("text", "")
                msg_id = msg.get("id", "")
                print(f"[Agent] [USER] Input ({msg_id}): {text[:120]}...")

                try:
                    out_text, thinking_parts, _ = await self.user.run_once(text)
                except Exception as e:
                    print(f"[Agent] [USER] Error: {e}")
                    traceback.print_exc()
                    continue

                print(f"[Agent] [USER] Output ({msg_id}): {out_text[:120]}...")

                # 新协议：直接发送 action
                if msg_id.startswith("turn_"):
                    await self._send_action(msg_id, out_text)
                    # 发送 action 后立即回到休眠
                    self.is_hibernating = True
                else:
                    # 旧协议兼容：scene 触发发送 action_review
                    await self._send_action_review(out_text, msg_id)
        except asyncio.CancelledError:
            pass

    async def _gm_loop(self):
        """GM 主循环：消费 gm_input_queue。"""
        try:
            while self._running:
                msg = await self.gm_input_queue.get()
                await self._process_gm_message(msg)
        except asyncio.CancelledError:
            pass

    async def run(self):
        tasks = [
            asyncio.create_task(self._orchestrator_reader_loop()),
            asyncio.create_task(self._gm_loop()),
        ]
        if self.mode in ("auto", "npc", "beatrice") and self.user:
            tasks.append(asyncio.create_task(self._user_loop()))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            for t in tasks:
                t.cancel()
            if self.orchestrator_writer:
                self.orchestrator_writer.close()
                await self.orchestrator_writer.wait_closed()
            if self.gm and self.gm.instance:
                self.gm.instance.shutdown_background_tasks()
            if self.user and self.user.instance:
                self.user.instance.shutdown_background_tasks()
            print(f"[Agent] Seat {self.seat_id} stopped.")

    async def init_and_run(self):
        await self.init()
        await self.run()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="Seat Agent Wrapper for Umineko")
    parser.add_argument("--work-dir", type=Path, required=True, help="Role directory")
    parser.add_argument("--seat-id", type=str, required=True, help="Seat ID, e.g. P1")
    parser.add_argument("--orchestrator-host", type=str, default="127.0.0.1", help="Orchestrator host")
    parser.add_argument("--orchestrator-port", type=int, required=True, help="Orchestrator port")
    parser.add_argument("--mode", type=str, choices=["auto", "human", "beatrice", "npc"], default="auto",
                        help="auto=AI mock user, human=human player, beatrice=贝阿朵莉切(可扮演), npc=NPC轻量模式")
    parser.add_argument("--yolo", action="store_true", default=True)
    parser.add_argument("--no-yolo", dest="yolo", action="store_false")
    parser.add_argument("--thinking", action="store_true", default=False)
    parser.add_argument("--model", type=str, default=None)
    args = parser.parse_args()

    agent = SeatAgent(
        role_dir=args.work_dir.resolve(),
        seat_id=args.seat_id,
        orchestrator_host=args.orchestrator_host,
        orchestrator_port=args.orchestrator_port,
        mode=args.mode,
        yolo=args.yolo,
        thinking=args.thinking,
        model_name=args.model,
    )

    asyncio.run(agent.init_and_run())


if __name__ == "__main__":
    main()
