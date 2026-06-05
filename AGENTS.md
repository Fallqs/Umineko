# 《海猫鸣泣之时：六轩岛黄昏》客户端 - 顶层规则

> 这是整个联机客户端的根规则文件。所有子目录的AGENTS.md都继承并覆盖此文件。

## 一、系统概述

本目录是《海猫鸣泣之时》剧本杀的联机游玩客户端。每个角色由一个独立的 kimi-code-cli 进程扮演，进程间通过 `shared/inbox/` 下的消息文件通信。

## 二、目录权限规则

| 目录 | 访问权限 | 说明 |
|------|---------|------|
| `gm/` | 仅GM进程 | 包含死亡顺序、核心隐藏层等绝密信息 |
| `roles/{角色名}/` | 对应角色进程 + GM | 角色自己的身份卡与文档 |
| `npcs/{NPC名}/` | GM进程 + AI注入 | NPC行为模式（旧版，已逐渐被独立NPC进程替代） |
| `roles/{NPC名}/` | NPC独立进程 | AI驱动的NPC角色进程，与普通玩家进程同级 |
| `shared/` | 所有进程 | 公开规则、游戏状态、消息队列 |

## 三、消息通信协议

所有进程通过 `shared/inbox/` 目录交换消息。消息文件格式：

```json
{
  "from": "发送者角色名或GM或NPC名",
  "to": "目标角色名或ALL或GM",
  "type": "say|action|gm_order|npc_inject|system",
  "content": "消息内容",
  "timestamp": "ISO时间",
  "day": 1,
  "scene": "场景名称",
  "require_approval": false,
  "meta": {}
}
```

- `say`：角色发言（同场景内所有人可见）
- `whisper`：私聊（仅to指定的角色可见）
- `action`：角色行动（调查、移动、使用道具等）
- `gm_order`：GM指令（分组、宣告死亡、发放线索）
- `npc_inject`：NPC发言/行动（由GM进程注入）
- `system`：系统事件（天气、时间推进、环境描述）

## 四、AI助手（GM协程）的职责

每个角色进程中的AI助手（即kimi-code-cli原生AI）充当该角色的**GM协程**，职责包括：

1. **规则判定**：审核玩家的行动是否符合规则（每日行动点、能力使用限制等）
2. **本地状态管理**：追踪该角色已收集的信息条目、道具、当前场景
3. **信息过滤**：根据角色能看到的内容，决定什么信息可以展示给玩家
4. **审批代理**：将需要GM审批的操作写入待审批队列

**AI助手绝对不可**：
- 查看上级目录中的 `gm/` 文件夹内容
- 透露其他角色的隐藏层信息
- 代替GM执行强制击杀或死亡宣告
- 修改 `shared/game_state.json` 中的全局状态

## 五、审批流程映射（游戏内选项）

以下操作触发kimi-code-cli的审批流程，等待GM（人类或AI GM进程）确认：

| 操作 | 审批理由 | 选项形式 |
|------|---------|---------|
| 解锁核心隐藏层 | GM需确认条件已满足 | "是否允许揭示{条目}？" |
| 使用侦探特权（战人） | 消耗行动点，需确认 | "消耗1行动点验尸？" |
| 宣告角色死亡（触发死亡） | GM需确认条件触发 | "{角色}触发死亡条件，是否执行？" |
| 使用红字/金字 | GM专属能力 | "贝阿朵使用红字：'{内容}'？" |
| 强制行动（失控机制） | GM接管角色 | "对该玩家执行强制行动？" |
| 分组操作 | 每调查阶段必须 | "将存活角色分为以下N组？" |
| 角色切换 | 当前角色死亡后 | "允许玩家切换至{新角色}？" |

## 六、游戏回合推进协议

每个游戏日（Day）按以下阶段推进，由GM进程广播阶段切换消息：

1. `MORNING`：发现尸体/事件（GM广播场景描述）
2. `INVESTIGATION`：调查阶段（GM广播分组，各组行动）
3. `FREE_TALK`：自由交流（全员可发言）
4. `EVENING`：傍晚事件（GM广播）
5. `NIGHT`：夜间事件（GM广播，部分角色可能有私密剧情）
6. `DAY_END`：当日结算（信息条目发放、死亡结算、得分更新）

## 七、角色切换协议

当角色死亡时：
1. GM进程广播 `DEATH` 消息，包含死亡场景描述
2. 玩家进程暂停，等待GM发送 `SWITCH` 消息
3. GM发送 `SWITCH` 消息，指定新角色
4. 玩家重启kimi-code-cli进程，以 `roles/{新角色}/` 为工作目录
5. 新进程继承 `shared/players/{玩家ID}/info_entries.json` 中的已收集信息

## 八、得分与结算

- 角色的信息条目得分存储在 `shared/players/{玩家ID}/score.json`
- 死亡结算时，GM进程锁定该文件并写入最终得分
- 最终对决时，战人进程向GM进程提交推理，GM进程判定得分

## 九、NPC独立进程（Agent模式）

自 kimi-code-cli 源码修改后，NPC可以作为**独立进程**运行，由外部AI Agent通过pipe文件驱动：

```bash
# 启动NPC进程（以贝阿朵莉切为例）
cd umi_client/roles/贝阿朵莉切
kimi --hide-thinking --agent-mode --agent-pipe ../shared/inbox/贝阿朵莉切/agent_pipe.jsonl
```

### NPC进程特性

| 特性 | 说明 |
|------|------|
| `--hide-thinking` | AI思考过程对终端完全不可见，防止玩家窥视 |
| `--agent-mode` | 不从键盘读取输入，从pipe文件读取 |
| `--agent-pipe` | 指定JSONL格式的pipe文件路径 |

### Pipe协议

**输入**（写入 `agent_pipe.jsonl`）：
```json
{"type": "input", "text": "战人向你提问：金藏是怎么死的？", "id": "q1"}
```

**输出**（自动写入 `agent_pipe.jsonl.out`）：
```json
{"type": "status", "phase": "thinking", "id": "q1"}
{"type": "output", "text": "他是被黄金魔女的诅咒所杀...", "tools": [], "id": "q1"}
{"type": "status", "phase": "idle"}
```

### NPC外部驱动器

外部AI Agent（如另一个LLM或脚本）负责：
1. 从消息路由器读取场景信息
2. 生成NPC的"输入"并写入pipe文件
3. 读取NPC的"输出"并分发到其他角色的收件箱

这样可以完全卸载GM进程的NPC计算压力，避免tps瓶颈卡住游戏进度。

## 十、命令速查

```bash
# 启动GM进程
cd umi_client/gm && kimi

# 启动玩家进程（以战人为例）
cd umi_client/roles/右代宫战人 && kimi

# 启动NPC进程（以贝阿朵莉切为例）
cd umi_client/roles/贝阿朵莉切
kimi --hide-thinking --agent-mode --agent-pipe ../shared/inbox/贝阿朵莉切/agent_pipe.jsonl

# 运行消息路由器（在当前机器上）
python umi_client/scripts/router.py --mode local

# 运行消息路由器（联机模式，作为中心服务器）
python umi_client/scripts/router.py --mode server --host 0.0.0.0 --port 8765

# 发送测试消息
python umi_client/scripts/send-msg.py --from GM --to ALL --type system --content "游戏开始！"

# 查看某角色的收件箱
python umi_client/scripts/inbox-viewer.py --character 右代宫战人 --watch
```

---

*「没有爱，就看不见。」*
*但在这个系统中，爱也是受到权限控制的。*
