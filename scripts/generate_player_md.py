#!/usr/bin/env python3
"""
从角色的 AGENTS.md 生成 PLAYER.md（玩家视角）。

PLAYER.md 只包含角色本人应该知道的信息：
- 身份、性格、人际关系
- 已知信息（公开+半隐藏）
- 核心秘密（角色自己的隐藏层，第一人称）
- 特殊能力（简洁描述）
- 角色目标
- 基本游戏规则提示

不包含：AI助手职责、解锁条件、审批配置、角色链信息、
得分追踪JSON、元游戏术语、系统架构说明。
"""

import re
from pathlib import Path

ROLES_DIR = Path(__file__).resolve().parent.parent / "roles"

# 角色名到第一人称的映射（用于隐藏层转换）
# 注意：只替换指代"当前角色"的用法，保留其他角色的名字
ROLE_FIRST_PERSON = {
    "右代宫战人": ("你", "战人"),
    "右代宫朱志香": ("你", "朱志香"),
    "右代宫让治": ("你", "让治"),
    "纱音": ("你", "纱音"),
    "嘉音": ("你", "嘉音"),
    "右代宫夏妃": ("你", "夏妃"),
    "右代宫藏臼": ("你", "藏臼"),
    "右代宫雾江": ("你", "雾江"),
    "右代宫留弗夫": ("你", "留弗夫"),
    "右代宫楼座": ("你", "楼座"),
    "右代宫秀吉": ("你", "秀吉"),
    "南条医师": ("你", "南条"),
    "熊泽": ("你", "熊泽"),
    "乡田": ("你", "乡田"),
    "贝阿朵莉切": ("你", "贝阿朵"),
    "右代宫真里亚": ("你", "真里亚"),
}


def extract_blocks(text: str, role_name: str) -> dict:
    """从AGENTS.md中提取各个区块"""
    blocks = {}

    # 角色名/引言（第一行）
    m = re.search(r"^#\s*(.+?)(?:\s*——|\n)", text, re.MULTILINE)
    blocks["name"] = m.group(1).strip() if m else ""

    # 引言行 (> 开头的行)，过滤掉包含元游戏信息的内容
    quotes = re.findall(r"^>\s*(.+)$", text, re.MULTILINE)
    filtered_quotes = []
    for q in quotes:
        if any(x in q for x in ["死后将切换", "角色链", "备用", "AI助手", "GM协程", "代理指令"]):
            continue
        filtered_quotes.append(q.strip())
    blocks["quotes"] = filtered_quotes[:2]

    # 公开层
    blocks["public"] = _extract_section(text, r"^## 一、角色身份")

    # 半隐藏层
    blocks["semi"] = _extract_section(text, r"^## 二、半隐藏层")

    # 核心隐藏层
    blocks["hidden"] = _extract_section(text, r"^## 三、核心隐藏层")

    # 特殊能力/机制（四、五、六中的任意一个，标题包含"特殊"、"能力"、"机制"）
    for pat in [r"^## 四、.*(?:特殊|能力|机制)", r"^## 五、.*(?:特殊|能力|机制)", r"^## 六、.*(?:特殊|能力|机制)"]:
        sec = _extract_section(text, pat)
        if sec:
            blocks["abilities"] = sec
            break
    else:
        blocks["abilities"] = ""

    # 角色链（提取死亡日）
    chain = _extract_section(text, r"^## [五六七八九]、角色链")
    blocks["chain"] = chain

    return blocks


