# 元机制 / 元行动 + Buff 系统 设计文档

> 版本: v1.0
> 目标: 将物品行为和状态效果从硬编码中提取为可配置的原子操作组合

---

## 一、设计哲学

### 当前问题

1. `core.py` 中 `special_executed` if-elif 链硬编码了 10+ 种特殊行动
2. 每种物品行为需要独立的方法（`execute_shoot`、`execute_threaten`、`execute_search`...）
3. "熬夜双倍AP" 硬编码在 `get_action_point_cost` 中
4. 新增一种物品或状态效果 = 新增一段 Python 代码

### 目标架构

**"一切皆配置，代码只负责执行原子操作。"**

- **元行动（Meta Action）**：不可再分的原子操作，如"消耗AP"、"检查状态"、"广播消息"
- **物品行为**：元行动的有序列表（JSON 配置）
- **Buff 效果**：元行动的有序列表（JSON 配置）
- **Orchestrator**：解析配置 → 按顺序执行元行动 → 无副作用地推进游戏状态

---

## 二、元行动清单

所有元行动都是纯函数：接收 `(context: ActionContext)` → 返回 `ActionResult`。

| 元行动 ID | 参数 | 说明 |
|-----------|------|------|
| `check_target_alive` | `error_msg` | 检查目标角色是否存活 |
| `check_item_state` | `key`, `condition`, `error_msg` | 检查物品状态，如 `ammo > 0` |
| `check_buff` | `buff_id`, `condition`, `error_msg` | 检查角色是否持有某 buff |
| `consume_ap` | `amount` | 消耗 AP（可引用变量如 `$base_cost`） |
| `consume_item_state` | `key`, `delta` | 修改物品状态，如 `ammo -= 1` |
| `consume_buff_charge` | `buff_id`, `delta` | 消耗 buff 层数或持续时间 |
| `grant_buff` | `buff_id`, `duration`, `params` | 给目标施加 buff |
| `remove_buff` | `buff_id` | 移除 buff |
| `broadcast` | `message`, `exclude_self` | 向同地点所有人广播 |
| `notify_self` | `title`, `body`, `severity` | 给行动者发送通知 |
| `notify_target` | `title`, `body`, `severity` | 给目标发送通知 |
| `log_event` | `event_type`, `message` | 写入 narrative_log |
| `transfer_item` | `item_id`, `to_role` | 转移物品 |
| `mark_dead` | `cause` | 标记角色死亡 |
| `unlock_info` | `info_id` | 解锁信息条目 |
| `move_actor` | `location` | 强制移动角色 |
| `consume_item` | — | 消耗（删除）一次性物品 |

### 变量插值

所有字符串参数支持变量插值：

| 变量 | 含义 |
|------|------|
| `{role}` | 行动者角色名 |
| `{target}` | 目标角色名 |
| `{location}` | 当前地点 |
| `{item_state.KEY}` | 物品状态字段 |
| `{buff.BUFF_ID.duration}` | buff 剩余持续时间 |
| `{ap_cost}` | 实际 AP 消耗（已乘过倍数） |

---

## 三、Buff 系统设计

### 3.1 Buff 定义

```json
{
  "buffs": {
    "night_owl": {
      "name": "熬夜",
      "type": "neutral",
      "description": "你选择继续行动，行动点消耗翻倍",
      "duration": {
        "type": "until_phase",
        "phases": ["DAWN"]
      },
      "effects": [
        {"op": "modify_ap_cost", "multiplier": 2.0}
      ],
      "removable_by": ["sleep", "force_rest"],
      "on_apply": {
        "notify_self": {"title": "状态", "body": "你决定熬夜，行动点消耗翻倍。", "severity": "info"}
      },
      "on_remove": {
        "notify_self": {"title": "状态", "body": "清晨到来，疲劳消退。", "severity": "info"}
      }
    },
    "injured": {
      "name": "受伤",
      "type": "debuff",
      "duration": {
        "type": "turns",
        "count": 3,
        "countdown_on": ["token_ring_end"]
      },
      "effects": [
        {"op": "modify_ap_cost", "multiplier": 1.5},
        {"op": "modify_success_rate", "action_types": ["investigate", "search"], "multiplier": 0.8}
      ]
    },
    "encouraged": {
      "name": "受到鼓舞",
      "type": "buff",
      "duration": {
        "type": "turns",
        "count": 2,
        "countdown_on": ["token_ring_end"]
      },
      "effects": [
        {"op": "modify_ap_cost", "multiplier": 0.8}
      ]
    },
    "terrified": {
      "name": "恐惧",
      "type": "debuff",
      "duration": {
        "type": "turns",
        "count": 2
      },
      "effects": [
        {"op": "block_action", "action_ids": ["investigate", "search"]}
      ]
    }
  }
}
```

### 3.2 Duration 类型

