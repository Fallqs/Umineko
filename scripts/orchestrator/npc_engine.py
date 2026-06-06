"""
《海猫鸣泣之时：六轩岛黄昏》NPC引擎

管理NPC进程的启动、回收、状态转移。
"""

from typing import Optional, Set

from .config_loader import ConfigLoader
from .process_manager import ProcessManager
from .state import GameState


class NPCEngine:
    def __init__(self, game_state: GameState, process_manager: ProcessManager, config: Optional[ConfigLoader] = None):
        self.state = game_state
        self.pm = process_manager
        self.config = config

    def _get_chains(self) -> dict:
        if self.config:
            return self.config.seat_chains
        return {}

    def get_all_playable_roles(self) -> Set[str]:
        """返回所有可扮演角色。"""
        roles = set()
        for chain in self._get_chains().values():
            roles.update(chain)
        # 添加独立NPC角色
        roles.add("右代宫金藏")
        roles.add("贝阿朵莉切")
        return roles

    def get_npc_roles(self) -> Set[str]:
        """返回当前应由NPC控制的角色。"""
        all_roles = self.get_all_playable_roles()
        player_roles = set()
        for seat_id, chain in self._get_chains().items():
            if chain:
                player_roles.add(chain[0])  # 当前玩家控制的角色
        npc_roles = all_roles - player_roles - self.state.dead_roles
        return npc_roles

    def start_all_npcs(self, host: str, port: int) -> None:
        """启动所有未被玩家控制的角色的NPC进程。"""
        npc_roles = self.get_npc_roles()
        for role in npc_roles:
            if role in self.state.dead_roles:
                continue
            seat_id = f"NPC_{role}"
            if seat_id not in self.state.role_controller:
                self.state.role_controller[role] = seat_id
                self.state.alive_roles.add(role)
                if role not in self.state.action_points:
                    self.state.action_points[role] = 50
                # 设置初始位置
                # 注意：这里需要ConfigLoader，但为了避免循环依赖，
                # 初始位置在Orchestrator初始化时统一设置
                self.pm.start_npc(role, host, port)
                print(f"[NPCEngine] 启动NPC: {role} -> {seat_id}")

    def terminate_npc(self, role_name: str) -> None:
        seat_id = f"NPC_{role_name}"
        self.pm.terminate(seat_id)
        self.state.role_controller.pop(role_name, None)
        print(f"[NPCEngine] 终止NPC: {role_name}")

    def prepare_role_for_player(self, role_name: str, player_seat_id: str) -> None:
        """玩家切换角色前：回收NPC，准备状态。"""
        old_controller = self.state.role_controller.get(role_name)
        if old_controller and old_controller.startswith("NPC_"):
            self.pm.terminate(old_controller)
            self.state.role_controller.pop(role_name, None)
            print(f"[NPCEngine] 回收NPC角色: {role_name} (原控制者: {old_controller})")
        self.state.role_controller[role_name] = player_seat_id
