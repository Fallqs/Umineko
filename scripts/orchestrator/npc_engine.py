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
        self._launched_npc_roles: Set[str] = set()

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
        """返回当前应由NPC控制的角色。排除已被任何seat控制的角色。"""
        all_roles = self.get_all_playable_roles()
        # 已被任何 seat（玩家或BEATRICE）控制的角色
        controlled_roles = set(self.state.role_controller.keys())
        npc_roles = all_roles - controlled_roles - self.state.dead_roles
        return npc_roles

    def start_all_npcs(self, host: str, port: int) -> None:
        """启动所有未被玩家控制的角色的NPC进程。"""
        npc_roles = self.get_npc_roles()
        self._launched_npc_roles = set()
        for role in npc_roles:
            if role in self.state.dead_roles:
                continue
            seat_id = f"NPC_{role}"
            if seat_id not in self.state.role_controller:
                self.state.role_controller[role] = seat_id
                self.state.alive_roles.add(role)
                if role not in self.state.action_points:
                    self.state.action_points[role] = 50
                self.pm.start_npc(role, host, port)
                self._launched_npc_roles.add(role)
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