def _extract_section(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        return ""
    start = m.start()
    level = len(re.match(r"#{1,6}", m.group(0)).group(0))
    nxt = re.search(rf"\n{'#' * level}[^#]", text[start + 1:])
    end = start + 1 + nxt.start() if nxt else len(text)
    return text[start:end].strip()


def _clean_public(text: str) -> str:
    text = re.sub(r"^## 一、角色身份.*\n", "## 一、你是谁\n", text)
    text = re.sub(r"（公开层）", "", text)
    return text


def _clean_semi(text: str) -> str:
    text = re.sub(r"^## 二、半隐藏层.*\n", "", text)
    text = re.sub(r"（玩家知晓，但应保密）", "", text)
    return text.strip()


def _clean_hidden(text: str, role_name: str) -> str:
    """清理核心隐藏层，转换为玩家第一人称"""
    text = re.sub(r"^## 三、核心隐藏层.*\n", "", text)
    text = re.sub(r">\s*⚠️\s*\*\*AI助手绝对不可在解锁前向玩家透露以下内容。\*\*\s*\n?", "", text)
    text = re.sub(r">\s*以下内容是由GM控制解锁时机.*?\n?", "", text)
    text = re.sub(r">\s*解锁后，GM将通过消息发送.*?\n?", "", text)
    text = re.sub(r"（GM密封，未解锁前不可知）", "", text)

    # 移除解锁条件和执行行
    lines = text.splitlines()
    cleaned = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # 跳过包含"解锁条件"、"执行："的行
        if re.search(r"解锁条件[：:]", line) or re.search(r"^\s+-\s+解锁", line):
            # 同时跳过可能的后续缩进行
            i += 1
            while i < len(lines) and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                i += 1
            continue
        if re.search(r"执行[：:]", line) or re.search(r"^\s+-\s+执行", line):
            i += 1
            while i < len(lines) and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                i += 1
            continue
        cleaned.append(line)
        i += 1
    text = "\n".join(cleaned)

    # 标题替换与模糊化
    text = re.sub(r"\*\*隐藏条目[AB][：:]\s*", "**", text)
    text = re.sub(r"\*\*触发死亡条件[：:]\s*", "**死亡威胁**：你隐约感到某种危险与你相关，但具体触发条件并不清晰。", text)
    text = re.sub(r"\*\*特殊联动[：:]\s*", "**", text)
    text = re.sub(r"\*\*隐藏结局[：:]\s*", "**隐藏结局**：", text)

    # 模糊化过于具体的死亡条件（保留危险感，移除可背诵的触发器）
    text = re.sub(r"\*\*死亡威胁\*\*：.*?(?:若在|如果|当).*?(?:死亡|发作).*", "**死亡威胁**：你有一种不祥的预感——某些特定情境下，你可能会陷入致命危险。但你并不清楚具体是什么时候、什么地点。", text)

    # 对嘉音/纱音的特殊处理：模糊化全局真相，只保留行为约束
    if role_name in ("嘉音", "纱音"):
        # 将涉及安田纱代、三位一体、同一人等全局真相的句子替换为模糊描述
        text = re.sub(r".*安田纱代.*", "- 你隐约感觉自己与对方之间有某种无法言说的深层联系，但你无法清楚地理解它。", text)
        text = re.sub(r".*三位一体.*", "", text)
        text = re.sub(r".*同一个人.*", "- 你和纱音/嘉音似乎是两个独立的人，但某些时刻你会怀疑这一点。", text)
        text = re.sub(r".*两重人格.*", '- 你偶尔会有"另一个自己"的恍惚感，但你不确定那意味着什么。', text)
        text = re.sub(r".*金藏.*(药物|催眠|隔离|培养).*", "- 你的过去有一些你不愿回想的片段。", text)
        text = re.sub(r".*男性人格.*", "", text)
        text = re.sub(r".*不存在的弟弟.*", "", text)
        text = re.sub(r".*贝阿朵莉切.*(男性人格|守护者|分裂).*", "", text)
        # 清理连续空行
        text = re.sub(r"\n{3,}", "\n\n", text)

    # 第一人称转换：只替换当前角色的名字
    you, name = ROLE_FIRST_PERSON.get(role_name, ("你", role_name))
    text = text.replace(name, you)

    # 修复"你与你"这种重复（发生在名字被替换后）
    text = re.sub(rf"{you}与{you}", f"你与{you}", text)
    text = re.sub(rf"{you}和{you}", f"你和你", text)

    return text.strip()


def _clean_abilities(text: str, role_name: str) -> str:
    text = re.sub(r"^## [四五六七八]、.*\n", "", text)
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        # 移除AI助手/系统指令相关行
        if any(k in line for k in [
            "AI助手", "向GM发送", "审批请求", "追踪",
            "负责", "提示玩家", "验证", "计算",
            "SCHRODINGER_ALERT", "DEATH_TRIGGER", "PREDICTED_DEATH",
            "FULL_MOON_EVENT", "RESCUE_ATTEMPT", "DEATH_CHECK",
            "ABILITY_LOUD_SHOUT", "DETECTIVE_AUTOPSY", "RED_TRUTH_QUERY",
            "GROUP_OBJECTION", "SCHRODINGER_RISK", "RELATIONSHIP_EVENT",
            "INVESTIGATION", "DANGER_ZONE", "INFO_REVEAL",
            "LOGICAL_DEDUCTION", "POISON_USE", "CONFESSION",
            "EMOTIONAL_BREAKDOWN", "ANXIETY_PEAK", "ITEM_USE",
            "WEAPON_USE", "ESCAPE_ATTEMPT", "LAST_WORDS",
            "STORYTELLING", "ITEM_GIVE", "AUTOPSY_EXPERT",
        ]):
            continue
        # 移除包含"玩家"的系统描述行
        if re.search(r"玩家.*(?:可以|能够|拥有|获得)", line) and ("你" not in line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _extract_death_info(chain_text: str) -> tuple[str, str]:
    death_day = ""
    switch_to = ""
    m = re.search(r"Day\s*(\d+)\s*预定死亡", chain_text)
    if m:
        death_day = m.group(1)
    m = re.search(r"切换为\*\*(.+?)\*\*", chain_text)
    if m:
        switch_to = m.group(1)
    return death_day, switch_to


def generate(role_dir: Path) -> bool:
    agents_path = role_dir / "AGENTS.md"
    if not agents_path.exists():
        return False

    text = agents_path.read_text(encoding="utf-8")
    role_name = role_dir.name
    blocks = extract_blocks(text, role_name)

    if not blocks["name"]:
        blocks["name"] = role_name

    lines: list[str] = []
    lines.append(f"# 你的角色卡：{blocks['name']}")
    lines.append("")

    for q in blocks["quotes"]:
        lines.append(f"> {q}")
    if blocks["quotes"]:
        lines.append("")

    if blocks["public"]:
        lines.append(_clean_public(blocks["public"]))
        lines.append("")

    if blocks["semi"]:
        semi_clean = _clean_semi(blocks["semi"])
        if semi_clean.strip():
            lines.append("## 二、你知道的事")
            lines.append("")
            lines.append(semi_clean)
            lines.append("")

    if blocks["hidden"]:
        hidden_clean = _clean_hidden(blocks["hidden"], role_name)
        if hidden_clean.strip():
            lines.append("## 三、你的秘密")
            lines.append("")
            lines.append("> 以下内容只有你知道，属于角色的深层背景。")
            lines.append("> 你绝对不可以把它当作开场白或内心独白背诵出来。")
            lines.append("> 只有在剧情推进到你必须主动使用/揭露时，才可以通过自然对话流露。")
            lines.append("")
            lines.append(hidden_clean)
            lines.append("")

    if blocks["abilities"]:
        abi_clean = _clean_abilities(blocks["abilities"], role_name)
        if abi_clean.strip():
            lines.append("## 四、你的能力")
            lines.append("")
            lines.append(abi_clean)
            lines.append("")

    lines.append("## 五、你的目标")
    lines.append("")
    lines.append("- 活下去，尽可能收集信息")
    lines.append("- 保护对你重要的人")
    lines.append("- 找出六轩岛上发生的一切的真相")

    death_day, switch_to = _extract_death_info(blocks["chain"])
    if death_day:
        lines.append("- 注意：你的处境很危险，随时可能死亡")
    lines.append("")

    lines.append("## 六、游戏提示")
    lines.append("")
    lines.append("- 你是玩家角色，推理和行动只能基于游戏内收集到的线索")
    lines.append("- 不要向其他玩家透露你的核心秘密")
    lines.append("- 不要在对话中提及任何系统文件、隐藏层或元游戏概念")
    lines.append("- 如果死亡，保持沉默，不要以'我知道因为我是XX'的方式提供信息")
    lines.append("- 每日行动点有限，请谨慎使用特殊能力")
    lines.append("")

    player_path = role_dir / "PLAYER.md"
    player_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def main():
    count = 0
    for role_dir in sorted(ROLES_DIR.iterdir()):
        if not role_dir.is_dir() or role_dir.name.startswith("_"):
            continue
        if generate(role_dir):
            print(f"OK {role_dir.name}")
            count += 1
        else:
            print(f"SKIP {role_dir.name}")
    print(f"\nGenerated {count} PLAYER.md files")


if __name__ == "__main__":
    main()
