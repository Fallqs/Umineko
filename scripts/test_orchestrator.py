#!/usr/bin/env python3
"""
《海猫鸣泣之时：六轩岛黄昏》全自动测试 Orchestrator

无需人类玩家，所有角色由 AI agent 驱动。
使用 agent_wrapper.py 作为角色进程后端。

用法:
    python test_orchestrator.py [--root-dir ..] [--mock]
"""

import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

PHASES = ["MORNING", "INVESTIGATION", "TWILIGHT", "MIDNIGHT"]

# 玩家席位 → 角色链（死亡后按顺序切换）
SEAT_CHAINS = {
    "P1": ["右代宫战人"],  # 战人不会死
    "P2": ["右代宫朱志香", "右代宫夏妃", "右代宫藏臼"],
    "P3": ["右代宫让治", "右代宫雾江", "右代宫留弗夫"],
    "P4": ["右代宫真里亚", "右代宫楼座"],
    "P5": ["嘉音", "乡田"],
    "P6": ["纱音", "熊泽"],
    "P7": ["右代宫秀吉", "南条医师"],
    "NPC1": ["贝阿朵莉切"],
}

# 角色目录映射
ROLE_DIRS = {
    "右代宫战人": "roles/右代宫战人",
    "右代宫朱志香": "roles/右代宫朱志香",
    "右代宫夏妃": "roles/右代宫夏妃",
    "右代宫藏臼": "roles/右代宫藏臼",
    "右代宫让治": "roles/右代宫让治",
    "右代宫雾江": "roles/右代宫雾江",
    "右代宫留弗夫": "roles/右代宫留弗夫",
    "右代宫真里亚": "roles/右代宫真里亚",
    "右代宫楼座": "roles/右代宫楼座",
    "嘉音": "roles/嘉音",
    "乡田": "roles/乡田",
    "纱音": "roles/纱音",
    "熊泽": "roles/熊泽",
    "右代宫秀吉": "roles/右代宫秀吉",
    "南条医师": "roles/南条医师",
    "贝阿朵莉切": "roles/贝阿朵莉切",
}

# 预定死亡表: (day, phase, 角色名, 死因)
DEATH_SCHEDULE: List[Tuple[int, str, str, str]] = [
    (2, "TWILIGHT", "右代宫秀吉", "在别馆被发现身亡，胸口有猎枪弹孔"),
    (3, "TWILIGHT", "右代宫朱志香", "在客房内被发现，额头有枪伤"),
    (4, "TWILIGHT", "右代宫让治", "在餐厅中毒身亡"),
    (4, "TWILIGHT", "南条医师", "在书房被发现，死因不明"),
    (5, "TWILIGHT", "右代宫真里亚", "在玫瑰园失踪后被发现身亡"),
    (5, "TWILIGHT", "右代宫夏妃", "在本馆走廊被发现，身上有刀伤"),
    (6, "TWILIGHT", "嘉音", "在别馆厨房被发现，中毒身亡"),
    (6, "TWILIGHT", "纱音", "在客房内被发现，窒息身亡"),
    (6, "TWILIGHT", "右代宫雾江", "在庭院被发现，身上有枪伤"),
    (7, "TWILIGHT", "右代宫藏臼", "在地下密室被发现身亡"),
    (7, "TWILIGHT", "右代宫留弗夫", "在港口被发现，溺亡"),
    (7, "TWILIGHT", "右代宫楼座", "在神社附近被发现身亡"),
    (7, "TWILIGHT", "乡田", "在餐厅被发现，中毒身亡"),
    (7, "TWILIGHT", "熊泽", "在本馆被发现，死因不明"),
]

