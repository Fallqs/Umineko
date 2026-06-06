"""
元行动执行引擎

将物品行为、buff 效果等从硬编码方法提取为可配置的原子操作组合。
每个元行动是纯函数：(step_def, ctx) -> ActionResult。
"""

from typing import Any, Callable, Dict, Optional

from .action_context import ActionContext
from .network import NetworkLayer
from .state import GameState


class ActionResult:
    """元行动执行结果。"""

    def __init__(self, success: bool, message: str = ""):
        self.success = success
        self.message = message

    @classmethod
    def ok(cls, message: str = "") -> "ActionResult":
        return cls(True, message)

    @classmethod
    def fail(cls, message: str = "") -> "ActionResult":
        return cls(False, message)


MetaActionHandler = Callable[[dict, ActionContext, GameState, NetworkLayer], ActionResult]


class MetaActionEngine:
    """执行由元行动步骤序列定义的行为。"""

    def __init__(self, state: GameState, network: NetworkLayer):
        self.state = state
        self.network = network
        self._registry: Dict[str, MetaActionHandler] = {}
        self._register_builtins()

    def _register_builtins(self):
        """注册所有内置元行动。"""
        self.register("check_target_alive", _check_target_alive)
        self.register("check_item_state", _check_item_state)
        self.register("consume_ap", _consume_ap)
        self.register("consume_item_state", _consume_item_state)
        self.register("broadcast", _broadcast)
        self.register("notify_self", _notify_self)
        self.register("notify_target", _notify_target)
        self.register("log_event", _log_event)
        self.register("consume_item", _consume_item)
        self.register("transfer_item", _transfer_item)
        self.register("mark_dead", _mark_dead)
        self.register("unlock_info", _unlock_info)
        self.register("grant_buff", _grant_buff)
        self.register("remove_buff", _remove_buff)
        self.register("check_random", _check_random)
        self.register("restore_ap", _restore_ap)
        self.register("check_dead_in_location", _check_dead_in_location)
        self.register("pickup_item", _pickup_item)

    def register(self, op: str, handler: MetaActionHandler):
        """注册自定义元行动。"""
        self._registry[op] = handler

    async def execute_steps(
        self,
        steps: list[dict],
        ctx: ActionContext,
        on_failure: Optional[dict] = None,
    ) -> ActionResult:
        """按顺序执行元行动步骤序列。

        若某步骤失败且定义了 on_failure，则执行 on_failure 的 steps。
        返回最后一步的结果。
        """
        for step in steps:
            op = step.get("op")
            if not op:
                continue
            handler = self._registry.get(op)
            if not handler:
                return ActionResult.fail(f"未知元行动: {op}")
            result = handler(step, ctx, self.state, self.network)
            if not result.success:
                if on_failure and on_failure.get("steps"):
                    return await self.execute_steps(on_failure["steps"], ctx)
                return result
        return ActionResult.ok()


# ------------------------------------------------------------------
# 内置元行动实现
# ------------------------------------------------------------------


