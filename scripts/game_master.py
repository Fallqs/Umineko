#!/usr/bin/env python3
"""
《海猫鸣泣之时：六轩岛黄昏》GM辅助控制台

帮助人类GM管理游戏状态、执行分组、宣告死亡、追踪得分等。
可以通过此脚本直接修改 game_state.json 和向消息队列发送指令。

用法:
    python game_master.py --status          # 查看当前游戏状态
    python game_master.py --next-phase      # 推进到下一阶段
    python game_master.py --group           # 生成分组方案
    python game_master.py --kill 角色名      # 宣告角色死亡
    python game_master.py --switch 玩家ID 新角色 # 角色切换
    python game_master.py --info 角色名 条目编号 # 发放信息条目
    python game_master.py --broadcast "内容" # 向全员广播消息
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录（scripts的上级）
ROOT = Path(__file__).parent.parent.resolve()
INBOX_DIR = ROOT / "shared" / "inbox"
STATE_PATH = ROOT / "shared" / "game_state.json"

# 角色链配置（来自角色切换版设定）
CHARACTER_CHAINS = {
    "P1": {"chain": "侦探", "characters": ["右代宫战人"]},
    "P2": {"chain": "长房血脉", "characters": ["右代宫朱志香", "右代宫夏妃", "右代宫藏臼"]},
    "P3": {"chain": "次房血脉", "characters": ["右代宫让治", "右代宫雾江", "右代宫留弗夫"]},
    "P4": {"chain": "幼女血脉", "characters": ["右代宫真里亚", "右代宫楼座"]},
    "P5": {"chain": "三位一体·里", "characters": ["嘉音", "乡田"]},
    "P6": {"chain": "三位一体·表", "characters": ["纱音", "熊泽"]},
    "P7": {"chain": "通用备用", "characters": ["右代宫秀吉", "南条医师"]},
}

# 死亡顺序表（角色切换版）
DEATH_SCHEDULE = {
    1: {"day": 2, "character": "右代宫秀吉", "type": "触发", "player": "P7"},
    2: {"day": 3, "character": "右代宫朱志香", "type": "触发", "player": "P2"},
    3: {"day": 4, "character": "右代宫让治", "type": "触发", "player": "P3"},
    4: {"day": 4, "character": "南条医师", "type": "剧情杀", "player": "P7"},
    5: {"day": 5, "character": "右代宫真里亚", "type": "触发", "player": "P4"},
    6: {"day": 5, "character": "右代宫夏妃", "type": "触发", "player": "P2"},
    7: {"day": 6, "character": "嘉音", "type": "强制", "player": "P5"},
    8: {"day": 6, "character": "纱音", "type": "强制", "player": "P6"},
    9: {"day": 6, "character": "右代宫雾江", "type": "强制", "player": "P3"},
    10: {"day": 7, "character": "右代宫藏臼", "type": "触发", "player": "P2"},
    11: {"day": 7, "character": "右代宫留弗夫", "type": "触发", "player": "P3"},
    12: {"day": 7, "character": "右代宫楼座", "type": "触发", "player": "P4"},
    13: {"day": 7, "character": "乡田", "type": "剧情杀", "player": "P5"},
    14: {"day": 7, "character": "熊泽", "type": "剧情杀", "player": "P6"},
}

# GM冷却规则
KILL_COOLDOWN = {
    1: 0,    # Day 1: 无冷却（但新版Day1不杀）
    2: None, # Day 2: 冷却中
    3: 2,    # Day 3: 可用
    4: None, # Day 4: 冷却中
    5: 1,    # Day 5: 可用，冷却1天
    6: 1,    # Day 6: 可用，冷却1天
    7: 0,    # Day 7: 可用，无冷却
}

PHASES = ["SETUP", "MORNING", "INVESTIGATION", "FREE_TALK", "EVENING", "NIGHT", "DAY_END"]


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"[GM] 游戏状态已保存")


def send_message(from_: str, to: str, msg_type: str, content: str,
                 day: int = 0, scene: str = "GM", meta: dict = None):
    """发送消息到 outbox"""
    outbox = INBOX_DIR / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)

    msg = {
        "from": from_,
        "to": to,
        "type": msg_type,
        "content": content,
        "timestamp": datetime.now().isoformat(),
        "day": day,
        "scene": scene,
        "require_approval": False,
        "meta": meta or {},
    }

    ts = msg["timestamp"].replace(":", "-").replace(".", "-")
    filename = f"{ts}_{from_}_{to}_{msg_type}.json"
    filepath = outbox / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(msg, f, ensure_ascii=False, indent=2)
    print(f"[GM] 消息已发送: {from_} → {to} [{msg_type}]")


def show_status(state: dict):
    """显示当前游戏状态"""
    print("=" * 60)
    print("《海猫鸣泣之时：六轩岛黄昏》游戏状态")
    print("=" * 60)
    print(f"当前游戏日: Day {state.get('current_day', 0)}")
    print(f"当前阶段: {state.get('current_phase', 'SETUP')}")
    print(f"阶段描述: {state.get('phase_description', '')}")
    print()

    print("--- 玩家状态 ---")
    players = state.get("players", {})
    for pid, p in players.items():
        status_icon = "🟢" if p.get("status") == "alive" else "🔴" if p.get("status") == "dead" else "⏳"
        print(f"  {status_icon} {pid} | {p.get('current_character', '?')} "
              f"({p.get('chain', '?')}) | 状态: {p.get('status', '?')} "
              f"| 得分: {p.get('score', 0)} | 地点: {p.get('location', '?')}")
    print()

    gm = state.get("gm_state", {})
    print("--- GM状态 ---")
    print(f"  强制击杀可用: {gm.get('kill_available', False)}")
    print(f"  今日已用强制击杀: {gm.get('kill_used_this_day', False)}")
    print(f"  今日红字使用: {gm.get('red_truth_used_today', 0)}/{gm.get('red_truth_limit', 3)}")
    print(f"  今日金字使用: {gm.get('golden_command_used_today', False)}")
    print(f"  实际死亡顺序: {gm.get('death_order_actual', [])}")
    print()

    groups = state.get("groups", {})
    current = groups.get("current_groups", [])
    if current:
        print("--- 当前分组 ---")
        for i, g in enumerate(current, 1):
            print(f"  第{i}组 ({g.get('scene', '?')}): {', '.join(g.get('members', []))}")
    else:
        print("--- 当前无分组 ---")
    print()

    approvals = state.get("pending_approvals", [])
    if approvals:
        print("--- 待审批请求 ---")
        for a in approvals:
            print(f"  [{a.get('type', '?')}] {a.get('from', '?')} → {a.get('description', '?')}")
    else:
        print("--- 无待审批请求 ---")
    print("=" * 60)


def next_phase(state: dict):
    """推进到下一阶段"""
    current = state.get("current_phase", "SETUP")
    day = state.get("current_day", 0)

    if current == "SETUP":
        state["current_day"] = 1
        state["current_phase"] = "MORNING"
        state["phase_description"] = "Day 1 早晨：家族成员抵达六轩岛"
        # 初始化存活角色
        players = state.get("players", {})
        alive = [p["current_character"] for p in players.values()]
        state["characters_alive"] = alive
        state["characters_dead"] = []
        # 重置GM每日状态
        gm = state.get("gm_state", {})
        gm["kill_used_this_day"] = False
        gm["red_truth_used_today"] = 0
        gm["golden_command_used_today"] = False
        cooldown = KILL_COOLDOWN.get(1, 0)
        gm["kill_available"] = cooldown is not None and cooldown == 0
        gm["kill_cooldown_remaining"] = cooldown if cooldown is not None else 0
        state["gm_state"] = gm

    elif current == "DAY_END":
        state["current_day"] = day + 1
        state["current_phase"] = "MORNING"
        state["phase_description"] = f"Day {day+1} 早晨"
        # 重置每日状态
        gm = state.get("gm_state", {})
        gm["kill_used_this_day"] = False
        gm["red_truth_used_today"] = 0
        gm["golden_command_used_today"] = False
        cooldown = KILL_COOLDOWN.get(day + 1, 0)
        gm["kill_available"] = cooldown is not None and cooldown == 0
        gm["kill_cooldown_remaining"] = cooldown if cooldown is not None else 0
        state["gm_state"] = gm
        state["groups"]["current_groups"] = []

    else:
        idx = PHASES.index(current)
        if idx < len(PHASES) - 1:
            state["current_phase"] = PHASES[idx + 1]
            phase_names = {
                "MORNING": f"Day {day} 早晨：发现尸体与事件",
                "INVESTIGATION": f"Day {day} 调查阶段：GM分组",
                "FREE_TALK": f"Day {day} 自由交流：对话与信息交换",
                "EVENING": f"Day {day} 傍晚：晚餐与夜间事件前",
                "NIGHT": f"Day {day} 夜间：私密剧情与暗杀",
                "DAY_END": f"Day {day} 结束：结算与死亡处理",
            }
            state["phase_description"] = phase_names.get(state["current_phase"], "")

    save_state(state)
    show_status(state)

    # 广播阶段切换
    send_message("GM", "ALL", "gm_order",
                 f"阶段切换：{state['current_phase']} - {state['phase_description']}",
                 day=state["current_day"], scene="GM")


def generate_groups(state: dict, manual: str = None):
    """生成分组方案"""
    alive = state.get("characters_alive", [])
    day = state.get("current_day", 1)

    if manual:
        # 手动分组格式: "场景A:角色1,角色2;场景B:角色3,角色4"
        groups = []
        for part in manual.split(";"):
            scene, members = part.split(":")
            groups.append({"scene": scene.strip(), "members": [m.strip() for m in members.split(",")]})
    else:
        # 自动分组（简化版）
        # 规则：2-3组，每组2-4人
        # 纱音/嘉音不可同组
        # 战人尽量不与逻辑型角色同组

        chars = alive.copy()
        random.shuffle(chars)

        # 确保纱音和嘉音分开
        shannon = "纱音" if "纱音" in chars else None
        kanon = "嘉音" if "嘉音" in chars else None

        groups = []
        if len(chars) <= 4:
            groups = [{"scene": random.choice(["本馆", "别馆", "神社"]), "members": chars}]
        elif len(chars) <= 6:
            mid = len(chars) // 2
            groups = [
                {"scene": random.choice(["本馆", "书房"]), "members": chars[:mid]},
                {"scene": random.choice(["别馆", "庭院"]), "members": chars[mid:]},
            ]
        else:
            # 分3组
            g1 = chars[:3]
            g2 = chars[3:6]
            g3 = chars[6:]
            groups = [
                {"scene": "本馆", "members": g1},
                {"scene": "别馆", "members": g2},
                {"scene": "神社", "members": g3},
            ]

        # 检查纱音/嘉音同组
        for g in groups:
            if "纱音" in g["members"] and "嘉音" in g["members"]:
                # 移动嘉音到另一组
                g["members"].remove("嘉音")
                for other in groups:
                    if other is not g and len(other["members"]) < 4:
                        other["members"].append("嘉音")
                        break

    state["groups"]["current_groups"] = groups
    state["groups"]["group_history"].append({
        "day": day,
        "phase": state.get("current_phase", "INVESTIGATION"),
        "groups": groups
    })
    save_state(state)

    print(f"[GM] Day {day} 分组方案已生成：")
    for i, g in enumerate(groups, 1):
        print(f"  第{i}组 ({g['scene']}): {', '.join(g['members'])}")

    # 广播分组
    group_text = "\n".join([f"第{i}组 ({g['scene']}): {', '.join(g['members'])}"
                            for i, g in enumerate(groups, 1)])
    send_message("GM", "ALL", "gm_order",
                 f"调查阶段分组：\n{group_text}",
                 day=day, scene="GM")


def kill_character(state: dict, character: str, cause: str = "GM强制击杀"):
    """宣告角色死亡"""
    alive = state.get("characters_alive", [])
    dead = state.get("characters_dead", [])

    if character not in alive:
        print(f"[GM] 错误：{character} 不在存活列表中")
        return

    alive.remove(character)
    dead.append(character)
    state["characters_alive"] = alive
    state["characters_dead"] = dead

    # 更新玩家状态
    players = state.get("players", {})
    for pid, p in players.items():
        if p.get("current_character") == character:
            p["status"] = "dead"
            # 这里应该计算最终得分，简化版跳过
            break

    # 更新GM死亡顺序
    gm = state.get("gm_state", {})
    gm["death_order_actual"] = dead
    state["gm_state"] = gm

    save_state(state)
    print(f"[GM] {character} 已死亡：{cause}")

    # 广播死亡
    send_message("GM", "ALL", "gm_order",
                 f"【死亡宣告】{character} 已死亡。\n死因：{cause}",
                 day=state.get("current_day", 0), scene="GM")

    # 发送SWITCH消息给对应玩家
    for pid, p in players.items():
        if p.get("current_character") == character:
            chain = CHARACTER_CHAINS.get(pid, {}).get("characters", [])
            current_idx = chain.index(character) if character in chain else -1
            if current_idx >= 0 and current_idx + 1 < len(chain):
                next_char = chain[current_idx + 1]
                send_message("GM", character, "SWITCH",
                             f"你的角色 {character} 已死亡。请切换到新角色：{next_char}\n"
                             f"新工作目录: roles/{next_char}/",
                             day=state.get("current_day", 0), scene="GM",
                             meta={"switch_to": next_char, "player_id": pid})
            else:
                send_message("GM", character, "SWITCH",
                             f"你的角色链已结束。你已进入观剧模式。",
                             day=state.get("current_day", 0), scene="GM",
                             meta={"eliminated": True, "player_id": pid})
            break


def switch_character(state: dict, player_id: str, new_character: str):
    """手动执行角色切换"""
    players = state.get("players", {})
    if player_id not in players:
        print(f"[GM] 错误：玩家 {player_id} 不存在")
        return

    old = players[player_id]["current_character"]
    players[player_id]["current_character"] = new_character
    players[player_id]["status"] = "alive"

    # 更新存活列表
    alive = state.get("characters_alive", [])
    if old in alive:
        alive.remove(old)
    if new_character not in alive:
        alive.append(new_character)
    state["characters_alive"] = alive

    save_state(state)
    print(f"[GM] {player_id}: {old} → {new_character}")

    send_message("GM", new_character, "SWITCH",
                 f"角色切换完成。你现在是 {new_character}。",
                 day=state.get("current_day", 0), scene="GM",
                 meta={"switched_from": old, "switched_to": new_character, "player_id": player_id})


def give_info(state: dict, character: str, entry_id: str, entry_content: str = "", score: int = 0):
    """向角色发放信息条目"""
    players = state.get("players", {})
    for pid, p in players.items():
        if p.get("current_character") == character:
            entries = p.get("info_entries", [])
            if entry_id not in entries:
                entries.append(entry_id)
                p["info_entries"] = entries
                p["score"] = p.get("score", 0) + (score or 1)
            break

    save_state(state)
    print(f"[GM] 信息条目 [{entry_id}] 已发放给 {character}")

    send_message("GM", character, "gm_order",
                 f"【获得信息条目】{entry_id}\n{entry_content}",
                 day=state.get("current_day", 0), scene="GM",
                 meta={"info_entry": entry_id, "score": score})


def broadcast(state: dict, content: str, msg_type: str = "system"):
    """向全员广播"""
    send_message("GM", "ALL", msg_type, content,
                 day=state.get("current_day", 0), scene="GM")
    print(f"[GM] 广播: {content[:80]}...")


def main():
    parser = argparse.ArgumentParser(description="海猫GM辅助控制台")
    parser.add_argument("--status", action="store_true", help="显示游戏状态")
    parser.add_argument("--next-phase", action="store_true", help="推进到下一阶段")
    parser.add_argument("--group", action="store_true", help="生成分组方案")
    parser.add_argument("--group-manual", type=str, help="手动分组: '场景A:角色1,角色2;场景B:角色3'")
    parser.add_argument("--kill", type=str, help="宣告角色死亡")
    parser.add_argument("--kill-cause", type=str, default="GM强制击杀", help="死亡原因")
    parser.add_argument("--switch", dest="switch_cmd", type=str, help="切换角色: 玩家ID,新角色")
    parser.add_argument("--info", type=str, help="发放信息: 角色名,条目编号")
    parser.add_argument("--info-content", type=str, default="", help="信息内容")
    parser.add_argument("--info-score", type=int, default=1, help="信息分值")
    parser.add_argument("--broadcast", type=str, help="广播消息")
    parser.add_argument("--broadcast-type", type=str, default="system", help="广播消息类型")
    parser.add_argument("--init", action="store_true", help="初始化游戏状态")

    args = parser.parse_args()

    if args.init:
        # 重置游戏状态
        print("[GM] 初始化游戏状态...")
        if STATE_PATH.exists():
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            state["status"] = "SETUP"
            state["current_day"] = 0
            state["current_phase"] = "SETUP"
            state["characters_alive"] = []
            state["characters_dead"] = []
            state["groups"]["current_groups"] = []
            for p in state.get("players", {}).values():
                p["status"] = "waiting"
                p["info_entries"] = []
                p["score"] = 0
            save_state(state)
            print("[GM] 游戏状态已重置")
        return

    state = load_state()

    if args.status or len(sys.argv) == 1:
        show_status(state)
        return

    if args.next_phase:
        next_phase(state)

    if args.group or args.group_manual:
        generate_groups(state, args.group_manual)

    if args.kill:
        kill_character(state, args.kill, args.kill_cause)

    if args.switch_cmd:
        parts = args.switch_cmd.split(",")
        if len(parts) == 2:
            switch_character(state, parts[0].strip(), parts[1].strip())
        else:
            print("[GM] 格式错误，应为: 玩家ID,新角色")

    if args.info:
        parts = args.info.split(",")
        if len(parts) >= 2:
            give_info(state, parts[0].strip(), parts[1].strip(), args.info_content, args.info_score)
        else:
            print("[GM] 格式错误，应为: 角色名,条目编号")

    if args.broadcast:
        broadcast(state, args.broadcast, args.broadcast_type)


if __name__ == "__main__":
    main()