# 场景描述模板
SCENE_TEMPLATES = {
    "MORNING": """【第{day}天 - 清晨】
晨曦透过厚重的窗帘洒入六轩岛的本馆。你醒来后，发现岛上笼罩着一层诡异的寂静。
{deaths}
{context}

今天是第{day}天，你目前在{location}。
请描述你此刻的行动和心情。你可以选择：
- 去某个地点调查
- 与其他角色交谈
- 独自思考/整理线索
- 使用 send-msg 工具与其他人交流
""",
    "INVESTIGATION": """【第{day}天 - 调查时间】
{deaths}
{context}

自由调查时间。你可以：
- 探索岛上的各个地点
- 与其他角色组队或单独行动
- 搜索可疑的线索
- 使用工具读写文件记录发现

请注意：嘉音和纱音不能同时出现在同一个调查小组中（薛定谔规则）。
""",
    "TWILIGHT": """【第{day}天 - 黄昏推理】
黄昏降临，所有存活者聚集在餐厅。
{deaths}
{context}

请分享你今天的发现和推理。你可以：
- 提出对事件的假设
- 质疑其他人的证词
- 出示你找到的线索
- 投票表决（如果进入表决阶段）
""",
    "MIDNIGHT": """【第{day}天 - 深夜】
夜色深沉，六轩岛被暴风雨包围。
{deaths}
{context}

深夜时段。你可以：
- 私下与其他角色密谈（使用密谈工具）
- 独自调查
- 休息并整理今日的发现
- 写下日记或笔记

明天将是第{next_day}天...
""",
}

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _write_pipe(pipe_path: Path, text: str, msg_id: Optional[str] = None) -> str:
    pipe_path.parent.mkdir(parents=True, exist_ok=True)
    msg_id = msg_id or f"msg_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
    record = {"type": "input", "text": text, "id": msg_id}
    with open(pipe_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return msg_id


def _write_output(out_path: Path, msg: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")


def _read_output(out_path: Path, last_pos: int, timeout: float = 120.0) -> Tuple[Optional[dict], int]:
    """等待并读取输出，直到收到 status=idle 或超时"""
    start = time.time()
    while time.time() - start < timeout:
        if not out_path.exists():
            time.sleep(0.5)
            continue
        current_size = out_path.stat().st_size
        if current_size <= last_pos:
            time.sleep(0.5)
            continue
        with open(out_path, "r", encoding="utf-8") as f:
            f.seek(last_pos)
            new_content = f.read()
            new_pos = f.tell()
        for line in new_content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "status" and msg.get("phase") == "idle":
                    return msg, new_pos
            except json.JSONDecodeError:
                continue
        last_pos = new_pos
    return None, last_pos


def _read_all_output(out_path: Path, last_pos: int) -> Tuple[List[dict], int]:
    if not out_path.exists():
        return [], last_pos
    current_size = out_path.stat().st_size
    if current_size <= last_pos:
        return [], last_pos
    with open(out_path, "r", encoding="utf-8") as f:
        f.seek(last_pos)
        new_content = f.read()
        new_pos = f.tell()
    messages = []
    for line in new_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return messages, new_pos


# ---------------------------------------------------------------------------
# 角色进程管理
# ---------------------------------------------------------------------------

@dataclass
class RoleProcess:
    seat_id: str
    role_name: str
    work_dir: Path
    pipe_path: Path
    out_path: Path
    session_id: str
    process: Optional[subprocess.Popen] = None
    last_out_pos: int = 0
    alive: bool = True
    chain_index: int = 0


class TestOrchestrator:
    def __init__(self, root_dir: Path, mock_mode: bool = False, python_exe: str = "python"):
        self.root_dir = root_dir.resolve()
        self.mock_mode = mock_mode
        # Normalize python executable path for Windows
        self.python_exe = self._normalize_python_path(python_exe)
        self.inbox_dir = self.root_dir / "shared" / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

        self.processes: Dict[str, RoleProcess] = {}  # seat_id -> RoleProcess
        self.alive_seats: Set[str] = set()
        self.dead_roles: Set[str] = set()
        self.day = 1
        self.phase_index = 0  # 0=MORNING, 1=INVESTIGATION, 2=TWILIGHT, 3=MIDNIGHT
        self.turn_counter = 0
        self.narrative_log: List[str] = []
        self.router_process: Optional[subprocess.Popen] = None

    @staticmethod
    def _normalize_python_path(path: str) -> str:
        r"""Convert Git Bash /c/... paths to Windows C:\... paths."""
        if len(path) >= 3 and path[0] == "/" and path[2] == "/":
            drive = path[1].upper()
            rest = path[3:]
            return f"{drive}:\\{rest.replace('/', '\\')}"
        return path

    def _get_phase(self) -> str:
        return PHASES[self.phase_index]

    def _get_agent_wrapper_path(self) -> Path:
        return (self.root_dir / "scripts" / "agent_wrapper.py").resolve()

    def _get_role_dir(self, role_name: str) -> Path:
        rel = ROLE_DIRS.get(role_name, f"roles/{role_name}")
        return (self.root_dir / rel).resolve()

    def _get_pipe_path(self, seat_id: str) -> Path:
        return (self.inbox_dir / seat_id / "agent_pipe.jsonl").resolve()

    def start_router(self) -> None:
        router_script = (self.root_dir / "scripts" / "router.py").resolve()
        if not router_script.exists():
            print(f"[Orchestrator] Warning: router.py not found at {router_script}")
            return
        cmd = [
            self.python_exe,
            str(router_script),
            "--mode", "local",
            "--inbox-dir", str(self.inbox_dir),
        ]
        print(f"[Orchestrator] Starting router: {' '.join(cmd)}")
        self.router_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        time.sleep(1)

    def stop_router(self) -> None:
        if self.router_process:
            print("[Orchestrator] Stopping router...")
            self.router_process.terminate()
            try:
                self.router_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.router_process.kill()
            self.router_process = None

    def start_role(self, seat_id: str, role_name: str, chain_index: int = 0) -> Optional[RoleProcess]:
        work_dir = self._get_role_dir(role_name)
        pipe_path = self._get_pipe_path(seat_id)
        out_path = Path(str(pipe_path) + ".out")
        session_id = f"{seat_id}_{role_name.replace('/', '_')}"

        # Clear old out file
        if out_path.exists():
            out_path.unlink()

        wrapper = self._get_agent_wrapper_path()
        if not wrapper.exists():
            print(f"[Orchestrator] ERROR: agent_wrapper.py not found at {wrapper}")
            return None

        cmd = [
            self.python_exe,
            str(wrapper),
            "--work-dir", str(work_dir),
            "--pipe", str(pipe_path),
            "--session", session_id,
            "--yolo",
        ]
        if self.mock_mode:
            print(f"[Orchestrator] [MOCK] Would start: {' '.join(cmd)}")
            proc = None
        else:
            print(f"[Orchestrator] Starting {seat_id} -> {role_name}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )

        rp = RoleProcess(
            seat_id=seat_id,
            role_name=role_name,
            work_dir=work_dir,
            pipe_path=pipe_path,
            out_path=out_path,
            session_id=session_id,
            process=proc,
            chain_index=chain_index,
            alive=True,
        )
        self.processes[seat_id] = rp
        self.alive_seats.add(seat_id)
        return rp

    def stop_role(self, seat_id: str) -> None:
        rp = self.processes.get(seat_id)
        if not rp:
            return
        print(f"[Orchestrator] Stopping {seat_id} ({rp.role_name})")
        rp.alive = False
        if rp.process:
            rp.process.terminate()
            try:
                rp.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rp.process.kill()
        self.alive_seats.discard(seat_id)

    def switch_role(self, seat_id: str) -> Optional[RoleProcess]:
        """为指定席位切换到下一个角色。如果无可用角色则返回 None。"""
        rp = self.processes.get(seat_id)
        if not rp:
            return None

        chain = SEAT_CHAINS.get(seat_id, [])
        next_index = rp.chain_index + 1
        if next_index >= len(chain):
            print(f"[Orchestrator] {seat_id} 没有更多角色可切换，已出局")
            self.stop_role(seat_id)
            return None

        new_role = chain[next_index]
        print(f"[Orchestrator] {seat_id} 切换角色: {rp.role_name} -> {new_role}")
        self.stop_role(seat_id)
        new_rp = self.start_role(seat_id, new_role, chain_index=next_index)
        return new_rp

    def send_to_role(self, seat_id: str, text: str) -> str:
        rp = self.processes.get(seat_id)
        if not rp or not rp.alive:
            raise RuntimeError(f"Role {seat_id} is not alive")
        msg_id = _write_pipe(rp.pipe_path, text)
        return msg_id

    def wait_for_role(self, seat_id: str, timeout: float = 300.0) -> Optional[str]:
        """等待角色处理完成，返回输出文本"""
        rp = self.processes.get(seat_id)
        if not rp or not rp.alive:
            return None

        if self.mock_mode:
            # Mock 回复
            time.sleep(0.5)
            mock_text = f"[Mock] {rp.role_name} 收到了消息并做出了回应。"
            _write_output(rp.out_path, {
                "type": "output",
                "text": mock_text,
                "tools": [],
                "id": "mock",
            })
            _write_output(rp.out_path, {
                "type": "status",
                "phase": "idle",
                "id": "mock",
            })

        start_pos = rp.last_out_pos
        status_msg, new_pos = _read_output(rp.out_path, rp.last_out_pos, timeout=timeout)
        rp.last_out_pos = new_pos

        if status_msg is None:
            print(f"[Orchestrator] WARNING: {seat_id} ({rp.role_name}) timed out after {timeout}s")
            return None

        # Read all output messages since last check (from start_pos to new_pos)
        messages, rp.last_out_pos = _read_all_output(rp.out_path, start_pos)
        output_texts = []
        for m in messages:
            if m.get("type") == "output":
                output_texts.append(m.get("text", ""))
        return "\n".join(output_texts) if output_texts else "(无输出)"

    def broadcast(self, text: str, exclude: Optional[Set[str]] = None) -> None:
        exclude = exclude or set()
        for seat_id in sorted(self.alive_seats):
            if seat_id in exclude:
                continue
            try:
                self.send_to_role(seat_id, text)
            except Exception as e:
                print(f"[Orchestrator] Failed to send to {seat_id}: {e}")

    def collect_responses(self, timeout_per_role: float = 300.0) -> Dict[str, str]:
        """收集所有存活角色的回复"""
        responses = {}
        for seat_id in sorted(self.alive_seats):
            text = self.wait_for_role(seat_id, timeout=timeout_per_role)
            if text is not None:
                responses[seat_id] = text
                rp = self.processes[seat_id]
                print(f"[Orchestrator] {seat_id} ({rp.role_name}): {text[:100]}...")
            else:
                rp = self.processes[seat_id]
                print(f"[Orchestrator] {seat_id} ({rp.role_name}): TIMEOUT")
        return responses

    def check_deaths(self) -> List[Tuple[str, str]]:
        """检查当前阶段是否有预定死亡，返回 (seat_id, cause) 列表"""
        phase = self._get_phase()
        deaths = []
        for day, death_phase, role_name, cause in DEATH_SCHEDULE:
            if day == self.day and death_phase == phase:
                if role_name not in self.dead_roles:
                    deaths.append((role_name, cause))
        return deaths

    def handle_deaths(self, deaths: List[Tuple[str, str]]) -> None:
        for role_name, cause in deaths:
            self.dead_roles.add(role_name)
            # Find which seat owns this role
            seat_id = None
            for sid, rp in self.processes.items():
                if rp.role_name == role_name and rp.alive:
                    seat_id = sid
                    break
            if seat_id is None:
                continue

            rp = self.processes[seat_id]
            print(f"\n[Orchestrator] ☠️ {role_name} ({seat_id}) 死亡: {cause}\n")
            self.narrative_log.append(f"Day{self.day} {self._get_phase()}: {role_name} 死亡 - {cause}")

            # Broadcast death to all alive roles
            death_announcement = f"【紧急】{role_name} 被发现死亡！{cause}"
            self.broadcast(death_announcement)

            # Wait a moment for agents to process
            time.sleep(2)

            # Switch role if possible
            new_rp = self.switch_role(seat_id)
            if new_rp:
                # Send context to new role
                context = self._build_game_context()
                switch_msg = f"""【角色切换】
你之前控制的角色 {role_name} 已死亡。
现在你接管了 {new_rp.role_name} 的视角。

{context}

请继续参与游戏。"""
                self.send_to_role(seat_id, switch_msg)
                # Wait for new role to respond
                resp = self.wait_for_role(seat_id, timeout=60)
                if resp:
                    print(f"[Orchestrator] {seat_id} ({new_rp.role_name}) switch response: {resp[:80]}...")

    def _build_game_context(self) -> str:
        alive_roles = [self.processes[s].role_name for s in self.alive_seats]
        dead_list = ", ".join(sorted(self.dead_roles)) if self.dead_roles else "无"
        return f"""当前游戏状态:
- 第 {self.day} 天，{self._get_phase()}
- 存活角色: {', '.join(alive_roles)}
- 已死亡: {dead_list}
- 你已参与的回合数: {self.turn_counter}"""

    def _build_scene_prompt(self) -> str:
        phase = self._get_phase()
        deaths = self.check_deaths()
        death_text = ""
        if deaths:
            death_text = "\n".join([f"☠️ {r} 死亡: {c}" for r, c in deaths])
        else:
            death_text = "（今日尚未发现死亡）"

        template = SCENE_TEMPLATES.get(phase, SCENE_TEMPLATES["MORNING"])
        location = "本馆"  # Simplified
        return template.format(
            day=self.day,
            phase=phase,
            deaths=death_text,
            context=self._build_game_context(),
            location=location,
            next_day=self.day + 1,
        )

    def run_phase(self) -> None:
        phase = self._get_phase()
        print(f"\n{'='*60}")
        print(f"  Day {self.day} - {phase}")
        print(f"{'='*60}\n")

        # 1. Build and broadcast scene
        scene_prompt = self._build_scene_prompt()
        self.narrative_log.append(f"Day{self.day} {phase}: 场景开始")
        print(f"[Orchestrator] Broadcasting scene to {len(self.alive_seats)} alive roles...")
        self.broadcast(scene_prompt)

        # 2. Collect initial responses
        print(f"[Orchestrator] Collecting responses...")
        responses = self.collect_responses(timeout_per_role=300.0)
        for sid, text in responses.items():
            rp = self.processes[sid]
            self.narrative_log.append(f"Day{self.day} {phase} {rp.role_name}: {text[:200]}")

        # 3. Handle deaths
        deaths = self.check_deaths()
        if deaths:
            self.handle_deaths(deaths)

        # 4. Free interaction round (optional)
        if phase in ("INVESTIGATION", "TWILIGHT") and len(self.alive_seats) > 1:
            interaction_prompt = """【互动回合】
你可以对特定角色发起对话或行动。
请使用 send-msg 工具与其他角色交流，或直接描述你的行动。"""
            self.broadcast(interaction_prompt)
            responses2 = self.collect_responses(timeout_per_role=180.0)
            for sid, text in responses2.items():
                rp = self.processes[sid]
                self.narrative_log.append(f"Day{self.day} {phase} {rp.role_name} interaction: {text[:200]}")

        self.turn_counter += 1

    def run_day(self) -> None:
        print(f"\n{'#'*60}")
        print(f"#  START OF DAY {self.day}")
        print(f"{'#'*60}")
        for i, phase in enumerate(PHASES):
            self.phase_index = i
            if not self.alive_seats:
                print("[Orchestrator] No alive seats remaining. Ending game.")
                return
            self.run_phase()
            time.sleep(1)

    def run(self, max_day: int = 7) -> None:
        print("="*60)
        print("《海猫鸣泣之时：六轩岛黄昏》全自动测试")
        print("="*60)

        # 1. Start router
        self.start_router()

        # 2. Start initial roles
        print("\n[Orchestrator] Starting initial roles...")
        for seat_id, chain in SEAT_CHAINS.items():
            if chain:
                self.start_role(seat_id, chain[0], chain_index=0)
                time.sleep(0.5)

        print(f"\n[Orchestrator] Started {len(self.processes)} roles")

        # 3. Wait for processes to initialize
        time.sleep(3)

        try:
            # 4. Run up to max_day days
            for day in range(1, max_day + 1):
                self.day = day
                self.run_day()
                if not self.alive_seats:
                    break

            print("\n" + "="*60)
            print("游戏结束")
            print("="*60)
            print(f"\n存活角色: {[self.processes[s].role_name for s in self.alive_seats]}")
            print(f"死亡角色: {sorted(self.dead_roles)}")
            print(f"\n叙事日志 ({len(self.narrative_log)} 条):")
            for entry in self.narrative_log[-20:]:
                print(f"  {entry}")

        except KeyboardInterrupt:
            print("\n[Orchestrator] Interrupted by user")
        finally:
            # Cleanup
            print("\n[Orchestrator] Cleaning up...")
            for seat_id in list(self.processes.keys()):
                self.stop_role(seat_id)
            self.stop_router()
            print("[Orchestrator] Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Umineko全自动测试Orchestrator")
    parser.add_argument("--root-dir", type=Path, default=None, help="项目根目录")
    parser.add_argument("--mock", action="store_true", help="Mock模式（不启动真实AI进程）")
    parser.add_argument("--python", type=str, default="python", help="Python可执行文件路径")
    parser.add_argument("--max-day", type=int, default=7, help="最大运行天数（默认7）")
    args = parser.parse_args()

    if args.root_dir is None:
        # Auto-detect: this script is in <root>/scripts/
        root_dir = Path(__file__).resolve().parent.parent
    else:
        root_dir = args.root_dir.resolve()

    print(f"[Orchestrator] Root dir: {root_dir}")
    print(f"[Orchestrator] Mock mode: {args.mock}")
    print(f"[Orchestrator] Max day: {args.max_day}")

    orch = TestOrchestrator(root_dir, mock_mode=args.mock, python_exe=args.python)
    orch.run(max_day=args.max_day)


if __name__ == "__main__":
    main()
