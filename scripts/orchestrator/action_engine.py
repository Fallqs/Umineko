"""
《海猫鸣泣之时：六轩岛黄昏》行动引擎

行动解析、调查、发言广播、信息解锁。
"""

import re
from dataclasses import dataclass
from typing import Optional

from .config_loader import ConfigLoader
from .network import NetworkLayer, SeatConnection
from .state import GameState


@dataclass
class ParsedAction:
    investigate: bool = False
    speech: str = ""
    skip: bool = False
    next_move: Optional[str] = None
    duel_beatrice: bool = False
    # 物品相关（Phase B）
    pickup: bool = False              # 拾取地点物品
    gift_target: Optional[str] = None # 赠送目标角色
    gift_item: Optional[str] = None   # 赠送物品（item_id 或名称片段）
    # 玩家互动（Phase C）
    investigate_target: Optional[str] = None  # 调查特定玩家
    search_target: Optional[str] = None       # 搜身目标
    comfort_target: Optional[str] = None      # 安慰目标
    shoot_target: Optional[str] = None        # 射击目标
    threaten_target: Optional[str] = None     # 威胁目标
    autopsy: bool = False                     # 验尸


class ActionEngine:
    def __init__(self, game_state: GameState, config: ConfigLoader, network: NetworkLayer):
        self.state = game_state
        self.config = config
        self.network = network

    def parse(self, text: str, nearby_roles: Optional[list[str]] = None) -> ParsedAction:
        result = ParsedAction()
        if not text:
            result.skip = True
            return result

        nearby = nearby_roles or []
        # 构建角色名匹配正则
        role_pattern = "|".join(re.escape(r) for r in nearby) if nearby else ""

        # 调查（先检查是否针对特定玩家，否则为场景调查）
        if any(k in text for k in ["调查", "搜索", "查看", "检查", "探索", "搜寻"]):
            if role_pattern:
                # 检查是否调查特定玩家
                target_match = re.search(
                    rf"(?:调查|观察|查看|检查)\s*(?:一下?)?\s*({role_pattern})", text
                )
                if target_match:
                    result.investigate_target = target_match.group(1).strip()
                else:
                    result.investigate = True
            else:
                result.investigate = True

        # 搜身
        if role_pattern and any(k in text for k in ["搜身", "搜", "检查口袋", "翻口袋"]):
            search_match = re.search(
                rf"(?:搜身|搜索|检查口袋|翻口袋)\s*(?:一下?)?\s*({role_pattern})", text
            )
            if search_match:
                result.search_target = search_match.group(1).strip()

        # 安慰
        if role_pattern and any(k in text for k in ["安慰", "抚慰", "鼓励", "拍拍"]):
            comfort_match = re.search(
                rf"(?:安慰|抚慰|鼓励|拍拍)\s*(?:一下?)?\s*({role_pattern})", text
            )
            if comfort_match:
                result.comfort_target = comfort_match.group(1).strip()

        # 开枪/射击
        if role_pattern and any(k in text for k in ["开枪", "射击", "射杀", "击毙"]):
            shoot_match = re.search(
                rf"(?:向|对)?\s*({role_pattern})\s*(?:开枪|射击|射杀|击毙)", text
            )
            if not shoot_match:
                shoot_match = re.search(
                    rf"(?:开枪|射击|射杀|击毙)\s*(?:向|对)?\s*({role_pattern})", text
                )
            if shoot_match:
                result.shoot_target = shoot_match.group(1).strip()

        # 威胁/用武器指着（不消耗弹药，但可见性同射击）
        if role_pattern and any(k in text for k in ["威胁", "指着", "用枪指着", "举枪"]):
            threaten_match = re.search(
                rf"(?:威胁|指着|用枪指着|举枪)\s*(?:向|对)?\s*({role_pattern})", text
            )
            if not threaten_match:
                threaten_match = re.search(
                    rf"(?:向|对)?\s*({role_pattern})\s*(?:威胁|指着|用枪指着|举枪)", text
                )
            if threaten_match:
                result.threaten_target = threaten_match.group(1).strip()

        # 验尸
        if any(k in text for k in ["验尸", "检查尸体", "尸检", "查看尸体"]):
            result.autopsy = True

        # 拾取物品
        if any(k in text for k in ["捡起", "拾取", "拿取", "带走", "拿起来"]):
            result.pickup = True

        # 赠送物品——解析具体物品和目标（"把X给Y" 或 "给Y X"）
        gift_match = re.search(r"(?:把|将)\s*(.+?)\s*(?:给|交给|赠送)\s*(\S+)", text)
        if gift_match:
            result.gift_item = gift_match.group(1).strip()
            result.gift_target = gift_match.group(2).strip()
        else:
            gift_match2 = re.search(r"(?:给|交给|赠送)\s*(\S+)\s*(.+?)", text)
            if gift_match2:
                result.gift_target = gift_match2.group(1).strip()
                result.gift_item = gift_match2.group(2).strip()

        # 跳过
        if "跳过" in text or "不行动" in text or text.lower().strip() == "pass":
            result.skip = True

        # 决斗
        if "决斗" in text and "贝阿朵" in text:
            result.duel_beatrice = True

        # 移动意向
        m = re.search(r"下轮移动[：:]\s*(\S+)", text)
        if m:
            result.next_move = m.group(1).strip()

        # 发言（提取引号内容）
        speeches = re.findall(r'["""]([^"""]+)["""]', text)
        if speeches:
            result.speech = speeches[-1]
        elif not result.investigate and not result.skip and not result.duel_beatrice and not result.pickup:
            # 无引号时，取最后一行作为发言（排除纯物品操作）
            lines = [l for l in text.split("\n") if l.strip()]
            if lines:
                result.speech = lines[-1][:200]

        return result

    def _check_requires(self, role: str, requires: Optional[dict]) -> tuple[bool, str]:
        """检查角色是否满足信息条目的前置条件。

        Args:
            role: 角色名
            requires: 前置条件字典，可能为 None。支持的字段：
                - info_ids: List[str] — 需要已解锁的信息条目
                - items: List[str] — 需要持有的物品（Phase B 完整实现）
                - day_min: int — 最小游戏日
                - day_max: int — 最大游戏日
                - role: str — 仅限特定角色
                - time_slot: str — 仅限特定时间槽

        Returns:
            (是否满足, 不满足原因)
        """
        if not requires:
            return True, ""

        # 角色限制
        if "role" in requires and requires["role"] != role:
            return False, f"该线索仅限 {requires['role']} 发现"

        # 时间槽限制
        current_slot = getattr(self.state, "current_slot", "")
        if "time_slot" in requires and current_slot and requires["time_slot"] != current_slot:
            return False, f"该线索仅在 {requires['time_slot']} 时段可发现"

        # 游戏日范围
        if "day_min" in requires and self.state.day < requires["day_min"]:
            return False, f"该线索需第 {requires['day_min']} 天后才能发现"
        if "day_max" in requires and self.state.day > requires["day_max"]:
            return False, f"该线索仅能在第 {requires['day_max']} 天前发现"

        # 已解锁信息前置
        unlocked = self.state.unlocked_info.get(role, set())
        if "info_ids" in requires:
            missing = [iid for iid in requires["info_ids"] if iid not in unlocked]
            if missing:
                return False, f"需先解锁: {', '.join(missing)}"

        # 物品前置（预留接口，Phase B 完整实现 inventory 后自动生效）
        if "items" in requires:
            inventory = getattr(self.state, "inventory", {}).get(role, set())
            missing_items = [item for item in requires["items"] if item not in inventory]
            if missing_items:
                return False, f"需持有物品: {', '.join(missing_items)}"

        return True, ""

    async def execute_investigate(self, role: str, location: str, seat: SeatConnection) -> str:
        day = self.state.day
        infos = self.config.get_location_info(location, day)
        if not infos:
            return f"你仔细调查了{location}，但没有发现新的线索。"

        unlocked = self.state.unlocked_info.get(role, set())

        # 筛选：未解锁且满足前置条件的信息
        available_infos = []
        blocked_count = 0
        for iid, desc, requires in infos:
            if iid in unlocked:
                continue
            can_unlock, _reason = self._check_requires(role, requires)
            if can_unlock:
                available_infos.append((iid, desc))
            else:
                blocked_count += 1

        if not available_infos:
            if blocked_count > 0:
                # 有线索但因前置条件未满足而被锁定，返回模糊提示
                return f"你调查了{location}，隐约感觉有些秘密被什么遮蔽了，但一时无法触及..."
            return f"你再次调查了{location}，但没有新的发现。"

        iid, desc = available_infos[0]
        self.state.unlock_info(role, iid)
        points = self._get_info_points(iid)
        return f"【调查成功】你发现了新的线索！\n{iid}: {desc}\n（获得 {points} 分）"

    async def broadcast_speech(self, speaker_role: str, speech: str, location: str) -> None:
        if not speech:
            return
        body = f"【{speaker_role}】{speech}"
        for role, seat_id in self.state.role_controller.items():
            if self.state.locations.get(role) == location:
                seat = self.network.seats.get(seat_id)
                if seat and seat.alive:
                    await self.network.send_and_drain(seat, {
                        "type": "notification",
                        "title": "同场发言",
                        "body": body,
                        "location": location,
                    })

    async def broadcast_action_visibility(self, actor_role: str, action_desc: str, location: str, exclude_role: Optional[str] = None) -> None:
        """广播行为可见性：通知同地点其他角色有人正在做某事。

        Args:
            actor_role: 行动者角色名
            action_desc: 行为描述（如"正在仔细调查餐厅的每个角落"）
            location: 地点
            exclude_role: 排除的角色（通常是行动者本人，避免自己收到自己的行动通知）
        """
        body = f"{actor_role}{action_desc}"
        for role, seat_id in self.state.role_controller.items():
            if role == exclude_role:
                continue
            if self.state.locations.get(role) == location:
                seat = self.network.seats.get(seat_id)
                if seat and seat.alive:
                    await self.network.send_and_drain(seat, {
                        "type": "notification",
                        "title": "同场事件",
                        "body": body,
                        "location": location,
                    })

    def handle_move_intent(self, role: str, target: str) -> None:
        if target in self.config.locations:
            self.state.pending_moves[role] = target

    # ------------------------------------------------------------------
    # 物品操作（Phase B）
    # ------------------------------------------------------------------

    async def execute_pickup(self, role: str, location: str, seat: SeatConnection) -> str:
        """执行拾取：角色在当前地点拾取可用物品（优先第一个）。"""
        available = self.state.get_location_items(location, self.state.day)
        if not available:
            return f"你环顾{location}四周，没有找到可以带走的东西。"

        item_id = available[0]
        item = self.state.item_registry.get(item_id, {})
        item_name = item.get("name", "不明物品")

        self.state.add_item(role, item_id)
        desc = self.state.get_item_desc(item_id, gm_view=False)
        return f"【拾取】你获得了 {item_name}。\n{desc}"

    async def execute_gift(self, role: str, target_role: str, item_hint: str, seat: SeatConnection) -> str:
        """执行赠送物品。"""
        if target_role not in self.state.alive_roles:
            return f"{target_role} 不在这里或已死亡，无法赠送。"

        # 模糊匹配物品
        inventory = self.state.get_inventory(role)
        matched = None
        for item_id in inventory:
            item = self.state.item_registry.get(item_id, {})
            if item_hint == item_id or item_hint in item.get("name", ""):
                matched = item_id
                break

        if not matched:
            return f"你想赠送 '{item_hint}' 给 {target_role}，但背包中没有这件物品。"

        item = self.state.item_registry.get(matched, {})
        item_name = item.get("name", "不明物品")

        if self.state.transfer_item(role, target_role, matched):
            # 通知接收方
            target_seat_id = self.state.role_controller.get(target_role)
            target_seat = self.network.seats.get(target_seat_id) if target_seat_id else None
            if target_seat and target_seat.alive:
                await self.network.send_and_drain(target_seat, {
                    "type": "notification",
                    "title": "收到物品",
                    "body": f"【{role}】赠送给你 {item_name}。",
                    "severity": "info",
                })
            return f"【赠送】你将 {item_name} 交给了 {target_role}。"
        return "赠送失败。"

    # ------------------------------------------------------------------
    # 玩家互动操作（Phase C）
    # ------------------------------------------------------------------

    async def execute_investigate_target(self, role: str, target: str, seat: SeatConnection) -> str:
        """调查特定玩家，获取其状态摘要。"""
        if target not in self.state.alive_roles:
            return f"{target} 不在这里或已死亡。"
        target_loc = self.state.locations.get(target, "未知")
        target_ap = self.state.action_points.get(target, 0)
        has_items = len(self.state.get_inventory(target)) > 0
        item_hint = "似乎携带了什么东西" if has_items else "身上看起来空空如也"
        return (
            f"【观察 {target}】\n"
            f"位置：{target_loc}\n"
            f"状态：{item_hint}\n"
            f"精神：{'旺盛' if target_ap > 10 else '一般' if target_ap > 5 else '低迷'}"
        )

    async def execute_search(self, role: str, target: str, seat: SeatConnection) -> str:
        """搜身：60% 基础成功率。成功可查看目标背包。"""
        import random
        if target not in self.state.alive_roles:
            return f"{target} 不在这里或已死亡，无法搜身。"

        rules = self.config.game_rules if self.config else {}
        success = random.random() < rules.get("search_success_rate", 0.6)
        if not success:
            return f"你试图搜查 {target}，但被他/她察觉并避开了。"

        items = self.state.get_inventory(target)
        if items:
            item_names = [self.state.item_registry.get(iid, {}).get("name", iid) for iid in items]
            return f"【搜身成功】你从 {target} 身上发现了：{', '.join(item_names)}"
        return f"【搜身成功】你仔细搜查了 {target}，但没有发现任何东西。"

    async def execute_comfort(self, role: str, target: str, seat: SeatConnection) -> str:
        """安慰目标，赠送 2 行动点。"""
        if target not in self.state.alive_roles:
            return f"{target} 不在这里或已死亡。"
        comfort_restore = (self.config.game_rules.get("comfort_ap_restore", 2) if self.config else 2)
        self.state.action_points[target] = self.state.action_points.get(target, 0) + comfort_restore
        # 通知被安慰方
        target_seat_id = self.state.role_controller.get(target)
        target_seat = self.network.seats.get(target_seat_id) if target_seat_id else None
        if target_seat and target_seat.alive:
            await self.network.send_and_drain(target_seat, {
                "type": "notification",
                "title": "被安慰",
                "body": f"【{role}】安慰了你，你感到精神一振（+2 行动点）。",
                "severity": "info",
            })
        return f"【安慰】你安慰了 {target}，他/她恢复了些许精神（+2 行动点）。"

    async def execute_shoot(self, role: str, target: str, seat: SeatConnection) -> str:
        """向目标开枪。若持有带 ammo 状态的武器，检查并消耗子弹。"""
        if target not in self.state.alive_roles:
            return f"{target} 已经不在这里或已死亡。"

        # 查找可射击武器（优先查找有 ammo 状态的物品）
        weapon_id = None
        for item_id in self.state.get_inventory(role):
            item = self.state.item_registry.get(item_id, {})
            if item.get("action") == "shoot":
                weapon_id = item_id
                break

        if weapon_id:
            ammo = self.state.get_item_state(weapon_id, "ammo", 0)
            if ammo > 0:
                self.state.set_item_state(weapon_id, "ammo", ammo - 1)
                remaining = ammo - 1
                ammo_text = f"（剩余 {remaining} 发子弹）" if remaining > 0 else "（子弹已用尽）"
                return f"【射击】你向 {target} 开枪了！{ammo_text}（等待 GM 裁决）"
            else:
                return f"【射击】你扣动扳机，但枪膛空空如也——已经没有子弹了。你仍然可以用枪威胁 {target}。"

        # 没有武器也能"开枪"（空手/其他方式）
        return f"【射击】你向 {target} 开枪了！（等待 GM 裁决）"

    async def execute_threaten(self, role: str, target: str, seat: SeatConnection) -> str:
        """用武器威胁目标（不消耗子弹/弹药）。"""
        if target not in self.state.alive_roles:
            return f"{target} 已经不在这里或已死亡。"
        return f"【威胁】你用武器指着 {target}，气氛瞬间紧张起来。（不消耗弹药）"

    async def execute_autopsy(self, role: str, location: str, seat: SeatConnection) -> str:
        """验尸：检查当前地点的尸体。"""
        dead_here = [r for r in self.state.dead_roles if self.state.locations.get(r) == location]
        if not dead_here:
            return f"{location} 没有尸体可以验尸。"
        return f"【验尸】你检查了 {', '.join(dead_here)} 的尸体，发现了一些线索。（需 GM 补充细节）"

    @staticmethod
    def parse_red_truth(text: str) -> tuple[list[str], list[str]]:
        """从文本中提取红字和金字声明（XML 标签格式）。
        返回: (红字列表, 金字列表)
        """
        red = re.findall(r"<red>\s*(.*?)\s*</red>", text, re.IGNORECASE)
        gold = re.findall(r"<gold>\s*(.*?)\s*</gold>", text, re.IGNORECASE)
        return red, gold

    def _get_info_points(self, info_id: str) -> int:
        if self.config:
            return self.config.get_info_points(info_id)
        for prefix, pts in {"P-": 1, "S-": 2, "C-": 4}.items():
            if info_id.startswith(prefix):
                return pts
        return 0
