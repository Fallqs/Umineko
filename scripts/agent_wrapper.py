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

from npc_prompt_builder import build_npc_prompt
from prompt_loader import PromptLoader


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
    """从 GM 输出中提取 <orchestration_request>块，并去重。"""
    pattern = r"<orchestration_request>\s*(.*?)\s*</orchestration_request>"
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
    """提取 <player_input>块内容（人类模式）。"""
    pattern = r"<player_input>\s*(.*?)\s*</player_input>"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else None


def _strip_blocks(text: str) -> str:
    """移除 orchestration/player_input 块，返回干净文本。"""
    text = re.sub(r"<orchestration_request>\s*.*?\s*</orchestration_request>", "", text, flags=re.DOTALL)
    text = re.sub(r"<player_input>\s*.*?\s*</player_input>", "", text, flags=re.DOTALL)
    return text.strip()


# ---------------------------------------------------------------------------
# GM 输出验证器（前置到 agent 侧，支持同 Session 内修正重试）
# ---------------------------------------------------------------------------

class GMOutputValidator:
    """验证 BEATRICE (GM) 的结构化输出格式。

    设计目标：在 agent_wrapper 侧完成格式校验，解析失败时
    立即在同一会话内要求 GM 修正，避免错误格式传播到 orchestrator。
    """

    MAX_RETRIES: int = 2

    @staticmethod
    def validate_action_review(text: str) -> tuple[bool, str, str, list[str]]:
        """验证 action_review 输出。

        Returns:
            (success, result, reason, errors)
        """
        result_match = re.search(r"<result>\s*(approve|reject)\s*</result>", text, re.IGNORECASE)
        reason_match = re.search(r"<reason>\s*(.*?)\s*</reason>", text, re.DOTALL)

        errors: list[str] = []
        if not result_match:
            errors.append("缺少 <result>approve</result> 或 <result>reject</result> 标签")
        if not reason_match:
            errors.append("缺少 <reason>审查原因</reason> 标签")

        if errors:
            return False, "", "", errors

        return True, result_match.group(1).lower(), reason_match.group(1).strip(), []

    @staticmethod
    def validate_schrodinger_judgment(text: str) -> tuple[bool, str, str, list[str]]:
        """验证 schrodinger_judgment 输出。

        Returns:
            (success, victim, reason, errors)
        """
        judgment_match = re.search(r"<judgment>\s*kill:\s*(嘉音|纱音)\s*</judgment>", text, re.IGNORECASE)
        reason_match = re.search(r"<reason>\s*(.*?)\s*</reason>", text, re.DOTALL)

        errors: list[str] = []
        if not judgment_match:
            errors.append('缺少 <judgment>kill: 嘉音</judgment> 或 <judgment>kill: 纱音</judgment> 标签')

        if errors:
            return False, "", "", errors

        reason = reason_match.group(1).strip() if reason_match else "无原因"
        return True, judgment_match.group(1), reason, []

    @staticmethod
    def build_correction_prompt(original_prompt: str, errors: list[str], original_output: str, template: str = "") -> str:
        """构建修正 prompt，在同一会话内要求 GM 修正格式错误。
        
        若提供 template，则使用模板渲染；否则使用 fallback 文本。
        """
        error_text = "\n".join(f"- {e}" for e in errors)
        if template:
            from string import Template
            return Template(template).safe_substitute(
                original_prompt=original_prompt,
                errors=error_text,
                original_output=original_output,
            )
        return (
            f"{original_prompt}\n\n"
            f"【格式错误】你之前的输出存在以下问题：\n"
            f"{error_text}\n\n"
            f"你之前的输出：\n{original_output}\n\n"
            f"请修正以上问题，重新输出正确的格式。只输出 XML 标签内容，不要添加额外解释。"
        )


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
        # 事件数量校验
        self.received_event_count: int = 0
        # 兼容旧机制（过渡期保留）
        self.hibernation_buffer: deque[dict] = deque(maxlen=200)
        self.pending_notifications: deque[dict] = deque()

        # Sessions
        self.gm: Optional[SessionWrapper] = None
        self.user: Optional[SessionWrapper] = None

        # Prompt 模板加载器
        self.prompt_loader = PromptLoader()

        # 网络
        self.orchestrator_reader: Optional[asyncio.StreamReader] = None
        self.orchestrator_writer: Optional[asyncio.StreamWriter] = None

        # 预解析请求等待池
        self._pending_preparse: dict[str, asyncio.Future] = {}

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

        # User Session（auto / beatrice 模式）
        # npc 模式：GM 与 User 合并为同一个 Session，不单独创建 User Session
        if self.mode in ("auto", "beatrice"):
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
                if msg_type == "notification":
                    # 事件数量校验：无论休眠状态如何，收到即计数
                    self.received_event_count += 1
                if msg_type not in ("register_ok", "notification"):
                    print(f"[Agent] [{self.seat_id}] Received: {msg_type} {msg.get('id', '')}")
                elif msg_type == "notification" and msg.get("severity") == "error":
                    print(f"[Agent] [{self.seat_id}] Received: {msg_type} [{msg.get('title', '')}] {msg.get('body', '')[:60]}")
                # pre_parse_result 直接唤醒等待的 future，不入 GM 队列
                if msg_type == "pre_parse_result":
                    req_id = msg.get("request_id", "")
                    future = self._pending_preparse.pop(req_id, None)
                    if future and not future.done():
                        future.set_result(msg)
                    continue
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
        text = f"<result>{result}</result>\n<reason>{reason}</reason>"
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
        elif msg_type == "inherited_state":
            await self._handle_inherited_state(msg)
        elif msg_type == "schrodinger_judgment":
            await self._handle_schrodinger_judgment(msg)
        elif msg_type == "player_input":
            await self._handle_player_input(msg)
        elif msg_type == "register_ok":
            print(f"[Agent] [{self.seat_id}] Registered with orchestrator")
        else:
            print(f"[Agent] [{self.seat_id}] Unknown message type: {msg_type}")

    def _extract_buffer_events(self) -> list[str]:
        """从 hibernation_buffer 中提取可直接向玩家展示的事件。
        提取后这些消息会从 buffer 中移除，避免 GM Session 重复处理。
        返回事件描述列表（供 prompt 直接展示）。"""
        events: list[str] = []
        remaining: deque[dict] = deque()

        for msg in self.hibernation_buffer:
            title = msg.get("title", "")
            body = msg.get("body", "")

            # 这些类型的事件玩家可以直接感知
            direct_perception_types = {
                "同场发言", "同场事件", "收到物品", "被安慰", "被搜身",
                "被观察", "调查发现", "射击", "拾取", "使用物品", "赠送",
            }

            if title in direct_perception_types and body:
                events.append(f"[{title}] {body}")
            else:
                # 其他消息留给 GM Session 处理
                remaining.append(msg)

        self.hibernation_buffer = remaining
        return events

    async def _process_hibernation_buffer(self) -> str:
        """将 hibernation_buffer 中剩余的消息传给 GM Session 处理。
        返回 GM 认知更新摘要（内部使用，不发给 orchestrator）。"""
        if not self.hibernation_buffer:
            return ""
        if self.gm is None:
            self.hibernation_buffer.clear()
            return ""

        # 整理 buffer 内容（此时直接感知类事件已被 _extract_buffer_events 过滤掉）
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
        if not buffer_text:
            self.hibernation_buffer.clear()
            return ""

        prompt = self.prompt_loader.load_or_fallback(
            "buffer_summary",
            f"【系统通知摘要】在你等待行动期间，发生了以下事件：\n\n{buffer_text}\n\n请简要更新你的认知（纯内部思考，不发给别人）。",
            events=buffer_text,
        )

        try:
            out_text, _, _ = await self.gm.run_once(prompt)
        except Exception as e:
            print(f"[Agent] [GM] Buffer processing error: {e}")
            out_text = ""

        self.hibernation_buffer.clear()
        return out_text

    # -----------------------------------------------------------------------
    # 结构化行动解析与审查（新增）
    # -----------------------------------------------------------------------

    def _parse_player_output(self, text: str) -> dict:
        """解析 Player Session 的输出，提取 $action / $sound / $argue。
        返回包含解析结果的字典。"""
        result = {
            "action_text": "",
            "speech": "",
            "argue": "",
            "move_target": "",
            "investigate": False,
            "investigate_target": "",
            "is_valid": False,
            "error_msg": "",
        }
        if not text:
            result["error_msg"] = "输出为空"
            return result

        # 提取 $sound
        sound_match = re.search(r'\$sound\s+"([^"]+)"', text)
        if not sound_match:
            sound_match = re.search(r'\$sound\s+(.+?)(?=\n\s*\$|\n*$)', text, re.DOTALL)
        if sound_match:
            result["speech"] = sound_match.group(1).strip()

        # 提取 $action
        action_match = re.search(r'\$action\s+(.+?)(?=\n\s*\$argue|\n\s*\$sound|\n*$)', text, re.DOTALL)
        if not action_match:
            action_match = re.search(r'\$action\s+(.+)', text, re.DOTALL)
        if action_match:
            action_content = action_match.group(1).strip()
            result["action_text"] = action_content
            # 提取子命令
            move_match = re.search(r'下轮移动[：:]\s*(\S+)', action_content)
            if move_match:
                result["move_target"] = move_match.group(1).strip().rstrip('。，！？.!?')
            inv_match = re.search(r'调查\s*(\S+)', action_content)
            if inv_match:
                result["investigate"] = True
                target = inv_match.group(1).strip().rstrip('。，！？.!?')
                if target not in ("了", "一下", "周围", "附近", "此地", "这里"):
                    result["investigate_target"] = target

        # 提取 $argue
        argue_match = re.search(r'\$argue\s+(.+?)(?=\n\s*\$|\n*$)', text, re.DOTALL)
        if argue_match:
            result["argue"] = argue_match.group(1).strip()

        # 验证：至少要有 $sound 或 $action
        if not result["action_text"] and not result["speech"]:
            result["error_msg"] = "输出格式错误：缺少 $action 或 $sound。请按格式要求输出。"
            return result

        result["is_valid"] = True
        return result

    async def _gm_review(self, buffer_text: str, parsed: dict) -> tuple[bool, str, dict]:
        """调用 GM Session 做合规审查。
        返回 (approved, reason, action_package)"""
        if self.gm is None:
            return True, "GM Session 未初始化，默认通过", parsed

        sound_line = f'$sound "{parsed["speech"]}"' if parsed["speech"] else ""
        action_line = f'$action {parsed["action_text"]}' if parsed["action_text"] else ""
        argue_line = f'$argue {parsed["argue"]}' if parsed["argue"] else ""

        role_name = self.role_dir.name
        role_special = ""
        if role_name == "贝阿朵莉切":
            role_special = (
                "你是黄金魔女贝阿朵莉切，拥有红字与金字能力。"
                "你可以在发言中使用<red>绝对真实的陈述</red>和<gold>无需证明的真理</gold>。"
                "你应当保持魔女的傲慢与神秘感，不要像普通人一样行动。"
            )

        prompt = self.prompt_loader.load_or_fallback(
            "gm_review",
            f"【GM合规审查】\n\n请审查以下行动是否合规：\n{sound_line}\n{action_line}\n{argue_line}\n\n"
            f"上下文：\n{buffer_text}\n\n请输出 <result>approve|reject</result> 和 <reason>原因</reason>",
            sound_line=sound_line,
            action_line=action_line,
            argue_line=argue_line,
            buffer_text=buffer_text,
            role_name=role_name,
            role_special=role_special,
        )

        try:
            out_text, _, _ = await self.gm.run_once(prompt)
        except Exception as e:
            print(f"[Agent] [GM] Review error: {e}")
            return True, f"GM 审查异常（{e}），默认通过", parsed

        # 解析 GM 输出
        result_match = re.search(r'<result>\s*(approve|reject)\s*</result>', out_text, re.IGNORECASE)
        reason_match = re.search(r'<reason>\s*(.*?)\s*</reason>', out_text, re.DOTALL)

        approved = result_match is not None and result_match.group(1).lower() == "approve"
        reason = reason_match.group(1).strip() if reason_match else "无原因"

        # 提取 action_package（XML 格式）
        action_package = dict(parsed)
        pkg_match = re.search(r'<action_package>(.*?)</action_package>', out_text, re.DOTALL)
        if pkg_match:
            pkg_text = pkg_match.group(1).strip()
            for tag in ["action_text", "speech", "move_target", "investigate_target"]:
                tag_match = re.search(rf'<{tag}>(.*?)</{tag}>', pkg_text, re.DOTALL)
                if tag_match:
                    action_package[tag] = tag_match.group(1).strip()
            inv_match = re.search(r'<investigate>(true|false)</investigate>', pkg_text, re.IGNORECASE)
            if inv_match:
                action_package["investigate"] = inv_match.group(1).lower() == "true"

        return approved, reason, action_package

    async def _pre_parse(self, action_package: dict) -> tuple[bool, str]:
        """向 orchestrator 发送 pre_parse 请求，验证行动是否可解析。
        返回 (success, error_msg)
        
        注意：只传递 action_text 和 move_target 给预解析，
        speech（发言内容）不参与行动解析，避免日常对话中的"去""走向"等词被误识别为移动意图。"""
        parts = []
        if action_package.get("action_text"):
            parts.append(action_package["action_text"])
        if action_package.get("move_target"):
            parts.append(f'下轮移动：{action_package["move_target"]}')
        standardized = "\n".join(parts)
        if not standardized:
            return True, ""

        request_id = f"preparse_{self.seat_id}_{asyncio.get_event_loop().time()}"
        future = asyncio.get_event_loop().create_future()
        self._pending_preparse[request_id] = future

        self._send_to_orchestrator({
            "type": "pre_parse",
            "seat_id": self.seat_id,
            "request_id": request_id,
            "action_text": standardized,
        })
        await self._drain_orchestrator()

        try:
            result = await asyncio.wait_for(future, timeout=10.0)
            if result.get("success"):
                return True, ""
            else:
                return False, result.get("error", "预解析失败")
        except asyncio.TimeoutError:
            print(f"[Agent] pre_parse timeout for {request_id}")
            return True, "预解析超时，默认通过"
        finally:
            self._pending_preparse.pop(request_id, None)

    async def _handle_turn_token(self, msg: dict):
        """处理 turn_token 消息——轮到该 seat 行动了。
        这是唯一的激活入口。行动结束后自动回到休眠。"""
        msg_id = msg.get("id", "")
        slot = msg.get("time_slot", "")
        location = msg.get("location", "")
        round_num = msg.get("token_round", 1)
        total_rounds = msg.get("token_total_rounds", 10)
        action_points = msg.get("action_points", 0)
        investigations_remaining = msg.get("investigations_remaining", 2)

        # 激活
        self.is_hibernating = False

        # 观察者模式：跳过行动
        if self._spectator:
            await self._send_action(msg_id, "...（旁观者沉默）")
            self.is_hibernating = True
            return

        # 1. 事件数量校验
        expected_count = msg.get("expected_event_count", 0)
        if expected_count > 0:
            if self.received_event_count < expected_count:
                missing = expected_count - self.received_event_count
                print(f"[Agent] [{self.seat_id}] 事件校验警告：应收到 {expected_count} 条，实际收到 {self.received_event_count} 条，缺失 {missing} 条")
            else:
                print(f"[Agent] [{self.seat_id}] 事件校验通过：{self.received_event_count}/{expected_count}")
            # 重置计数器（为下一轮做准备）
            self.received_event_count = 0

        # 2. 提取完整的 buffer 文本（暂不清空，等审查通过后再清空）
        # 合并 hibernation_buffer + pending_notifications
        buffer_lines = []
        for buf_msg in self.hibernation_buffer:
            title = buf_msg.get("title", "")
            body = buf_msg.get("body", "")
            text = buf_msg.get("text", "")
            if title and body:
                buffer_lines.append(f"- [{title}] {body}")
            elif text:
                buffer_lines.append(f"- {text[:200]}")
        # 合并未读的 pending notifications
        if self.pending_notifications:
            for n in self.pending_notifications:
                title = n.get("title", "")
                body = n.get("body", "")
                if title and body:
                    buffer_lines.append(f"- [{title}] {body}")
            self.pending_notifications.clear()
        buffer_text = "\n".join(buffer_lines) if buffer_lines else "（无新事件）"

        # 2. 从模板加载 player prompt
        inventory = msg.get("inventory", [])
        inventory_str = ", ".join(inventory) if inventory else "（空）"

        if investigations_remaining > 0:
            investigate_desc = f"- 调查当前地点或指定对象（消耗2行动点，本时间槽剩余 {investigations_remaining}/2 次机会）"
        else:
            investigate_desc = "- 调查（本时间槽次数已用尽，本轮无法调查）"

        prompt = self.prompt_loader.load_or_fallback(
            "player_turn",
            f"【轮到你的回合】\n"
            f"时间：{slot}\n"
            f"地点：{location}\n"
            f"轮次：第{round_num}/{total_rounds}轮对话\n"
            f"剩余行动点：{action_points}\n"
            f"本时间槽剩余调查次数：{investigations_remaining}次\n"
            f"你携带的物品：{inventory_str}\n\n"
            f"【你观察到的上下文事件】\n{buffer_text}\n\n"
            f"【可选行动】\n"
            f"- 发言（消耗0行动点）\n"
            f"{investigate_desc}\n"
            f"- 使用背包中的物品（消耗1行动点）\n"
            f"- 移动（消耗1-3行动点）\n"
            f"- 跳过\n\n"
            f"请用简洁的自然语言描述你的行动（200字以内）。",
            time_slot=slot,
            location=location,
            round_num=str(round_num),
            total_rounds=str(total_rounds),
            action_points=str(action_points),
            investigations_remaining=str(investigations_remaining),
            inventory=inventory_str,
            buffer_events=buffer_text,
            investigate_desc=investigate_desc,
        )

        # 贝阿朵莉切特殊能力
        if self.role_dir.name == "贝阿朵莉切":
            special_text = self.prompt_loader.load_or_fallback(
                "beatrice_special",
                "\n\n【身份：黄金魔女贝阿朵莉切】"
                "你是传说中的黄金魔女，六轩岛真正的主人。你的存在本身就是一个谜。"
                "你拥有红字与金字的能力，可以在发言中使用 <red>绝对真实的陈述</red> 和 <gold>无需证明的真理</gold>。"
                "\n"
                "【扮演要求】"
                "1. 保持魔女的傲慢与神秘感。你的语气应当优雅、戏谑、带有居高临下的从容。"
                "2. 不要像普通人一样关心日常琐事（早餐、天气、家务等）。你的关注点应该是仪式、命运、真相。"
                "3. 你可以暗示自己知晓一切，但不要轻易揭示。谜题的乐趣在于让人类挣扎。"
                "4. 对其他角色使用带有距离感的称呼，不要显得过于亲近。"
                "5. 行动应当带有超自然色彩或象征意义，而非普通的调查/移动。"
                "\n"
                "【示例口吻】"
                '- "人类的智慧真是渺小呢。不过，我喜欢看你们挣扎的样子。"'
                '- "契约已经缔结。接下来的命运，谁也改变不了——<red>包括我自己</red>。"'
                '- "去吧，去追寻你想要的真相。但记住，<gold>没有爱，就看不见。</gold>"',
            )
            prompt = prompt + "\n" + special_text

        # auto / beatrice 模式：交给 User Session（_user_loop 会处理解析、审查、预解析）
        if self.mode in ("auto", "beatrice") and self.user:
            await self.user_input_queue.put({
                "type": "input",
                "text": prompt,
                "id": msg_id,
                "buffer_text": buffer_text,
            })
            return

        # human / npc 模式：直接用 GM Session 生成行动（简化处理，不做审查预解析）
        if self.mode in ("human", "npc") and self.gm:
            try:
                                if self.mode == "npc":
                    preset = build_npc_prompt(self.role_dir)
                    npc_situation = f"{situation}

