"""
行动上下文 — 元行动执行时的共享状态容器

所有元行动通过 ActionContext 访问游戏状态、网络层和运行时变量。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .network import SeatConnection


@dataclass
class ActionContext:
    """元行动执行上下文。不可变身份 + 可变变量池。"""

    role: str                           # 行动者角色名
    location: str                       # 当前地点
    slot: str                           # 当前时间槽
    seat: Optional[SeatConnection] = None   # 行动者的 seat 连接
    target: Optional[str] = None        # 目标角色名（若有）
    item_id: Optional[str] = None       # 关联物品 ID（若有）

    # 运行时变量池，供元行动读写和字符串插值使用
    variables: Dict[str, Any] = field(default_factory=dict)

    def setvar(self, key: str, value: Any):
        """设置变量。"""
        self.variables[key] = value

    def getvar(self, key: str, default=None) -> Any:
        """读取变量。"""
        return self.variables.get(key, default)

    def interpolate(self, text: str) -> str:
        """将字符串中的占位符替换为上下文值。

        支持的占位符：
        - {role} / {target} / {location} / {slot}
        - {item_state.KEY} — 从 GameState 读取物品状态
        - {ap_cost} / {buff.BUFF_ID.duration} 等（预留）
        """
        # 基础字段
        result = text.replace("{role}", self.role or "")
        result = result.replace("{target}", self.target or "")
        result = result.replace("{location}", self.location or "")
        result = result.replace("{slot}", self.slot or "")
        # 变量池
        for k, v in self.variables.items():
            result = result.replace(f"{{{k}}}", str(v))
        return result
