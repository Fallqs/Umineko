# 《海猫鸣泣之时：六轩岛黄昏》数据设计指南

> 本文档描述项目的数据架构、各配置文件的职责与格式规范，供后续数据填充和扩展使用。

---

## 一、架构哲学

本项目遵循 **"架构代码只持有算法与协议，所有游戏特异性内容走配置"** 的原则。

| 层次 | 存放位置 | 内容 |
|------|---------|------|
| **架构代码** | `scripts/orchestrator/` | 状态机、网络层、令牌环、行动引擎、死亡引擎 |
| **JSON 配置** | `config/` | 地点、规则、时间槽、物品、信息条目 |
| **Prompt 模板** | `config/prompts/` | GM Session 的 prompt 文本模板 |
| **角色文档** | `roles/{角色名}/` | AGENTS.md / PLAYER.md / GM.md / PORTRAITS.md |
| **共享文档** | `shared/docs/` | 全局计分规则、信息条目注册表、公开地图 |
| **玩家手册** | `docs/` | 面向人类玩家的规则书与角色卡 |

**核心原则**：
1. 修改游戏平衡（AP消耗、回合数、成功率）→ 只需改 JSON
2. 修改时间槽结构（增删时间段）→ 只需改 JSON
3. 修改 Prompt 措辞 → 只需改 txt 模板
4. 新增角色 → 只需创建标准化文档目录
5. 修改地点/信息条目 → 只需改 JSON

---

## 二、JSON 配置详解

### 2.1 `config/locations.json` — 地点与距离图

```json
{
  "locations": ["本馆", "别馆", "玫瑰园", ...],
  "distances": {
    "本馆": {"餐厅": 0, "书房": 0, "庭院": 1, "别馆": 2, ...},
    "庭院": {"玫瑰园": 1, "别馆": 2, ...}
  }
}
```

| 字段 | 说明 |
|------|------|
| `locations` | 所有地点名称列表，顺序无关 |
| `distances` | 稀疏无向图。若 A→B 未定义，则尝试 B→A；若都不存在，默认距离为 3 |
| 距离 0 | 同一建筑内的不同房间（如本馆-餐厅-书房-厨房-客房） |
| 距离 1 | 相邻区域 |
| 距离 2-3 | 较远区域 |

**距离直接决定移动 AP 消耗**：`cost = distance × move_per_distance_unit`（默认 1 AP/单位）

**数据填充指引**：
- 新增地点 → 在 `locations` 列表中添加，在 `distances` 中补全与其他地点的距离
- 修改距离 → 直接改数值，无需改代码

---

### 2.2 `config/role_locations.json` — 角色初始位置

```json
{
  "_注释": "说明文字",
  "locations": {
    "右代宫战人": "港口",
    "嘉音": "本馆",
    "右代宫金藏": "书房",
    "贝阿朵莉切": "玫瑰园"
  }
}
```

| 规则 | 说明 |
|------|------|
| 上岛家族成员 | 统一初始位置为 "港口"（刚乘渡轮到达） |
| 岛上工作人员 | 统一初始位置为 "本馆"（已在岛上工作） |
| 特殊角色 | 金藏在"书房"，贝阿朵在"玫瑰园" |

---

### 2.3 `config/location_info.json` — 地点信息条目表

```json
{
  "书房": {
    "1": [
      ["P-书房血迹", "书房的地板上有奇怪的血迹..."],
      ["S-金藏日记", "在书桌抽屉深处发现一本上锁的日记..."]
    ],
    "2": [
      ["P-魔法阵", "书房墙壁上用血画着奇怪的魔法阵..."],
      ["C-金藏遗书", "日记中夹着一封遗书，提到了'黄金魔女的传说'..."]
    ]
  }
}
```

| 字段 | 说明 |
|------|------|
| 顶层键 | 地点名称，必须与 `locations.json` 中的名称一致 |
| 第二层键 | 天数（字符串格式 `"1"`），表示该信息在 Day N 出现 |
| 条目格式 | `[info_id, description]` 或 `{"id": ..., "desc": ..., "requires": ...}` |