记住你是谁。记住你在乎谁。保护你所爱的，躲避你所惧的，保守你的秘密，尽力活下去！"
                    prompt = npc_situation + "

" + prompt
                    if preset:
                        prompt = prompt + f"

{preset}"
                out_text, _, _ = await self.gm.run_once(prompt)
                player_input = _extract_player_input(out_text)
                if player_input:
                    await self._send_action(msg_id, player_input)
                else:
                    await self._send_action(msg_id, out_text.strip() or "...（沉默）")
            except Exception as e:
                print(f"[Agent] [{self.mode}] Error handling turn_token: {e}")
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

        # 追加行动点与调查次数信息
        ap = msg.get("action_points")
        if ap is not None:
            text = text + f"\n\n【系统状态】你当前剩余行动点：{ap}。请根据剩余行动点合理规划行动。\n"
        inv_remaining = msg.get("investigations_remaining")
        if inv_remaining is not None:
            text = text + f"【系统状态】本时间槽剩余调查次数：{inv_remaining}/2。\n"

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
        """处理审查请求（beatrice 模式），带格式验证和同 Session 内重试修正。"""
        if self.mode != "beatrice":
            return

        text = msg.get("text", "")
        request_id = msg.get("id", "")
        action_text = msg.get("action_text", "")
        parent_id = msg.get("parent_id", "")

        current_prompt = text
        out_text = ""
        max_attempts = GMOutputValidator.MAX_RETRIES + 1

        for attempt in range(max_attempts):
            try:
                out_text, _, _ = await self.gm.run_once(current_prompt)
            except Exception as e:
                print(f"[Agent] [BEATRICE] Review error (attempt {attempt + 1}/{max_attempts}): {e}")
                if attempt == GMOutputValidator.MAX_RETRIES:
                    await self._send_action_review_result(
                        request_id, "approve", f"审查异常（{e}），默认通过", action_text, parent_id
                    )
                    return
                continue

            success, result, reason, errors = GMOutputValidator.validate_action_review(out_text)
            if success:
                print(f"[Agent] [BEATRICE] Review validated (attempt {attempt + 1}): {result}")
                await self._send_action_review_result(request_id, result, reason, action_text, parent_id)
                return

            print(
                f"[Agent] [BEATRICE] Review format error (attempt {attempt + 1}/{max_attempts}): "
                f"{'; '.join(errors)}"
            )

            if attempt < GMOutputValidator.MAX_RETRIES:
                correction_template = self.prompt_loader.load("correction")
                current_prompt = GMOutputValidator.build_correction_prompt(text, errors, out_text, template=correction_template)
            else:
                # 重试耗尽，fallback 到默认值
                fallback_reason = f"审查格式错误（{'；'.join(errors)}），默认通过"
                await self._send_action_review_result(
                    request_id, "approve", fallback_reason, action_text, parent_id
                )

    async def _handle_action_review_result(self, msg: dict):
        """处理 BEATRICE 返回的审查结果。"""
        result = msg.get("result", "")
        reason = msg.get("reason", "")
        original_action = msg.get("original_action", "")
        msg_id = msg.get("id", "")

        if result == "approve":
            notify_text = f"【GM 审查结果】你的行动已通过。\n原因: {reason}"
            if self.mode in ("auto", "beatrice") and self.user:
                await self.user_input_queue.put({"type": "input", "text": notify_text, "id": msg_id})
            else:
                try:
                    await self.gm.run_once(notify_text)
                except Exception:
                    pass
        else:
            reject_base = f"【GM 审查结果】你的行动未通过。\n原因: {reason}\n\n你之前的行动:\n{original_action}\n\n请给出修改建议，让该行动合规。"
            if self.mode in ("auto", "beatrice") and self.user and self.gm:
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
        """处理 orchestrator 发来的系统通知。
        注意：事件数量计数已在 _orchestrator_reader_loop 中完成。"""
        # 兼容旧机制：按休眠状态分发到不同 buffer
        if self.is_hibernating:
            self.hibernation_buffer.append(msg)
        else:
            self.pending_notifications.append(msg)

        # 人类模式：实时打印
        if self.mode == "human":
            title = msg.get("title", "")
            body = msg.get("body", "")
            severity = msg.get("severity", "info")
            prefix = "⚠️" if severity == "error" else "ℹ️"
            print(f"{prefix} [{title}] {body}")

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

    async def _handle_inherited_state(self, msg: dict):
        """接收从NPC继承的状态，更新本地GM Session认知。"""
        state = msg.get("state", {})
        role = msg.get("role_name", self.role_dir.name)
        summary_lines = [f"【系统】你接管了新的角色 {role}。以下是该角色的当前状态："]
        if "location" in state:
            summary_lines.append(f"- 当前位置：{state['location']}")
        if "action_points" in state:
            summary_lines.append(f"- 剩余行动点：{state['action_points']}")
        if "unlocked_info" in state:
            infos = state["unlocked_info"]
            summary_lines.append(f"- 已收集信息条目：{len(infos)} 条")
        if "pending_moves" in state and state["pending_moves"]:
            summary_lines.append(f"- 移动意向：{state['pending_moves']}")
        if "sleeping" in state and state["sleeping"]:
            summary_lines.append("- 状态：已选择睡觉")
        if "night_owl" in state and state["night_owl"]:
            summary_lines.append("- 状态：选择熬夜（行动消耗2倍）")
        summary = "\n".join(summary_lines)
        if self.gm:
            try:
                await self.gm.run_once(summary)
            except Exception as e:
                print(f"[Agent] [{self.seat_id}] Failed to update GM with inherited state: {e}")
        print(f"[Agent] [{self.seat_id}] Inherited state for {role}: ap={state.get('action_points')}, loc={state.get('location')}")

    async def _handle_schrodinger_judgment(self, msg: dict):
        """贝阿朵模式：对薛定谔违规进行裁决，带格式验证和同 Session 内重试修正。"""
        if self.mode != "beatrice":
            return

        text = msg.get("text", "")
        msg_id = msg.get("id", "")

        current_prompt = text
        out_text = ""
        max_attempts = GMOutputValidator.MAX_RETRIES + 1
        final_victim = "嘉音"
        final_reason = "裁决格式错误，默认执行守护者清除协议。"

        for attempt in range(max_attempts):
            try:
                out_text, _, _ = await self.gm.run_once(current_prompt)
            except Exception as e:
                print(f"[Agent] [BEATRICE] Judgment error (attempt {attempt + 1}/{max_attempts}): {e}")
                if attempt == GMOutputValidator.MAX_RETRIES:
                    break
                continue

            success, victim, reason, errors = GMOutputValidator.validate_schrodinger_judgment(out_text)
            if success:
                print(f"[Agent] [BEATRICE] Judgment validated (attempt {attempt + 1}): {victim}")
                final_victim = victim
                final_reason = reason
                break

            print(
                f"[Agent] [BEATRICE] Judgment format error (attempt {attempt + 1}/{max_attempts}): "
                f"{'; '.join(errors)}"
            )

            if attempt < GMOutputValidator.MAX_RETRIES:
                correction_template = self.prompt_loader.load("correction")
                current_prompt = GMOutputValidator.build_correction_prompt(text, errors, out_text, template=correction_template)
            else:
                break

        out_text = f"<judgment>kill: {final_victim}</judgment>\n<reason>{final_reason}</reason>"
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
        """AI 模式下：消费 user_input_queue，运行 User Session，解析、审查、预解析后发送 action。"""
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
                buffer_text = msg.get("buffer_text", "")
                print(f"[Agent] [USER] Input ({msg_id}): {text[:120]}...")

                success = False
                current_prompt = text
                for attempt in range(2):  # 最多 2 次尝试（原始 + 1 次重试）
                    try:
                        out_text, _, _ = await self.user.run_once(current_prompt)
                    except Exception as e:
                        print(f"[Agent] [USER] Error (attempt {attempt + 1}): {e}")
                        traceback.print_exc()
                        break

                    print(f"[Agent] [USER] Output ({msg_id}) attempt {attempt + 1}: {out_text[:120]}...")

                    # 1. 解析结构化输出
                    parsed = self._parse_player_output(out_text)
                    if not parsed["is_valid"]:
                        print(f"[Agent] [USER] 格式错误: {parsed['error_msg']}")
                        current_prompt = (
                            f"{text}\n\n"
                            f"【格式错误】{parsed['error_msg']}\n"
                            f"请修正输出格式，确保包含 $action 或 $sound。"
                        )
                        continue

                    # 2. GM 合规审查
                    approved, reason, action_package = await self._gm_review(buffer_text, parsed)
                    if not approved:
                        print(f"[Agent] [USER] GM 拒绝: {reason}")
                        current_prompt = (
                            f"{text}\n\n"
                            f"【GM 审查未通过】{reason}\n"
                            f"请根据反馈修正你的行动，确保不泄露核心秘密、符合角色设定。"
                        )
                        continue

                    # 3. 前置预解析
                    pre_ok, pre_err = await self._pre_parse(action_package)
                    if not pre_ok:
                        print(f"[Agent] [USER] 预解析失败: {pre_err}")
                        current_prompt = (
                            f"{text}\n\n"
                            f"【行动解析失败】{pre_err}\n"
                            f"请修正你的行动描述，确保目标地点/物品/角色名正确。"
                        )
                        continue

                    # 全部通过，清空 buffer 并发送标准化 action
                    self.hibernation_buffer.clear()
                    parts = []
                    if action_package.get("speech"):
                        parts.append(f'"{action_package["speech"]}"')
                    if action_package.get("action_text"):
                        parts.append(action_package["action_text"])
                    if action_package.get("move_target"):
                        parts.append(f'下轮移动：{action_package["move_target"]}')
                    standardized = "\n".join(parts)
                    await self._send_action(msg_id, standardized or "...（沉默）")
                    self.is_hibernating = True
                    success = True
                    break

                if not success and msg_id.startswith("turn_"):
                    fallback = f"...（{self.role_dir.name}环顾四周，陷入沉思）"
                    await self._send_action(msg_id, fallback)
                    self.hibernation_buffer.clear()
                    self.is_hibernating = True
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
        if self.mode in ("auto", "beatrice") and self.user:
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
