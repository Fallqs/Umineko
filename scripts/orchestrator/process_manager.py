"""
《海猫鸣泣之时：六轩岛黄昏》子进程管理器

管理 Router 和所有 Seat/NPC 子进程的启停，不感知游戏逻辑。
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

from .network import NetworkLayer


class ProcessManager:
    def __init__(self, root_dir: Path, python_exe: str, network: NetworkLayer):
        self.root_dir = Path(root_dir).resolve()
        self.python_exe = python_exe
        self.network = network
        self.router_process: Optional[subprocess.Popen] = None
        self._subprocesses: Dict[str, subprocess.Popen] = {}

    def start_router(self, inbox_dir: Path) -> None:
        router_script = self.root_dir / "scripts" / "router.py"
        if not router_script.exists():
            print(f"[ProcessManager] Warning: router.py not found at {router_script}")
            return
        inbox_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.python_exe,
            str(router_script),
            "--mode", "local",
            "--inbox-dir", str(inbox_dir),
        ]
        print(f"[ProcessManager] Starting router: {' '.join(cmd)}")
        self.router_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )

    def stop_router(self) -> None:
        if self.router_process:
            print("[ProcessManager] Stopping router...")
            self.router_process.terminate()
            try:
                self.router_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.router_process.kill()
            self.router_process = None

    def _normalize_python_path(self, path: str) -> str:
        if len(path) >= 3 and path[0] == "/" and path[2] == "/":
            drive = path[1].upper()
            rest = path[3:]
            return f"{drive}:\\{rest.replace('/', '\\')}"
        return path

    def start_seat(self, seat_id: str, role_name: str, agent_mode: str, host: str, port: int) -> None:
        role_dir = self.root_dir / "roles" / role_name
        wrapper = self.root_dir / "scripts" / "agent_wrapper.py"
        if not wrapper.exists():
            print(f"[ProcessManager] ERROR: agent_wrapper.py not found at {wrapper}")
            return
        cmd = [
            self._normalize_python_path(self.python_exe),
            "-u",
            str(wrapper),
            "--work-dir", str(role_dir),
            "--seat-id", seat_id,
            "--orchestrator-host", host,
            "--orchestrator-port", str(port),
            "--mode", agent_mode,
            "--yolo",
        ]
        log_file = self.root_dir / "shared" / "logs" / f"{seat_id}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"[ProcessManager] Starting {seat_id} ({agent_mode}) -> {role_name}, log={log_file}")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            cmd,
            stdout=open(log_file, "w", encoding="utf-8", buffering=1),
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            close_fds=True,
            env=env,
        )
        self._subprocesses[seat_id] = proc

    def start_npc(self, role_name: str, host: str, port: int) -> None:
        """启动NPC进程，seat_id格式为 NPC_{角色名}。"""
        seat_id = f"NPC_{role_name}"
        self.start_seat(seat_id, role_name, "auto", host, port)

    def terminate(self, seat_id: str) -> None:
        proc = self._subprocesses.pop(seat_id, None)
        if proc and proc.poll() is None:
            print(f"[ProcessManager] Terminating subprocess for {seat_id}")
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)
        seat = self.network.seats.get(seat_id)
        if seat:
            seat.alive = False
            try:
                seat.writer.close()
            except Exception:
                pass

    def terminate_all(self) -> None:
        for seat_id in list(self._subprocesses.keys()):
            self.terminate(seat_id)
        self.stop_router()