def _check_target_alive(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    target = ctx.target
    if not target:
        return ActionResult.fail("没有指定目标")
    if target not in state.alive_roles:
        msg = ctx.interpolate(step.get("error_msg", "{target} 已死亡或不在场"))
        return ActionResult.fail(msg)
    return ActionResult.ok()


def _check_item_state(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    item_id = ctx.item_id
    if not item_id:
        return ActionResult.fail("没有关联物品")
    key = step.get("key", "")
    condition = step.get("condition", "")
    current = state.get_item_state(item_id, key, 0)

    # 简单条件解析：支持 >0, >=N, ==N, <N
    ok = False
    cond_str = str(condition).strip()
    if cond_str.startswith(">="):
        ok = current >= int(cond_str[2:])
    elif cond_str.startswith(">"):
        ok = current > int(cond_str[1:])
    elif cond_str.startswith("<="):
        ok = current <= int(cond_str[2:])
    elif cond_str.startswith("<"):
        ok = current < int(cond_str[1:])
    elif cond_str.startswith("=="):
        ok = current == int(cond_str[2:])
    elif cond_str.startswith("!="):
        ok = current != int(cond_str[2:])
    else:
        # 默认 >0
        ok = current > 0

    if not ok:
        msg = ctx.interpolate(step.get("error_msg", f"物品状态不满足: {key} {condition}"))
        return ActionResult.fail(msg)
    return ActionResult.ok()


def _consume_ap(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    amount = step.get("amount", 1)
    # 支持变量引用
    if isinstance(amount, str) and amount.startswith("$"):
        amount = ctx.getvar(amount[1:], 1)
    actual = state.get_action_point_cost(ctx.role, int(amount))
    ctx.setvar("ap_cost", actual)
    if state.consume_action_point(ctx.role, actual):
        return ActionResult.ok()
    return ActionResult.fail("行动点不足")


def _consume_item_state(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    item_id = ctx.item_id
    if not item_id:
        return ActionResult.fail("没有关联物品")
    key = step.get("key", "")
    delta = step.get("delta", 0)
    current = state.get_item_state(item_id, key, 0)
    new_val = current + delta
    state.set_item_state(item_id, key, new_val)
    ctx.setvar(f"item_state.{key}", new_val)
    return ActionResult.ok()


def _broadcast(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    message = ctx.interpolate(step.get("message", ""))
    exclude_self = step.get("exclude_self", True)
    import asyncio
    for seat_id, seat in net.seats.items():
        if not seat.alive:
            continue
        if exclude_self and ctx.seat and seat_id == ctx.seat.seat_id:
            continue
        asyncio.create_task(net.send_and_drain(seat, {
            "type": "notification",
            "title": "事件",
            "body": message,
            "severity": "info",
        }))
    return ActionResult.ok()


def _notify_self(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    if not ctx.seat:
        return ActionResult.ok()
    title = ctx.interpolate(step.get("title", "通知"))
    body = ctx.interpolate(step.get("body", ""))
    severity = step.get("severity", "info")
    import asyncio
    asyncio.create_task(net.send_and_drain(ctx.seat, {
        "type": "notification", "title": title, "body": body, "severity": severity
    }))
    return ActionResult.ok()


def _notify_target(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    target = ctx.target
    if not target:
        return ActionResult.ok()
    seat_id = state.role_controller.get(target)
    if not seat_id:
        return ActionResult.ok()
    seat = net.seats.get(seat_id)
    if not seat or not seat.alive:
        return ActionResult.ok()
    title = ctx.interpolate(step.get("title", "通知"))
    body = ctx.interpolate(step.get("body", ""))
    severity = step.get("severity", "info")
    import asyncio
    asyncio.create_task(net.send_and_drain(seat, {
        "type": "notification", "title": title, "body": body, "severity": severity
    }))
    return ActionResult.ok()


def _log_event(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    # 由 orchestrator 读取 ctx.variables 后调用 _log_event
    event_type = step.get("event_type", "ACTION")
    message = ctx.interpolate(step.get("message", ""))
    ctx.setvar("_log_event_type", event_type)
    ctx.setvar("_log_event_message", message)
    return ActionResult.ok()


def _consume_item(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    item_id = ctx.item_id
    if item_id:
        state.remove_item(ctx.role, item_id)
    return ActionResult.ok()


def _transfer_item(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    item_id = step.get("item_id") or ctx.item_id
    to_role = step.get("to_role") or ctx.target
    if item_id and to_role:
        state.transfer_item(ctx.role, to_role, item_id)
    return ActionResult.ok()


def _mark_dead(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    target = step.get("target") or ctx.target or ctx.role
    cause = ctx.interpolate(step.get("cause", "未知原因"))
    if target in state.alive_roles:
        state.mark_dead(target)
        ctx.setvar("_death_cause", cause)
    return ActionResult.ok()


def _unlock_info(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    info_id = step.get("info_id", "")
    if info_id:
        state.unlock_info(ctx.role, info_id)
    return ActionResult.ok()


def _grant_buff(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    buff_id = step.get("buff_id", "")
    target = step.get("target") or ctx.target or ctx.role
    # buff_def 需要从配置加载，这里简化处理
    return ActionResult.ok()


def _remove_buff(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    buff_id = step.get("buff_id", "")
    target = step.get("target") or ctx.target or ctx.role
    if buff_id:
        state.remove_buff(target, buff_id)
    return ActionResult.ok()


def _check_random(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    import random
    chance = step.get("chance", 0.5)
    if random.random() < chance:
        return ActionResult.ok()
    msg = ctx.interpolate(step.get("error_msg", "随机检查失败"))
    return ActionResult.fail(msg)


def _restore_ap(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    target = step.get("target") or ctx.target or ctx.role
    amount = step.get("amount", 2)
    state.action_points[target] = state.action_points.get(target, 0) + amount
    ctx.setvar("restored_ap", amount)
    return ActionResult.ok()


def _check_dead_in_location(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    location = ctx.location
    dead_here = [r for r in state.dead_roles if state.locations.get(r) == location]
    if dead_here:
        ctx.setvar("dead_roles", ", ".join(dead_here))
        return ActionResult.ok()
    msg = ctx.interpolate(step.get("error_msg", f"{location} 没有尸体"))
    return ActionResult.fail(msg)


def _pickup_item(step: dict, ctx: ActionContext, state: GameState, net: NetworkLayer) -> ActionResult:
    location = ctx.location
    available = state.get_location_items(location, state.day)
    if not available:
        msg = ctx.interpolate(step.get("error_msg", f"你环顾{location}四周，没有找到可以带走的东西。"))
        return ActionResult.fail(msg)
    item_id = available[0]
    state.add_item(ctx.role, item_id)
    item = state.item_registry.get(item_id, {})
    ctx.setvar("item_name", item.get("name", "不明物品"))
    ctx.setvar("item_desc", state.get_item_desc(item_id, gm_view=False))
    return ActionResult.ok()