| 类型 | 参数 | 说明 |
|------|------|------|
| `permanent` | — | 永久存在，需显式移除 |
| `until_phase` | `phases: [str]` | 到达指定阶段时自动移除 |
| `turns` | `count: int`, `countdown_on: [str]` | 经过 N 个指定事件后移除 |
| `until_death` | — | 角色死亡时移除 |
| `single_use` | — | 触发一次效果后自动移除 |

### 3.3 Effect 类型

| 效果 | 参数 | 说明 |
|------|------|------|
| `modify_ap_cost` | `multiplier: float` | AP 消耗乘数（可叠加） |
| `modify_success_rate` | `action_types: [str]`, `multiplier: float` | 特定行动成功率调整 |
| `block_action` | `action_ids: [str]` | 禁止特定行动 |
| `grant_extra_action` | `action_id: str`, `count: int` | 额外行动次数 |

### 3.4 Buff 叠加规则

- **同名 buff 不叠加**：再次施加时刷新持续时间
- **效果叠加**：不同 buff 的 `modify_ap_cost` 效果**相乘**
  - 例：`night_owl(×2) + injured(×1.5) = ×3.0`
- **block_action 叠加**：任一 buff 阻塞即不可用

---

## 四、物品行为配置

### 4.1 设计原则

物品不再使用模板继承，而是直接定义 `granted_actions`（授予的行动列表）。每个行动是一个元行动步骤序列。

```json
{
  "items": [
    {
      "id": "revolver",
      "name": "左轮手枪",
      "type": "permanent",
      "description": "一把老旧的左轮手枪",
      "player_desc": "你握着这把沉甸甸的左轮手枪。",
      "gm_desc": "一把.38口径左轮手枪，6发弹巢。",
      "location": "书房",
      "day_available": 1,
      "initial_state": {"ammo": 6},
      "granted_actions": [
        {
          "id": "shoot",
          "name": "射击",
          "ap_cost": 5,
          "target_type": "role",
          "priority": 100,
          "steps": [
            {"op": "check_target_alive", "error_msg": "{target} 已死亡或不在场"},
            {"op": "check_item_state", "key": "ammo", "condition": ">0", "error_msg": "枪膛空空如也"},
            {"op": "consume_item_state", "key": "ammo", "delta": -1},
            {"op": "broadcast", "message": "突然掏出了枪！", "exclude_self": true},
            {"op": "notify_self", "title": "射击", "body": "你向 {target} 开枪了！（剩余 {item_state.ammo} 发）", "severity": "error"},
            {"op": "log_event", "event_type": "ACTION", "message": "{role} 向 {target} 开枪"}
          ],
          "on_failure": {
            "steps": [
              {"op": "notify_self", "title": "射击", "body": "你扣动扳机，但枪膛空空如也。你仍然可以用枪威胁对方。", "severity": "warning"}
            ]
          }
        },
        {
          "id": "threaten",
          "name": "威胁",
          "ap_cost": 1,
          "target_type": "role",
          "priority": 50,
          "steps": [
            {"op": "broadcast", "message": "{role} 用武器指着 {target}！", "exclude_self": true},
            {"op": "notify_self", "title": "威胁", "body": "你用武器指着 {target}，气氛紧张。", "severity": "warning"},
            {"op": "log_event", "event_type": "ACTION", "message": "{role} 威胁 {target}"}
          ]
        }
      ]
    }
  ]
}
```

### 4.2 行动优先级

物品行动与基础行动混合时，通过 `priority` 排序。数值越大优先级越高。

| 行动 | 优先级 | 说明 |
|------|--------|------|
| `duel` | 999 | 决斗贝阿朵 |
| `shoot` | 100 | 射击 |
| `autopsy` | 90 | 验尸 |
| `search` | 80 | 搜身 |
| `investigate` | 70 | 调查 |
| `pickup` | 60 | 拾取 |
| `use_item` | 55 | 使用物品 |
| `gift` | 50 | 赠送 |
| `comfort` | 40 | 安慰 |
| `threaten` | 35 | 威胁 |
| `speak` | 0 | 发言（始终可叠加） |
| `move` | 0 | 移动意向（始终可叠加） |

---

## 五、动态行动构建

### 5.1 可用行动列表生成

```python
def build_available_actions(role: str, location: str) -> List[ActionOption]:
    options = []
    
    # 1. 基础行动
    options.append(ActionOption("investigate", "调查", 2, target_type="none"))
    options.append(ActionOption("move", "移动", None, target_type="location"))
    options.append(ActionOption("speak", "发言", 0, target_type="none", stackable=True))
    
    # 2. 物品授予的行动
    for item_id in state.get_inventory(role):
        item = state.item_registry.get(item_id, {})
        for action_def in item.get("granted_actions", []):
            # 检查 buff 是否阻塞此行动
            if is_action_blocked(role, action_def["id"]):
                continue
            options.append(ActionOption(
                action_id=f"{item_id}:{action_def['id']}",
                name=action_def["name"],
                ap_cost=calculate_ap_cost(role, action_def["ap_cost"]),
                item_id=item_id,
                target_type=action_def.get("target_type", "none"),
                priority=action_def.get("priority", 50),
            ))
    
    # 3. 按优先级排序
    options.sort(key=lambda x: x.priority, reverse=True)
    return options
```