**info_id 编码规范**：
- `P-xxx`：公开条目（1 分）
- `S-xxx`：半隐藏条目（2 分）
- `C-xxx`：核心隐藏条目（4 分）

**数据填充指引**：
- 为每个地点、每天设计 0-3 条信息
- Day 1 以公开信息为主（暴风雨、电话不通、停航等环境信息）
- Day 2-3 引入半隐藏信息（可疑痕迹、他人秘密）
- Day 4-7 引入核心隐藏信息（真相碎片、诡计核心）
- 若某地点某天没有信息，直接省略该天数键

---

### 2.4 `config/game_rules.json` — 游戏规则常数

```json
{
  "action_points": {
    "daily_reset": 26,
    "investigate": 2,
    "search": 3,
    "shoot": 5,
    "autopsy": 2,
    "pickup": 1,
    "use_item": 1,
    "comfort": 1,
    "move_per_distance_unit": 1
  },
  "token_ring": {
    "free_slot_rounds": 10,
    "meal_slot_rounds": 5,
    "investigations_per_slot": 2,
    "wait_timeout": 30
  },
  "info_points": {"P-": 1, "S-": 2, "C-": 4},
  "search_success_rate": 0.6,
  "comfort_ap_restore": 2
}
```

| 配置项 | 默认值 | 调整建议 |
|--------|--------|---------|
| `daily_reset` | 26 | 20=极简模式，26=标准模式，32=宽松模式 |
| `free_slot_rounds` | 10 | 减少则每轮更紧张，增加则有更多自由发言 |
| `meal_slot_rounds` | 5 | 用餐时间通常比自由时间短 |
| `investigations_per_slot` | 2 | 1=极度稀缺，2=标准，3=宽松 |
| `search_success_rate` | 0.6 | 搜身成功率 |
| `comfort_ap_restore` | 2 | 安慰恢复的 AP 量 |

**数据填充指引**：
- 调整游戏平衡时，优先修改此文件，无需重启代码即可生效（因为 ConfigLoader 是懒加载，但运行中的 orchestrator 不会热重载，需要重启）

---

### 2.5 `config/time_slots.json` — 时间槽定义

```json
{
  "time_slots": ["DAWN", "MORNING_1", "BREAKFAST", ...],
  "free_slots": ["MORNING_1", "NOON_1", "NOON_2", ...],
  "meal_slots": ["BREAKFAST", "LUNCH", "DINNER"],
  "special_slots": ["DAWN", "SLEEP_CHECK", "MIDNIGHT"]
}
```

| 分类 | 说明 |
|------|------|
| `time_slots` | 一天内的时间槽**顺序列表**，Orchestrator 按此顺序推进 |
| `free_slots` | 自由时间：角色可以自由移动、调查、行动 |
| `meal_slots` | 用餐时间：所有存活角色被强制移动到餐厅 |
| `special_slots` | 特殊时间：DAWN（清晨事件+AP重置）、SLEEP_CHECK（睡觉选择）、MIDNIGHT（深夜事件+死亡结算） |

**数据填充指引**：
- 可以增删自由时间槽（如增加 `AFTERNOON_3`）
- 可以调整时间槽顺序（如把 DINNER 放在 EVENING_1 之后）
- **必须保证**：`free_slots + meal_slots + special_slots` 的并集等于 `time_slots`
- **必须保证**：DAWN 和 MIDNIGHT 存在于 `special_slots` 中（代码逻辑依赖）

---

### 2.6 `config/items.json` — 物品注册表（已启用）

物品不再通过单一的 `action` 字段定义行为，而是通过 **`granted_actions`**（授予的行动列表）来声明该物品允许执行哪些操作。每个行动都是一个**元行动步骤序列**，由 `MetaActionEngine` 顺序执行。

