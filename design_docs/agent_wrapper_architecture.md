# Agent Wrapper 架构设计文档

> 版本: v3 (TCP Client 模式)
> 日期: 2026-06-06
> 对应计划: blue-devil-rictor-superboy

---

## 一、设计目标

Agent Wrapper 是每个角色席位（seat）的独立进程，负责：
1. 作为 **TCP Client** 连接到 orchestrator
2. 维护 **GM Session**（规则判定、状态管理、信息过滤）
3. 可选维护 **User Session**（auto 模式下生成角色行动）
4. 实现 **休眠-激活机制**（未收到 turn_token 时彻底休眠，零 API 调用）
5. 支持 **多模式**：auto / human / beatrice / npc

---

## 二、总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent Wrapper (单进程)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ GM Session   │  │ User Session │  │ TCP Connection   │  │
│  │ (KimiCLI)    │  │ (KimiCLI)    │  │ (asyncio)        │  │
│  │              │  │              │  │                  │  │
│  │ - 规则判定   │  │ - 角色扮演   │  │ - register       │  │
│  │ - 状态追踪   │  │ - 行动生成   │  │ - turn_token     │  │
│  │ - 信息过滤   │  │ - 自然语言   │  │ - action         │  │
│  │ - 认知更新   │  │ - 发言描述   │  │ - notification   │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│           ▲                ▲                  ▲             │
│           │                │                  │             │
│  ┌────────┴────────────────┴──────────────────┴────────┐   │
│  │              SeatAgent (状态机 + 调度器)              │   │
│  │                                                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │ is_hiberna- │  │ hibernation_│  │ pending_    │ │   │
│  │  │ ting: bool  │  │ buffer: list│  │ notifications│ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  │                                                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │ _gm_loop    │  │ _user_loop  │  │ _reader_loop│ │   │
│  │  │ (消息分发)   │  │ (行动生成)   │  │ (网络读取)   │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ TCP (JSONL)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Orchestrator                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、状态机：休眠 ↔ 激活

```
           ┌─────────────┐
    ┌─────►│  HIBERNATING│◄────────────────┐
    │      │  (默认状态)  │                 │
    │      └──────┬──────┘                 │
    │             │ 收到 turn_token         │
    │             ▼                        │
    │      ┌─────────────┐                 │
    │      │ ACTIVATING  │                 │
    │      │ 1. 处理buffer│                 │
    │      │ 2. GM认知更新│                 │
    │      └──────┬──────┘                 │
    │             │                        │
    │             ▼                        │
    │      ┌─────────────┐                 │
    │      │ GENERATING  │                 │
    │      │ User生成行动 │                 │
    │      └──────┬──────┘                 │
    │             │                        │
    │             ▼                        │
    │      ┌─────────────┐   action发送后   │
    └──────┤   IDLE      │─────────────────┘
           │ (等待下一回合)│
           └─────────────┘
```

### 休眠状态定义
- `is_hibernating = True`
- `_gm_loop` 继续消费队列，但**绝不调用任何 AI Session**
- `notification` / `scene` 消息存入 `hibernation_buffer`，完整保留
- 计数：收到消息数（不截断）

### 激活流程（收到 turn_token）
1. `is_hibernating = False`
2. `_process_hibernation_buffer()`：将 buffer 全部传给 **GM Session**
   - GM 输出内部认知更新（纯内部，不发给 orchestrator）
   - 让角色"知道"等待期间发生了什么
3. 构造 **User Session prompt**：`GM认知更新 + turn_token完整上下文`
4. User Session 生成自然语言行动
5. 发送 `action` 消息给 orchestrator
6. 清空 `hibernation_buffer`
7. `is_hibernating = True`（立即回到休眠）

---

## 四、消息协议

### Orchestrator → Agent

| 消息类型 | 触发行为 | 休眠时处理 |
|---------|---------|-----------|
| `turn_token` | **唯一激活入口**，启动完整激活流程 | N/A（休眠时不应收到） |
| `scene` | 旧协议兼容：触发 GM → User 生成行动 | 存入 hibernation_buffer |
| `notification` | 系统通知/同场发言/移动广播 | 存入 hibernation_buffer |
| `action_review_result` | BEATRICE 复核结果：approve/reject | 若激活中则处理；否则存入 buffer |
| `spectator_mode` | 进入观察者模式 | 立即处理（不依赖 AI） |
| `schrodinger_judgment` | BEATRICE 模式专用 | 立即处理 |
| `register_ok` | 注册确认 | 打印日志 |

### Agent → Orchestrator

| 消息类型 | 发送时机 | 内容 |
|---------|---------|------|
| `register` | 连接后 | `seat_id`, `role_name` |
| `action` | turn_token 激活后 | `action_text`, `parent_id` |
| `gm_output` | scene 兼容模式 | `text`, `orchestration_requests` |
| `action_review` | 旧协议兼容 | `action_text` |
| `action_review_result` | beatrice 模式 | `result`, `reason` |
| `schrodinger_judgment_result` | beatrice 模式 | `text` |

### turn_token 消息格式
```json
{
  "type": "turn_token",
  "seat_id": "P1",
  "slot": "MORNING_1",
  "day": 2,
  "location": "书房",
  "action_points": 42,
  "round": 1,
  "total_rounds": 2,
  "nearby_players": ["右代宫战人", "纱音"],
  "pending_speeches": ["【纱音】我去厨房拿点喝的。"],
  "context": "你在书房...",
  "id": "turn_d2_m1_P1_r1"
}
```

