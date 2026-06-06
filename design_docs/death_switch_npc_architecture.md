# 死亡触发、角色切换与NPC回收 — 实施计划

> 对应主计划: blue-devil-rictor-superboy Phase I + Phase H-5
> 前置条件: 时间槽系统、令牌环、行动点系统、BEATRICE playable 均已实现

---

## 一、现状核对（基于代码审计）

### 1.1 已实现的骨架（无需从零开始）

| 模块 | 已有能力 |
|------|---------|
| **DeathEngine** | `check_scheduled_deaths` 按(day,phase)查询；`handle_death` 区分AI/人类；`_switch_role` 按SEAT_CHAINS切链；`_make_spectator` 耗尽时观剧；**已含NPC回收逻辑**（terminate old_controller） |
| **NPCEngine** | `start_all_npcs` 启动未控角色；`terminate_npc` 终止；`prepare_role_for_player` 切换前回收 |
| **GameState** | `alive_roles/dead_roles/death_order`、`role_controller`、`mark_dead`结算分数、locations/action_points/unlocked_info |
| **Orchestrator** | `on_dawn`触发清晨死亡检查；`_handle_schrodinger`/`_handle_duel`调用死亡流程；NPC注册与普通seat同级 |
| **agent_wrapper** | `spectator_mode`处理、休眠-激活、turn_token响应 |

### 1.2 关键缺陷

1. **状态未继承**：`_switch_role` 启动新进程后，`on_register` 给新角色设 action_points=50，**丢失NPC期间积累的位置/信息/行动点**。
2. **旧seat残留**：`_switch_role` 关闭writer但未从 `network.seats` 中移除旧对象，新注册时覆盖存在竞态风险。
3. **NPC无轻量模式**：`start_npc` 调用 `mode="auto"`，加载完整 GM.md+PLAYER.md，token消耗与玩家同级。
4. **缺乏端到端测试**：死亡→切换→NPC回收的完整流程未在 `test_comprehensive.py` 中覆盖。

---

## 二、架构设计

### 2.1 状态继承协议（核心新增）

**原则**：所有状态存于 orchestrator GameState，切换时orchestrator"过户"给新seat。

```
Orchestrator                              Agent Wrapper (新进程)
    │                                         │
    │  1. _switch_role() 中：                  │
    │     - 终止NPC前，调用 _collect_role_state │
    │     - 写入 state.inheritance_pool[角色]   │
    │                                         │
    │  2. pm.start_seat() 启动新进程            │
    │◄────────────────────────────────────────│  register
    │                                         │
    │  3. on_register() 检测到 inheritance_pool │
    │     有该角色待继承状态                    │
    │────────────────────────────────────────►│  notification
    │                                         │  {type:"inherited_state", state:{...}}
    │                                         │
    │                                         │  4. _handle_inherited_state()
    │                                         │     更新GM Session认知
    │  5. pop(inheritance_pool) 清除            │
```

**继承字段**：location、action_points、unlocked_info、cooldowns、sleeping、night_owl、pending_moves。

### 2.2 NPC mode：GM与User合并的轻量模式

**核心设计**：NPC 不区分 GM Session 和 User Session，而是**共用同一个 Session**。外观与 auto mode 完全一致（同样响应 turn_token、发送 action），但内部只触发一次 AI 请求，由 GM 直接生成合规的角色行动。

**架构对比**：

```
auto mode（玩家）                    npc mode（NPC）
┌─────────────┐                    ┌─────────────┐
│ GM Session  │ ──规则判定──┐      │             │
│ (规则/状态) │            │      │  统一Session │◄── turn_token
└─────────────┘            ▼      │  (GM+User)  │───► action
┌─────────────┐      ┌─────────┐  │             │
│ User Session│◄─────┤ 判定结果│  └─────────────┘
│ (角色扮演)  │      └─────────┘        ↑
└─────────────┘                   一次请求完成
                                   合规+行动生成
```

**实现方式**：
- `ProcessManager.start_npc()` 启动 agent_wrapper 时传递 `--mode npc`
- agent_wrapper 的 `npc mode`：
  1. 只初始化**一个** Session（加载 GM.md + 角色行为摘要）
  2. 收到 turn_token 时，直接将该 Session 作为 GM 使用：输入完整上下文，输出同时包含"内部认知更新"和"角色行动"
  3. 从输出中提取 action_text（与 auto mode 相同的解析逻辑）
  4. 发送 action 给 orchestrator
- **不经过** `action_review` 流程（NPC 自己就是自己的 GM）
- **维护** hibernation_buffer，与 auto mode 相同（收到 turn_token 时统一处理缓存消息）

**Session prompt 设计**：
```
你是 {role_name} 的 GM 兼扮演者。
你的职责：
1. 根据游戏规则和当前状态，判断角色应该做什么
2. 直接输出角色的自然语言行动

规则约束：
- 行动点剩余 {ap}，调查消耗2点，移动消耗1-3点
- 遵守薛定谔规则：若嘉音/纱音另一人同地，立即移动离开
- 不主动泄露核心隐藏信息

角色倾向：
{role_specific_behavior}  ← 从 NPC_BEHAVIOR_PRESETS 读取

输出格式：
<player_input>
{角色的自然语言行动和发言}
</player_input>
```