```json
{
  "items": [
    {
      "id": "revolver",
      "name": "左轮手枪",
      "type": "permanent",
      "description": "一把老旧的左轮手枪...",
      "player_desc": "你握着这把沉甸甸的左轮手枪...",
      "gm_desc": "一把.38口径左轮手枪，6发弹巢...",
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
              {"op": "notify_self", "title": "射击", "body": "你扣动扳机，但枪膛空空如也...", "severity": "warning"}
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
            {"op": "notify_self", "title": "威胁", "body": "你用武器指着 {target}...", "severity": "warning"},
            {"op": "log_event", "event_type": "ACTION", "message": "{role} 威胁 {target}"}
          ]
        }
      ]
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 唯一标识符，全局唯一 |
| `name` | string | ✅ | 显示名称 |
| `type` | string | ✅ | `"consumable"`（使用/赠送后消失）或 `"permanent"`（永久持有） |
| `description` | string | | 简短描述 |
| `player_desc` | string | | 玩家视角的详细描述（拾取时展示） |
| `gm_desc` | string | | GM 视角的详细描述（含隐藏信息） |
| `location` | string | | 初始所在地点，必须与 `locations.json` 一致 |
| `day_available` | int | | 第几天开始出现在该地点（默认 1） |
| `initial_state` | dict | | 物品实例状态初始值，如 `{"ammo": 6}` |
| `granted_actions` | [object] | | 该物品授予的行动列表 |
| `unlocks_info` | [string] | | 拾取/使用后自动解锁的信息条目 ID 列表 |

#### `granted_actions` 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 行动标识符，如 `"shoot"`、`"gift"`、`"use"` |
| `name` | string | 显示名称，如 `"射击"`、`"赠送兔子玩偶"` |
| `ap_cost` | int | 基础 AP 消耗（实际消耗受 buff 影响） |
| `target_type` | string | `"none"` / `"role"` / `"location"` |
| `priority` | int | 行动优先级（越大越靠前显示） |
| `steps` | [object] | 元行动步骤序列，见下表 |
| `on_failure` | object | 某步骤失败时执行的备选步骤 |

#### 常用元行动（op）清单

| `op` | 参数 | 说明 |
|------|------|------|
| `check_target_alive` | `error_msg` | 目标存活检查 |
| `check_item_state` | `key`, `condition`, `error_msg` | 检查物品状态，如 `"ammo > 0"` |
| `check_random` | `chance`, `error_msg` | 随机成功率检查 |
| `check_dead_in_location` | `error_msg` | 检查当前地点有尸体 |
| `consume_ap` | `amount` | 消耗 AP（元行动内部使用，通常不需要） |
| `consume_item_state` | `key`, `delta` | 修改物品状态，如 `ammo -= 1` |
| `consume_item` | — | 销毁该物品（consumable 类型） |
| `restore_ap` | `target`, `amount` | 恢复目标 AP |
| `grant_buff` | `buff_id`, `duration` | 给目标施加 buff |
| `remove_buff` | `target`, `buff_id` | 移除目标 buff |
| `broadcast` | `message`, `exclude_self` | 向同地点所有人广播 |
| `notify_self` | `title`, `body`, `severity` | 通知行动者 |
| `notify_target` | `title`, `body`, `severity` | 通知目标 |
| `transfer_item` | `to_role` | 转移物品（从 `ctx.item_id` 读取） |
| `pickup_item` | `error_msg` | 拾取地点第一个可用物品 |
| `mark_dead` | `cause` | 标记角色死亡 |
| `unlock_info` | `info_id` | 解锁信息条目 |
| `log_event` | `event_type`, `message` | 写入 narrative_log |

#### 物品状态系统

每个 `item_id` 对应**唯一的物品实例**。当角色拾取物品时，系统从 `initial_state` 克隆一份状态存入 `GameState.item_states[item_id]`。

**状态的生命周期**：
1. **初始化**：`add_item()` 时从 `item_registry[item_id].initial_state` 克隆
2. **读取**：`get_item_state(item_id, key, default)`
3. **修改**：`set_item_state(item_id, key, value)` 或元行动 `consume_item_state`
4. **转移**：`transfer_item()` 转移持有权，状态绑定在 `item_id` 上自动跟随

#### 物品模板速查

**模板 1：武器（可射击 + 可威胁 + 默认可赠送）**
- `type`: `"permanent"`
- `granted_actions`: `[shoot, threaten]`
- 不配置 `gift` action → 走默认赠送逻辑（单纯转移物品）

**模板 2：一次性赠品（赠送后销毁 + 有特殊效果）**
- `type`: `"consumable"`
- `granted_actions`: `[use, gift]`
- `gift` 步骤中包含 `{"op": "consume_item"}` → 赠送后物品消失
- 示例：护身符（赠送解除恐惧 + 给目标加 encouraged buff）

**模板 3：体力药（净 AP 收益必须为正）**
- `type`: `"consumable"`
- `granted_actions`: `[use]`
- `use` 步骤：`restore_ap` 的 `amount` 必须 **>** `ap_cost`
- 示例：提神饮料（消耗 1 AP，恢复 5 AP，净收益 +4）

**模板 4：可多次转赠的使用后销毁物品**
- `type`: `"permanent"`（或 `"consumable"` 若使用即销毁）
- 有 `gift` action（仅 `transfer_item`，不含 `consume_item`）
- 有 `use` action（含 `consume_item`，使用后销毁）

**模板 5：解锁型物品（拾取/使用解锁信息）**
- `unlocks_info`: `["S-xxx", "C-yyy"]`
- 拾取时自动解锁，或通过 `use` action 的 `unlock_info` 步骤触发

#### 赠送规则

- **所有物品默认可赠送**：未配置 `gift` action 的物品走默认转移逻辑
- **配置了 `gift` action 的物品**：赠送时走元行动步骤，可实现特殊效果（加 buff、销毁、解锁信息等）
- **玩家必须指定具体物品**： `"把兔子玩偶给真里亚"` → 解析出 `gift_item="兔子玩偶"`、`gift_target="真里亚"`

#### 变量插值

所有字符串参数支持变量插值：

| 变量 | 含义 |
|------|------|
| `{role}` | 行动者角色名 |
| `{target}` | 目标角色名 |
| `{location}` | 当前地点 |
| `{item_state.KEY}` | 物品状态字段 |
| `{ap_cost}` | 实际 AP 消耗 |
| `{restored_ap}` | 恢复的行动点数量 |

---

## 三、Prompt 模板详解

### 3.1 模板机制

- **存放位置**：`config/prompts/*.txt`
- **加载器**：`scripts/prompt_loader.PromptLoader`
- **变量语法**：`$variable`（Python `string.Template`）
- **回退机制**：模板文件不存在时，代码使用内嵌的默认文本

### 3.2 当前模板列表

| 模板文件 | 注入位置 | 可用变量 |
|---------|---------|---------|
| `turn_token_actions.txt` | `_handle_turn_token` 的 prompt 末尾 | `$investigate_desc`, `$max_investigations` |
| `beatrice_special.txt` | 贝阿朵回合 prompt | 无（纯固定文本） |
| `buffer_summary.txt` | `_process_hibernation_buffer` | `$events` |
| `correction.txt` | `build_correction_prompt` | `$original_prompt`, `$errors`, `$original_output` |

### 3.3 新增模板指引

如需新增 prompt 模板：

1. 在 `config/prompts/` 下创建 `{name}.txt`
2. 在代码中使用 `self.prompt_loader.load_or_fallback("name", "默认文本", var1=..., var2=...)`
3. 变量名使用 `$snake_case` 格式
4. 保持向后兼容：始终提供 fallback 文本

**示例**：
```python
prompt = self.prompt_loader.load_or_fallback(
    "duel_challenge",
    "【决斗】你向贝阿朵莉切发起决斗！",
    opponent=target_role,
)
```

---

## 四、角色文档标准

### 4.1 文档体系

每个角色目录 `roles/{角色名}/` 必须包含：

| 文件 | 读者 | 内容 |
|------|------|------|
| `AGENTS.md` | AI助手（GM协程） | 角色身份、隐藏层、特殊机制、AI助手职责、审批规则、角色链 |
| `PLAYER.md` | 人类玩家 / AI User Session | 角色卡、公开层、半隐藏层（第一人称）、目标、扮演提示、特殊能力 |
| `GM.md` | AI GM协程 Session | 从 AGENTS.md 自动生成的精简版，聚焦规则判定与 orchestrator 通信 |
| `PORTRAITS.md` | AI User Session | 角色肖像、外貌细节、语气风格参考（可选） |

### 4.2 AGENTS.md 标准结构

```markdown
# {角色名} — {角色链}·{链位置}

> 引言行（NPC prompt 生成器会提取此行为角色定位）
> ⚠️ 特别注意：关键规则提示

## 一、角色身份（公开层）

- **姓名**：{角色名}
- **身份**：{身份描述}
- **年龄**：{年龄}
- **公开信息**：{所有玩家都知道的信息}

## 二、半隐藏层（玩家知晓，但应保密）

- {半隐藏信息1}
- {半隐藏信息2}

## 三、核心隐藏层（GM密封，未解锁前不可知）

> ⚠️ **AI助手绝对不可在解锁前向玩家透露以下内容。**

- **隐藏条目A**：{内容} —— 解锁条件：{条件}
- **触发死亡条件**：{条件} —— 执行：{执行方式}

## 四、特殊机制

### 4.1 {机制名}
- {规则描述}

## 五、AI助手（GM协程）职责

### 5.1 角色扮演辅助
### 5.2 保密红线
### 5.3 触发死亡监控

## 六、行动审批配置

| 操作 | 审批类型 | 说明 |
|------|---------|------|
| {操作} | {类型} | {说明} |

## 七、角色链信息

```
{角色链名称}（{玩家ID}）：
第一环：{角色A}（开局）→ Day {N} 预定死亡
第二环：{角色B}（备用）→ Day {M} 剧情杀
```

## 八、得分追踪

```json
{ ... }
```
```

**章节标题规范**（NpcPromptBuilder 依赖这些关键字）：
- 角色身份：`## 一、角色身份` 或 `## 一、角色身份（公开层）`
- 特殊机制：`## 四、特殊机制` 或包含"特殊"、"机制"的标题
- 扮演提示：在 PLAYER.md 中，标题为 `## 扮演提示` 或 `## 扮演建议`
- 目标：在 PLAYER.md 中，标题为 `## 你的目标` 或 `## 角色目标`
- 特殊能力：在 PLAYER.md 中，标题为 `## 特殊能力` 或 `## 能力`

### 4.3 自动生成脚本

```bash
# 从 AGENTS.md 生成 GM.md（规则判定用）
python scripts/generate_gm_md.py

# 从 AGENTS.md 生成 PLAYER.md（玩家视角用）
python scripts/generate_player_md.py
```

**工作流建议**：
1. 先编写/修改 `AGENTS.md`（最完整的版本）
2. 运行生成脚本，自动生成 `GM.md` 和 `PLAYER.md`
3. 人工审校生成的文档，补充第一人称转换中丢失的细腻情感

### 4.4 NPC Prompt 自动生成

NPC 模式运行时，系统不再使用硬编码的行为描述，而是：

1. 读取 `roles/{角色}/AGENTS.md` + `PLAYER.md` + `GM.md`
2. 提取以下部分拼接成 prompt：
   - **角色定位**：AGENTS.md 的"角色身份" → 第一段简述
   - **行为倾向**：PLAYER.md 的"扮演提示" + "目标" + "特殊能力" → 列表形式
   - **特殊规则**：AGENTS.md 的"特殊机制" → 列表形式
   - **NPC 指令后缀**：固定文本"你是NPC，请直接输出角色行动，不需要解释规则。"

**数据填充指引**：
- 确保每个角色的 PLAYER.md 包含"扮演提示"章节
- 确保每个角色的 AGENTS.md 包含"特殊机制"章节
- 若某角色没有特殊规则，NpcPromptBuilder 会自动跳过该部分

---

## 五、共享文档（shared/docs/）

| 文件 | 读者 | 内容 |
|------|------|------|
| `scoring_rules.md` | 所有玩家进程 | 计分规则：信息条目分值、结算时机、加分/扣分项 |
| `info_entries.md` | GM 进程 | 完整信息条目注册表：ID、内容、解锁条件、所属角色 |
| `core_hidden_layer.md` | GM 进程 | 核心诡计与全局真相（如三代贝阿朵、安田纱代身份） |
| `local_lore.md` | 所有玩家进程 | 六轩岛风物志、历史背景、公开传说 |
| `public_map.md` | 所有玩家进程 | 公开地图与地点说明 |

**数据填充指引**：
- `info_entries.md` 是 orchestrator 自动计分的唯一依据，必须与 `config/location_info.json` 中的 info_id 保持一致
- `core_hidden_layer.md` 是 GM 的绝密参考，**不可**在玩家进程中加载

---

## 六、数据一致性检查清单

在新增/修改数据后，请确认：

### 地点相关
- [ ] `locations.json` 中的地点名称与 `location_info.json` 的顶层键一致
- [ ] `locations.json` 中的距离图是完整的（新增地点需补全到所有已有地点的距离）
- [ ] `role_locations.json` 中的地点名称存在于 `locations.json`

### 信息条目相关
- [ ] `location_info.json` 中的 info_id 前缀符合规范（`P-`/`S-`/`C-`）
- [ ] `info_entries.md` 中注册了相同 ID 的条目
- [ ] `game_rules.json` 中的 `info_points` 定义了对应前缀的分值

### 角色相关
- [ ] 新角色的 `AGENTS.md` 包含标准章节（角色身份、半隐藏层、核心隐藏层、特殊机制、AI助手职责、角色链）
- [ ] 新角色的目录名与 `role_locations.json` 中的键一致
- [ ] 运行 `generate_gm_md.py` 和 `generate_player_md.py` 后生成了 `GM.md` 和 `PLAYER.md`
- [ ] 新角色的 `PLAYER.md` 包含"扮演提示"和"目标"章节（供 NpcPromptBuilder 使用）

### 时间槽相关
- [ ] `time_slots.json` 中的分类并集等于 `time_slots` 列表
- [ ] `time_slots` 列表中包含 "DAWN" 和 "MIDNIGHT"

### Prompt 模板相关
- [ ] 新增模板时，代码中有对应的 fallback 文本
- [ ] 模板变量名使用 `$snake_case`

---

## 七、扩展路线图

### 短期（数据填充阶段）

1. **地点信息条目扩充**
   - 为每个地点填充 Day 1-7 的信息条目
   - 确保每天有 1-3 条信息，形成信息密度梯度

2. **角色文档完善**
   - 为所有 18 个角色编写完整的 AGENTS.md
   - 运行生成脚本产出 GM.md 和 PLAYER.md
   - 审校 PLAYER.md 的第一人称转换质量

3. **物品系统数据化**
   - 创建 `config/items.json`
   - 定义岛上的关键道具（手枪、毒药、日记、钥匙等）
   - 在 orchestrator 中集成物品拾取/使用/传递逻辑

### 中期（玩法深化）

4. **死亡调度配置化**
   - 将硬编码的 `DEATH_SCHEDULE` 外部化到 `config/death_schedule.json`
   - 支持条件触发死亡（如"如果在书房发现日记 → 触发书房死亡"）

5. **角色链与座位链配置化**
   - 将 `SEAT_CHAINS` 外部化到 `config/seat_chains.json`
   - 支持动态角色切换链定义

6. **NPC 行为预设增强**
   - 在角色文档中增加 `## NPC 行为参数` 章节
   - 支持更精细的 NPC 参数： preferred_locations、curiosity_level、aggression_level 等

### 长期（模组支持）

7. **剧本模组系统**
   - `config/modules/` 目录，每个模组一个子目录
   - 模组包含：自定义地点、自定义角色、自定义信息条目、自定义时间槽、自定义规则覆盖
   - orchestrator 启动时选择加载的模组

---

## 八、文件修改权限速查

| 如果我修改了... | 我还需要检查/更新... |
|----------------|---------------------|
| `config/game_rules.json` | 无需其他修改（热重载需重启 orchestrator） |
| `config/locations.json` | `config/role_locations.json`、`config/location_info.json` |
| `config/location_info.json` | `shared/docs/info_entries.md` |
| `roles/{角色}/AGENTS.md` | 运行 `generate_gm_md.py` + `generate_player_md.py` |
| `config/prompts/*.txt` | 无需其他修改（即时生效） |
| `scripts/orchestrator/*.py` | 运行 `python scripts/test_comprehensive.py` 验证 |

---

*「没有爱，就看不见。」*
*但在这个系统中，数据结构也是受到权限控制的。*