### action 消息格式
```json
{
  "type": "action",
  "seat_id": "P1",
  "role_name": "右代宫战人",
  "action_text": "我仔细调查了书架...",
  "parent_id": "turn_d2_m1_P1_r1"
}
```

---

## 五、模式说明

### auto 模式（默认）
- **GM Session**：规则判定、状态管理、信息过滤
- **User Session**：生成角色行动（自然语言描述）
- **流程**：turn_token → GM处理buffer → User生成action → 发送action

### human 模式
- **仅 GM Session**：解释场景、在 TUI 中等待玩家输入
- **无 User Session**
- **流程**：turn_token → GM展示完整上下文 → TUI等待输入 → 发送action

### beatrice 模式
- **仅 GM Session**：合规复核、剧情裁决
- **无 User Session**
- **不参与普通令牌环**
- **处理**：`action_review` 请求 → GM审查 → 返回 `action_review_result`

### npc 模式（新增）
- **轻量级 User Session**：简化 prompt，行为模式相对固定
- **无 GM Session**（或极轻量 GM）
- **策略**：
  - 随机在当前地点调查或移动
  - 偶尔会与其他角色对话
  - 不主动泄露核心隐藏信息
  - 遵守薛定谔规则

---

## 六、模块结构

```
agent_wrapper.py
├── SeatAgent (主类)
│   ├── init()
│   │   ├── 准备 GM Session work_dir
│   │   ├── 准备 User Session work_dir (auto模式)
│   │   └── _connect_to_orchestrator()
│   ├── _connect_to_orchestrator()
│   │   ├── asyncio.open_connection()
│   │   └── 发送 register
│   ├── _orchestrator_reader_loop()
│   │   └── 读取 JSONL → 放入 gm_input_queue
│   ├── _gm_loop()
│   │   └── 消费 gm_input_queue → _process_gm_message()
│   ├── _user_loop()
│   │   └── 消费 user_input_queue → User.run_once() → 发送action
│   ├── _process_gm_message()
│   │   ├── turn_token → _handle_turn_token()
│   │   ├── scene → _handle_scene()
│   │   ├── notification → _handle_notification()
│   │   ├── action_review → _handle_action_review()
│   │   ├── action_review_result → _handle_action_review_result()
│   │   ├── spectator_mode → _handle_spectator_mode()
│   │   └── schrodinger_judgment → _handle_schrodinger_judgment()
│   ├── _handle_turn_token()
│   │   ├── _process_hibernation_buffer() (GM认知更新)
│   │   ├── 构造 prompt
│   │   ├── user_input_queue.put() (auto)
│   │   └── 直接发送 action (beatrice)
│   ├── _process_hibernation_buffer()
│   │   └── GM.run_once(buffer_summary)
│   ├── _send_action()
│   │   └── 发送 {"type": "action", ...}
│   └── run()
│       └── asyncio.gather(_reader_loop, _gm_loop, _user_loop)
│
├── SessionWrapper
│   ├── init(work_dir, session_id)
│   ├── init(config, model, thinking, yolo)
│   └── run_once(text) → (output, thinking, orch_reqs)
│
└── 辅助函数
    ├── _prepare_md_work_dir()
    ├── _extract_orchestration_requests()
    ├── _extract_player_input()
    └── _strip_blocks()
```

---

## 七、关键设计决策

### 1. 为什么不需要 `token_done` / `time_slot_end`？
- Agent 发送 action 后**自主休眠**
- Orchestrator 无需广播唤醒/休眠指令
- 减少网络广播开销，简化协议

### 2. 为什么 buffer 不截断？
- 确保玩家信息公平：每个角色收到 turn_token 时，看到的是**完整**的等待期间事件
- GM Session 负责从 buffer 中提取关键信息（分层 prompt）

### 3. 为什么 BEATRICE 复核是异步的？
- Orchestrator 端：`on_action_received` 中 `asyncio.create_task(_beatrice_review_async)`
- 不阻塞令牌环
- 复核结果作为 notification 发送给玩家

### 4. 为什么保留 scene 兼容？
- 旧 orchestrator 可能仍然发送 scene 消息
- Agent 同时支持 turn_token（新）和 scene（旧）
- scene 触发 action_review（旧协议），turn_token 触发 action（新协议）

---

## 八、与旧 Pipe 模式的关系

旧 `agent_wrapper.py`（pipe 模式）保留为 **NPC 独立进程** 的专用实现：
```bash
cd roles/贝阿朵莉切
kimi --hide-thinking --agent-mode --agent-pipe ../shared/inbox/贝阿朵莉切/agent_pipe.jsonl
```

新 `agent_wrapper.py`（TCP 模式）是 **玩家 seat / NPC seat** 的统一实现：
```bash
python scripts/agent_wrapper.py \
  --work-dir roles/右代宫战人 \
  --seat-id P1 \
  --orchestrator-host 127.0.0.1 \
  --orchestrator-port 9123 \
  --mode auto
```

两者可以共存：pipe 模式用于外部 AI Agent 驱动，TCP 模式用于直接连接到 orchestrator。
