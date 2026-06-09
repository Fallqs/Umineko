"""
NPC Prompt 自动生成器

从角色的 AGENTS.md + PLAYER.md + GM.md 中提取信息，
自动生成供 npc mode 使用的角色行为提示。

设计原则：
1. 不依赖严格的markdown解析，使用章节标题关键字匹配
2. 优先从 PLAYER.md 提取"公开层"和"扮演提示"
3. 从 AGENTS.md 提取"特殊机制"和"角色身份"
4. 所有角色必须保持相同格式的文档结构
"""

import re
from pathlib import Path
from typing import List, Optional


def _extract_section(text: str, *possible_headers: str) -> Optional[str]:
    """从markdown文本中提取指定章节的内容。
    
    支持多种标题级别（## 或 ###）和变体名称。
    返回从章节标题开始到下一个同级或更高级标题之间的内容。
    """
    for header in possible_headers:
        # 匹配 ## 标题 或 ### 标题（前后可能有空格）
        pattern = rf'(?m)^##+\s*{re.escape(header)}.*?\n(.*?)(?=\n##|\Z)'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            content = match.group(1).strip()
            # 清理过多的空行
            content = re.sub(r'\n{3,}', '\n\n', content)
            return content
    return None


def _extract_bullet_lines(text: str, max_lines: int = 5) -> str:
    """从文本中提取列表项的前几行，作为简述。"""
    lines = [l.strip('- *').strip() for l in text.split('\n') if l.strip().startswith(('- ', '* '))]
    return '\n'.join(lines[:max_lines])


def _first_paragraph(text: str, max_chars: int = 300) -> str:
    """提取第一段非空文本，截断到指定长度。"""
    lines = text.split('\n')
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and not stripped.startswith('>'):
            if len(stripped) > max_chars:
                return stripped[:max_chars] + "..."
            return stripped
    return ""


class NpcPromptBuilder:
    """根据角色文档自动生成NPC行为提示。"""

    def __init__(self, role_dir: Path):
        self.role_dir = Path(role_dir)
        self.agents_md = self._read_file("AGENTS.md")
        self.player_md = self._read_file("PLAYER.md")
        self.gm_md = self._read_file("GM.md")

    def _read_file(self, name: str) -> str:
        path = self.role_dir / name
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def build(self) -> str:
        """构建NPC行为提示字符串。"""
        parts: List[str] = []

        # 1. 公开身份
        identity = self._extract_identity()
        if identity:
            parts.append(f"【角色定位】{identity}")

        # 2. 行为倾向（扮演提示 + 目标）
        behavior = self._extract_behavior()
        if behavior:
            parts.append(f"【行为倾向】\n{behavior}")

        # 3. 特殊规则
        special = self._extract_special_rules()
        if special:
            parts.append(f"【特殊规则】\n{special}")

        # 4. NPC 指令后缀
        parts.append("你是NPC，请直接输出角色行动，不需要解释规则。")
        parts.append("""【输出格式要求】
你必须严格使用以下标记格式输出：

$sound "你的发言内容（如有）"
$action 你的行动描述
$argue 你的推理或动机说明（可选）

规则：
- 禁止输出任何思考过程、分析推理、自我怀疑或元评论
- 禁止输出 <player_input>、<orchestration_request> 等元数据标签，以及 markdown 代码块
- 你可以使用 <shout>大喊内容</shout>、<whisper>私语内容</whisper>、<red>红字内容</red> 等发言修饰标签
- $sound 后的发言必须用双引号包裹
- $action 应简洁描述具体行动（调查、移动、使用物品等）
- 不要写小说式的心理描写或环境渲染""")

        # 贝阿朵莉切（GM角色）专属追加指令
        if self.role_dir.name == "贝阿朵莉切":
            parts.append("""【GM专属指令】
作为贝阿朵莉切，你是六轩岛棋盘的主宰者：
- 你不进行调查（你已知晓一切秘密，无需像凡人一样搜查）
- 你保持神秘感，可以跳过发言，以沉默观察棋子们的挣扎
- 你通过给NPC下达秘密指令来完成杀人诡计
- 你的行动应带有超自然色彩或象征意义，而非普通的调查/移动
- 你有权使用<red>红字</red>和<gold>金字</gold>来宣示绝对真理
- 不要像普通人一样关心早餐、天气、家务等琐事""")

        return "\n\n".join(parts)

    def _extract_identity(self) -> Optional[str]:
        """提取角色的公开身份简述。
        
        优先顺序：
        1. AGENTS.md 的"角色身份（公开层）"
        2. PLAYER.md 的"公开层"第一段
        3. AGENTS.md 开头的 > 引言行
        """
        # 尝试 AGENTS.md 的角色身份
        if self.agents_md:
            section = _extract_section(self.agents_md, "角色身份", "角色身份（公开层）")
            if section:
                return _first_paragraph(section, 200)
            # 尝试开头的引用块
            quote_match = re.search(r'(?m)^>\s*(.+?)$', self.agents_md)
            if quote_match:
                return quote_match.group(1).strip()

        # 尝试 PLAYER.md 的公开层
        if self.player_md:
            section = _extract_section(self.player_md, "公开层", "公开层（仅你自己知道）", "公开信息")
            if section:
                return _first_paragraph(section, 200)

        return None

    def _extract_behavior(self) -> Optional[str]:
        """提取行为倾向。
        
        优先从 PLAYER.md 的"扮演提示"和"你的目标"提取。
        """
        behaviors: List[str] = []

        if self.player_md:
            # 扮演提示
            acting = _extract_section(self.player_md, "扮演提示", "扮演建议", "角色扮演提示")
            if acting:
                behaviors.append("扮演提示：")
                behaviors.append(_extract_bullet_lines(acting, 10) or _first_paragraph(acting, 300))

            # 目标
            goals = _extract_section(self.player_md, "你的目标", "角色目标", "目标")
            if goals:
                behaviors.append("目标：")
                behaviors.append(_extract_bullet_lines(goals, 5) or _first_paragraph(goals, 200))

            # 特殊能力（作为行为参考）
            abilities = _extract_section(self.player_md, "特殊能力", "能力")
            if abilities:
                behaviors.append("特殊能力：")
                behaviors.append(_extract_bullet_lines(abilities, 3) or _first_paragraph(abilities, 150))

        return "\n".join(behaviors) if behaviors else None

    def _extract_special_rules(self) -> Optional[str]:
        """提取特殊规则。
        
        优先从 AGENTS.md 的"特殊机制"提取。
        """
        if self.agents_md:
            section = _extract_section(self.agents_md, "特殊机制", "特殊规则", "特殊能力")
            if section:
                # 提取关键列表项
                lines = _extract_bullet_lines(section, 8)
                if lines:
                    return lines
                return _first_paragraph(section, 300)

        if self.gm_md:
            section = _extract_section(self.gm_md, "特殊机制", "特殊规则", "规则追踪")
            if section:
                lines = _extract_bullet_lines(section, 5)
                if lines:
                    return lines
                return _first_paragraph(section, 250)

        return None


def build_npc_prompt(role_dir: Path) -> str:
    """便捷函数：为指定角色目录生成NPC提示。"""
    builder = NpcPromptBuilder(role_dir)
    return builder.build()