**角色专属行为预设**（供 prompt 注入）：
| 角色 | 倾向地点 | 行为特征 |
|------|---------|---------|
| 嘉音 | 玫瑰园、本馆 | 寡言，对贝阿朵相关事物敏感，优先调查可疑痕迹 |
| 纱音 | 本馆、厨房 | 勤劳，关心战人，偶尔会准备食物 |
| 乡田 | 厨房、餐厅 | 厨师本职，围绕餐饮活动，对食材敏感 |
| 熊泽 | 本馆、庭院 | 喜欢讲故事（鲭鱼传说），悠闲走动 |
| 南条医师 | 书房、客房 | 医师本职，发现尸体时优先验尸 |
| 右代宫金藏 | 书房 | 家主，极少离开书房，研究黑魔法 |

**嘉音/纱音玩家优先原则**：
- `NPCEngine.get_npc_roles()` 中，嘉音和纱音默认视为玩家角色（由 P5/P6 控制）。
- 只有当 `active_seats` 不包含 P5/P6 时（开局玩家不足），才启动 `NPC_嘉音`/`NPC_纱音`。
- 这样确保薛定谔规则的核心冲突由玩家驱动，而非两个NPC随机碰撞。

---

## 三、实施步骤

### Step 1: GameState 新增 inheritance_pool
- **文件**: `scripts/orchestrator/state.py`
- **改动**: 新增 `inheritance_pool: Dict[str, dict] = field(default_factory=dict)`
- **验证**: 单元测试确认字段存在且可读写

### Step 2: DeathEngine 增强状态收集与清理
- **文件**: `scripts/orchestrator/death_engine.py`
- **改动**:
  1. 新增 `_collect_role_state(role) -> dict` 收集7个状态字段
  2. `_switch_role` 中：终止NPC前调用 `_collect_role_state` 写入 `inheritance_pool`
  3. `_switch_role` 中：关闭旧writer后，从 `network.seats` 中 `pop(seat_id)` 清理旧对象
  4. `_switch_role` 中：清理旧角色的 `role_controller` 映射
- **验证**: mock测试确认 `_collect_role_state` 返回正确结构

### Step 3: Orchestrator.on_register 发送 inherited_state
- **文件**: `scripts/orchestrator/core.py`
- **改动**:
  1. `on_register` 中，注册完成后检查 `inheritance_pool.pop(role, None)`
  2. 若有待继承状态：发送 `inherited_state` notification 给新seat
  3. 将继承状态写回 GameState（覆盖 `on_register` 中的默认值）
- **验证**: mock测试确认新seat收到 inherited_state 消息

### Step 4: agent_wrapper 处理 inherited_state
- **文件**: `scripts/agent_wrapper.py`
- **改动**:
  1. 新增 `_handle_inherited_state(msg)`：整理状态摘要传给 GM Session
  2. `_process_gm_message` 中新增 `inherited_state` 分支
- **验证**: mock测试确认收到消息后打印继承日志

### Step 5: NPC轻量模式
- **文件**:
  - `scripts/orchestrator/process_manager.py`：`start_npc` 添加 `--npc-lightweight`
  - `scripts/agent_wrapper.py`：解析 `--npc-lightweight`，跳过GM初始化，使用简化prompt
- **验证**: mock模式启动NPC，确认agent_wrapper日志显示"NPC lightweight mode"

### Step 6: 端到端测试
- **文件**: `scripts/test_comprehensive.py`
- **新增测试**:
  1. `test_death_and_switch`：模拟P7秀吉死亡→切换到南条医师，验证NPC回收+状态继承
  2. `test_npc_lightweight`：验证NPC seat使用轻量模式注册并行动
- **验证**: 两项测试均通过

### Step 7: 设计文档归档
- **文件**: `design_docs/death_switch_npc_architecture.md`
- **内容**: 将本计划的架构设计章节整理为正式设计文档

---

## 四、验证清单

- [ ] GameState 含 inheritance_pool 字段
- [ ] `_collect_role_state` 正确收集 location/action_points/unlocked_info 等7字段
- [ ] 角色切换时 NPC 进程被终止
- [ ] 角色切换时旧 seat 从 network.seats 中清理
- [ ] 新进程注册后收到 inherited_state 消息
- [ ] inherited_state 中的 unlocked_info 被写回 GameState
- [ ] agent_wrapper 收到 inherited_state 后更新 GM Session
- [ ] NPC 进程使用 `--npc-lightweight` 启动
- [ ] 端到端测试 `test_death_and_switch` 通过
- [ ] 端到端测试 `test_npc_lightweight` 通过
- [ ] 全部原有测试（movement/multi_day/beatrice/npc）仍通过

---

## 五、风险与应对

| 风险 | 可能性 | 影响 | 应对 |
|------|--------|------|------|
| 旧seat TCP连接残留，新进程注册冲突 | 低 | 高 | `_switch_role` 中 `network.seats.pop(seat_id)` 清理 |
| inheritance_pool 被重复读取 | 低 | 中 | 使用 `dict.pop()` 原子移除 |
| 新进程启动慢导致状态过期 | 低 | 中 | 不设TTL；旧seat关闭后1秒再启动新进程 |
| NPC轻量模式输出无法解析 | 中 | 低 | orchestrator解析失败默认skip；prompt强调格式 |
