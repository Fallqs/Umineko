"""
Prompt 模板加载器

从 config/prompts/ 目录加载 prompt 模板，支持变量替换。
"""

import string
from pathlib import Path
from typing import Optional


class PromptLoader:
    """加载并渲染 prompt 模板。"""

    def __init__(self, prompts_dir: Optional[Path] = None):
        if prompts_dir is None:
            # 默认路径：repo_root/config/prompts
            self.prompts_dir = Path(__file__).parent.parent / "config" / "prompts"
        else:
            self.prompts_dir = Path(prompts_dir)

    def load(self, name: str, **kwargs) -> str:
        """加载模板并替换变量。若模板不存在则返回空字符串。"""
        path = self.prompts_dir / f"{name}.txt"
        if not path.exists():
            return ""
        template = path.read_text(encoding="utf-8")
        if kwargs:
            return string.Template(template).safe_substitute(kwargs)
        return template

    def load_or_fallback(self, name: str, fallback: str, **kwargs) -> str:
        """加载模板，若不存在则返回 fallback。"""
        result = self.load(name, **kwargs)
        return result if result else fallback
