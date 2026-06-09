"""
贝阿朵莉切"闪回"觉醒引擎

在每个时间槽边界批量检查是否有新的贝阿朵设定章节满足解锁条件。
只将新解锁的章节通过私有消息发送给贝阿朵NPC进程，不写入公共日志。
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set


class BeatriceFlashbackEngine:
    """管理贝阿朵莉切的渐进觉醒闪回。"""

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)
        self.lore_dir = self.root_dir / "roles" / "贝阿朵莉切" / "lore"
        self._config: Optional[dict] = None
        self._last_checked: Set[str] = set()

    def _load_config(self) -> dict:
        if self._config is None:
            path = self.root_dir / "config" / "beatrice_unlocks.json"
            with open(path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        return self._config

    def _load_chapter(self, chapter_id: str) -> str:
        # 优先尝试直接匹配 chapter_id.md
        path = self.lore_dir / f"{chapter_id}.md"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        # 回退：尝试 chapter_id_*.md（如 L0_persona.md）
        for candidate in self.lore_dir.glob(f"{chapter_id}_*.md"):
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read()
        return f"【闪回：{chapter_id}】（内容暂缺）"

    def _meets_conditions(self, cfg: dict, game_state) -> bool:
        """检查章节解锁条件是否满足。"""
        # 检查天数
        if game_state.day < cfg.get("requires_day", 0):
            return False

        # 检查 info entry（任意角色解锁任一即可）
        required_infos = cfg.get("requires_info", [])
        if required_infos:
            all_unlocked: Set[str] = set()
            for infos in game_state.unlocked_info.values():
                all_unlocked.update(infos)
            if not any(r in all_unlocked for r in required_infos):
                return False

        return True

    def check_new_unlocks(self, game_state) -> List[dict]:
        """返回新解锁的闪回记忆列表。"""
        config = self._load_config()
        newly_unlocked: List[dict] = []

        for ch_id, ch_cfg in config.get("chapters", {}).items():
            if ch_id in self._last_checked:
                continue
            if self._meets_conditions(ch_cfg, game_state):
                self._last_checked.add(ch_id)
                content = self._load_chapter(ch_id)
                newly_unlocked.append({
                    "chapter_id": ch_id,
                    "chapter_title": ch_cfg.get("description", ch_id),
                    "content": content,
                    "day": game_state.day,
                })

        return newly_unlocked

    def reset(self):
        """重置已检查状态（用于新游戏）。"""
        self._last_checked.clear()