### 5.2 Prompt 动态渲染

```
请描述你的行动。每轮你都可以发言。

可执行的行动：
- 射击 {target}（消耗 10 行动点）[受 熬夜 影响，原 5 × 2]
- 威胁 {target}（消耗 2 行动点）[受 熬夜 影响]
- 调查（消耗 4 行动点）[受 熬夜 影响]
- 移动（消耗 2-6 行动点）[受 熬夜 影响]
- 发言（不消耗）

不可用：
- 搜身（受【恐惧】影响，无法执行）

本时间槽剩余调查次数：{investigations_remaining}/2
```

---

## 六、执行引擎

### 6.1 ActionContext

```python
@dataclass
class ActionContext:
    role: str
    target: Optional[str]
    item_id: Optional[str]
    location: str
    slot: str
    seat: SeatConnection
    # 运行时变量
    variables: Dict[str, Any] = field(default_factory=dict)
```

### 6.2 执行流程

```python
async def execute_action_steps(steps: list[dict], ctx: ActionContext) -> bool:
    for step in steps:
        op = step["op"]
        handler = META_ACTION_REGISTRY.get(op)
        if not handler:
            raise ValueError(f"Unknown meta action: {op}")
        
        result = await handler(step, ctx)
        if not result.success:
            # 步骤失败，触发 on_failure
            return False
    return True
```

### 6.3 核心分发逻辑（替换 special_executed 链）

```python
# core.py 中
available = self.action_engine.build_available_actions(role, location)
parsed = self.action_engine.parse(text, nearby_roles)

# 找到最高优先级的匹配行动
matched = self._resolve_action(parsed, available)
if matched:
    # 计算实际 AP 消耗（含 buff 影响）
    actual_cost = self.state.calculate_ap_cost(role, matched.ap_cost)
    if self.state.consume_action_point(role, actual_cost):
        # 执行元行动步骤
        ctx = ActionContext(role=role, target=..., item_id=matched.item_id, ...)
        success = await self.meta_engine.execute(matched.steps, ctx)
        if not success and matched.on_failure:
            await self.meta_engine.execute(matched.on_failure["steps"], ctx)
```

---

## 七、与现有系统的兼容性

| 现有系统 | 迁移策略 |
|---------|---------|
| `ParsedAction` | 保留现有字段（向后兼容），新增 `item_actions: List[str]` |
| `special_executed` | 逐步替换为优先级队列，过渡期保留 |
| `night_owl` Set | 迁移到 `status_effects["night_owl"]` |
| `get_action_point_cost` | 替换为 `calculate_ap_cost`（遍历 buff effects） |
| `turn_token_actions.txt` | 改为动态渲染模板 |
| `execute_shoot` 等方法 | 保留作为 fallback，新物品使用元行动配置 |

---

## 八、实施路线图

### Phase 1: Buff 系统基础
1. 创建 `config/buffs.json`
2. `GameState` 新增 `status_effects` + buff 管理方法
3. `calculate_ap_cost` 替换 `get_action_point_cost`
4. `on_sleep_check` / `on_midnight` 使用 buff API
5. 将 `night_owl` 迁移为 buff

### Phase 2: 元行动引擎
1. 实现 `MetaActionEngine` + `ActionContext`
2. 实现核心元行动（check/consume/notify/broadcast/log）
3. 单元测试每个元行动

### Phase 3: 物品配置迁移
1. 扩展 `items.json` 为 `granted_actions` 格式
2. 实现物品行动解析 → 元行动步骤
3. 替换 `execute_shoot` / `execute_threaten` 为元行动执行
4. 验证 revolver 的 6 发子弹逻辑

### Phase 4: 动态行动构建
1. `build_available_actions()` 实现
2. `turn_token_actions.txt` 动态化
3. 替换 `special_executed` 链为统一分发器
4. 全面测试

---

## 九、文件清单

| 新建/修改 | 路径 | 说明 |
|-----------|------|------|
| 新建 | `config/buffs.json` | Buff 定义注册表 |
| 新建 | `config/item_actions.json` | 物品行动定义（或并入 items.json） |
| 新建 | `scripts/orchestrator/meta_engine.py` | 元行动执行引擎 |
| 新建 | `scripts/orchestrator/action_context.py` | ActionContext 数据类 |
| 修改 | `scripts/orchestrator/state.py` | 新增 status_effects + buff 管理 |
| 修改 | `scripts/orchestrator/action_engine.py` | 新增动态行动构建 + 元行动解析 |
| 修改 | `scripts/orchestrator/core.py` | 替换 special_executed 链为分发器 |
| 修改 | `config/items.json` | 扩展为 granted_actions 格式 |
| 修改 | `config/game_rules.json` | 移除 night_owl 相关硬编码 |
| 修改 | `config/prompts/turn_token_actions.txt` | 改为动态渲染模板 |
