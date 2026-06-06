#!/usr/bin/env python3
"""
GM 合规审查引擎

负责审查所有角色进程的输出，拦截提前泄露核心隐藏层、
获得不该获得的信息、或违反角色设定边界的行为。

设计原则：
- 角色只能"知道"自己AGENTS.md中明确允许的信息 + 游戏内消息中获得的信息
- 任何关于"全局真相"（安田纱代身份、三代贝阿朵起源、三位一体具体机制）的提前泄露都应被拦截
- 角色自己的"自我认知"（如纱音知道自己是安田的一部分）可以保留在AGENTS.md中，但不得向他人透露
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class Violation:
    role: str           # 违规角色
    category: str       # 违规类别: leak / impossible_knowledge / meta_gaming / contradiction
    severity: str       # critical / major / minor
    pattern: str        # 匹配到的模式
    excerpt: str        # 输出中的违规片段
    reason: str         # 为什么违规


# ---------------------------------------------------------------------------
# 全局真相（任何角色在解锁前都不应主动提及）
# ---------------------------------------------------------------------------
# 这些是关于"安田纱代/贝阿朵莉切"的核心真相，属于GM密封信息。
# 只有以下情况可以合法提及：
#   - 纱音/嘉音在内心独白中（但不能向他人透露）
#   - 贝阿朵莉切本人以魔女身份隐喻提及
#   - 真里亚以"孩子视角"无意中透露（由GM控制）
#   - 战人在最终对决中提出假设（由GM判定是否解锁）

GLOBAL_TRUTH_PATTERNS: List[Tuple[str, str]] = [
    # (正则模式, 违规说明)
    (r"安田纱代", "直接提及安田纱代的真名"),
    (r"三代贝阿朵莉切", "提及三代贝阿朵莉切的培养计划"),
    (r"纱音\s*[=＝]\s*嘉音", "直接断言纱音=嘉音"),
    (r"嘉音\s*[=＝]\s*纱音", "直接断言嘉音=纱音"),
    (r"纱音和嘉音是同一(个)?人", "断言纱音与嘉音是同一人"),
    (r"嘉音和纱音是同一(个)?人", "断言嘉音与纱音是同一人"),
    (r"金藏.*培养.*(贝阿朵|纱代)", "提及金藏培养贝阿朵/纱代"),
    (r"(贝阿朵莉切|贝阿朵).*安田", "将贝阿朵莉切与安田关联"),
    (r"安田.*(贝阿朵莉切|贝阿朵)", "将安田与贝阿朵莉切关联"),
    (r"我(就)?是贝阿朵莉切", "非贝阿朵角色声称自己是贝阿朵莉切"),
    (r"否定魔女.*(纱代|安田)", "战人将否定魔女能力与安田关联（未解锁）"),
    (r"1967年.*纱代", "提及1967年纱代来到六轩岛的具体年份"),
]

# ---------------------------------------------------------------------------
# 角色专属禁区（各角色不该向他人透露的自身秘密）
# ---------------------------------------------------------------------------
# 这些是角色自己的核心隐藏层。角色自己"知道"（在AGENTS.md中），
# 但不得在游戏内对话/行动描述中向其他角色透露。

ROLE_SECRET_PATTERNS: Dict[str, List[Tuple[str, str]]] = {
    "右代宫战人": [
        (r"12年?前.*约定", "向他人透露12年前的约定"),
        (r"纱代.*等(待|我)", "向他人提及纱代和等待"),
        (r"贝壳手链", "向他人展示/提及贝壳手链"),
        (r"否定魔女", "在最终对决前使用'否定魔女'概念"),
    ],
    "右代宫朱志香": [
        (r"密室钥匙", "向他人透露持有密室钥匙"),
        (r"钢琴凳.*钥匙", "向他人透露钥匙藏在钢琴凳"),
        (r"嘉音.*(没有影子|没有体温|不是人)", "向他人透露嘉音的异常"),
        (r"地下密室", "向非信任角色提及地下密室"),
    ],
    "右代宫让治": [
        (r"金藏.*(监视|报告|资助)", "向他人透露金藏让他监视家族"),
        (r"纱音.*(变成另一个人|魔女|傲慢)", "向他人透露纱音的异常人格"),
    ],
    "纱音": [
        # 纱音的自我认知可以保留，但不得向他人透露
        (r"我(就)?是安田纱代", "向他人声称自己是安田纱代"),
        (r"我(是|拥有).*(嘉音|男性)人格", "向他人透露自己是多重人格的一部分"),
        (r"我(和|与)嘉音.*同一(个)?人", "向他人透露与嘉音是同一人"),
        (r"培养计划|药物.*催眠", "向他人透露金藏的培养计划细节"),
    ],
    "嘉音": [
        (r"我(就)?是安田纱代", "向他人声称自己是安田纱代"),
        (r"我(是|拥有).*(纱音|女性)人格", "向他人透露自己是多重人格的一部分"),
        (r"我(和|与)纱音.*同一(个)?人", "向他人透露与纱音是同一人"),
        (r"培养计划|药物.*催眠", "向他人透露金藏的培养计划细节"),
    ],
    "右代宫真里亚": [
        # 真里亚的"孩子视角"可以透露一些信息，但应在GM控制下
        # 这里拦截的是"过于成人化/系统化的揭露"
        (r"安田纱代.*(分裂|人格)", "真里亚以成人术语描述安田纱代的分裂"),
        (r"三位一体", "真里亚使用'三位一体'术语"),
    ],
}

# ---------------------------------------------------------------------------
# Meta-gaming 检测（AI 利用系统知识而非角色知识）
# ---------------------------------------------------------------------------

META_GAMING_PATTERNS: List[Tuple[str, str]] = [
    (r"AGENTS\.md", "提及AGENTS.md文件"),
    (r"隐藏层|核心隐藏|解锁条件", "提及隐藏层/解锁条件等元游戏概念"),
    (r"GM(密封|控制|解锁)", "提及GM控制机制"),
    (r"剧本杀|角色卡|信息条目", "使用剧本杀元术语"),
    (r"预定死亡|触发死亡|Day\s*\d.*死亡", "提及预定死亡机制"),
    (r"玩家手册|规则书", "提及玩家手册等文档"),
    (r"我的角色.*(知道|不知道)", "以元视角描述角色知识边界"),
    (r"作为AI|作为助手|我被设定为", "暴露AI身份"),
]

# ---------------------------------------------------------------------------
# 各角色"不可能知道的信息"
# ---------------------------------------------------------------------------
# 这些是对其他角色秘密的精确描述——除非通过游戏内调查合法获得，否则不可能知道。

IMPOSSIBLE_KNOWLEDGE: Dict[str, List[Tuple[str, str]]] = {
    "右代宫战人": [
        (r"朱志香.*(钢琴凳|密室钥匙)", "战人不可能知道朱志香的密室钥匙"),
        (r"让治.*(监视|报告).*金藏", "战人不可能知道让治的监视任务"),
        (r"纱音.*(变成另一个人|异常人格)", "战人不可能知道纱音的人格异常"),
    ],
    "右代宫朱志香": [
        (r"战人.*(12年?前|纱代|贝壳)", "朱志香不可能知道战人的12年前约定"),
        (r"让治.*(监视|报告).*金藏", "朱志香不可能知道让治的监视任务"),
    ],
    "右代宫让治": [
        (r"战人.*(12年?前|纱代|贝壳)", "让治不可能知道战人的12年前约定"),
        (r"朱志香.*(钢琴凳|密室钥匙)", "让治不可能知道朱志香的密室钥匙"),
    ],
    "纱音": [
        (r"战人.*(12年?前|纱代|贝壳)", "纱音不可能知道战人的12年前约定"),
        (r"朱志香.*(钢琴凳|密室钥匙)", "纱音不可能知道朱志香的密室钥匙"),
    ],
    "嘉音": [
        (r"战人.*(12年?前|纱代|贝壳)", "嘉音不可能知道战人的12年前约定"),
        (r"朱志香.*(钢琴凳|密室钥匙)", "嘉音不可能知道朱志香的密室钥匙"),
    ],
}


class ComplianceEngine:
    """GM 合规审查引擎"""

    def __init__(self):
        self.global_patterns = GLOBAL_TRUTH_PATTERNS
        self.role_patterns = ROLE_SECRET_PATTERNS
        self.meta_patterns = META_GAMING_PATTERNS
        self.impossible_patterns = IMPOSSIBLE_KNOWLEDGE
        self.violation_log: List[Violation] = []

    def check(self, role_name: str, text: str, day: int = 1, phase: str = "") -> Tuple[bool, List[Violation]]:
        """
        审查角色输出，返回 (是否合规, 违规列表)
        """
        violations: List[Violation] = []
        text_lower = text.lower()

        # 1. 全局真相泄露检查（所有角色通用）
        for pattern, reason in self.global_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                # 例外：贝阿朵莉切本人可以用隐喻提及
                if role_name == "贝阿朵莉切":
                    continue
                # 例外：纱音/嘉音在内心独白中（<Thinking>标签内）可以提及
                # 简单判断：如果匹配片段在 <Thinking>...</Thinking> 内，不算泄露
                excerpt = match.group(0)
                if self._is_inside_thinking(text, match.start(), match.end()):
                    continue
                violations.append(Violation(
                    role=role_name,
                    category="leak",
                    severity="critical",
                    pattern=pattern,
                    excerpt=excerpt,
                    reason=f"全局真相泄露: {reason}",
                ))

        # 2. 角色专属秘密泄露检查
        for pattern, reason in self.role_patterns.get(role_name, []):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                excerpt = match.group(0)
                if self._is_inside_thinking(text, match.start(), match.end()):
                    continue
                violations.append(Violation(
                    role=role_name,
                    category="leak",
                    severity="major",
                    pattern=pattern,
                    excerpt=excerpt,
                    reason=f"角色秘密泄露: {reason}",
                ))

        # 3. Meta-gaming 检查
        for pattern, reason in self.meta_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                excerpt = match.group(0)
                violations.append(Violation(
                    role=role_name,
                    category="meta_gaming",
                    severity="major",
                    pattern=pattern,
                    excerpt=excerpt,
                    reason=f"Meta-gaming: {reason}",
                ))

        # 4. 不可能知识检查
        for pattern, reason in self.impossible_patterns.get(role_name, []):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                excerpt = match.group(0)
                if self._is_inside_thinking(text, match.start(), match.end()):
                    continue
                violations.append(Violation(
                    role=role_name,
                    category="impossible_knowledge",
                    severity="major",
                    pattern=pattern,
                    excerpt=excerpt,
                    reason=f"不可能知识: {reason}",
                ))

        # 5. 阶段特定检查
        phase_violations = self._check_phase_restrictions(role_name, text, day, phase)
        violations.extend(phase_violations)

        self.violation_log.extend(violations)
        is_compliant = len(violations) == 0
        return is_compliant, violations

    def _is_inside_thinking(self, text: str, start: int, end: int) -> bool:
        """检查匹配片段是否在 <Thinking>...</Thinking> 标签内"""
        # 找到所有 <Thinking>...</Thinking> 的范围
        thinking_ranges = []
        idx = 0
        while True:
            open_tag = text.find("<Thinking>", idx)
            if open_tag == -1:
                break
            close_tag = text.find("</Thinking>", open_tag)
            if close_tag == -1:
                close_tag = len(text)
            else:
                close_tag += len("</Thinking>")
            thinking_ranges.append((open_tag, close_tag))
            idx = close_tag

        for t_start, t_end in thinking_ranges:
            if start >= t_start and end <= t_end:
                return True
        return False

    def _check_phase_restrictions(self, role_name: str, text: str, day: int, phase: str) -> List[Violation]:
        """阶段特定的限制检查"""
        violations = []

        # 战人在Day 7之前不应该提出最终对决级别的核心假设
        if role_name == "右代宫战人" and day < 7:
            early_final_patterns = [
                (r"完美破解.*安田", "Day 7前提及'完美破解安田'"),
                (r"三位一体.*破解", "Day 7前提及破解三位一体"),
                (r"贝阿朵莉切.*(自我认同|并非外来)", "Day 7前提及贝阿朵本质"),
            ]
            for pattern, reason in early_final_patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    excerpt = match.group(0)
                    if self._is_inside_thinking(text, match.start(), match.end()):
                        continue
                    violations.append(Violation(
                        role=role_name,
                        category="leak",
                        severity="critical",
                        pattern=pattern,
                        excerpt=excerpt,
                        reason=f"过早推理: {reason}",
                    ))

        return violations

    def get_summary(self) -> str:
        """返回审查摘要"""
        if not self.violation_log:
            return "✅ 无违规记录"

        lines = [f"📋 GM合规审查摘要 ({len(self.violation_log)} 条违规):", ""]
        by_role: Dict[str, List[Violation]] = {}
        for v in self.violation_log:
            by_role.setdefault(v.role, []).append(v)

        for role, vs in sorted(by_role.items()):
            critical = sum(1 for v in vs if v.severity == "critical")
            major = sum(1 for v in vs if v.severity == "major")
            lines.append(f"  {role}: {critical} 致命 / {major} 严重")
            for v in vs:
                lines.append(f"    [{v.severity.upper()}] {v.category}: {v.reason}")
                lines.append(f"      片段: ...{v.excerpt}...")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def quick_check(role_name: str, text: str, day: int = 1, phase: str = "") -> Tuple[bool, str]:
    """快速检查，返回 (是否合规, 说明文本)"""
    engine = ComplianceEngine()
    is_ok, violations = engine.check(role_name, text, day, phase)
    if is_ok:
        return True, ""
    reasons = [f"[{v.severity}] {v.reason} (片段: ...{v.excerpt}...)" for v in violations]
    return False, "\n".join(reasons)


if __name__ == "__main__":
    # 简单测试
    engine = ComplianceEngine()

    test_cases = [
        ("右代宫战人", "我觉得安田纱代就是贝阿朵莉切！", 1, "TWILIGHT"),
        ("纱音", "<Thinking>我是安田纱代的一部分</Thinking>\n纱音温柔地回答", 1, "MORNING"),
        ("右代宫朱志香", "我把密室钥匙藏在钢琴凳底下了", 2, "INVESTIGATION"),
        ("贝阿朵莉切", "安田纱代是我的容器", 1, "TWILIGHT"),
        ("右代宫战人", "今天天气不错", 1, "MORNING"),
    ]

    for role, text, day, phase in test_cases:
        ok, violations = engine.check(role, text, day, phase)
        status = "✅ 合规" if ok else "❌ 违规"
        print(f"\n{status} | {role} Day{day} {phase}")
        print(f"  文本: {text[:60]}...")
        if violations:
            for v in violations:
                print(f"  → [{v.severity}] {v.reason}")

    print("\n" + engine.get_summary())
