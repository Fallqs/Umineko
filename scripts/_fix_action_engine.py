#!/usr/bin/env python3
import re

with open('scripts/orchestrator/action_engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

punct_pattern = r"[。，！？、；：\"\'\(\)\[\]\{\}\.\,\!\?\;\:\"]+$"

# 修复 move_target
old_move = '''        # 即时移动
        move_match = re.search(r"(?:移动到|前往|去|走向)[：:]?\s*(\S+)", text)
        if move_match:
            result.move_target = move_match.group(1).strip()'''

new_move = '''        # 即时移动
        move_match = re.search(r"(?:移动到|前往|去|走向)[了：:]?\s*(\S+)", text)
        if move_match:
            result.move_target = re.sub(r"[。，！？、；：\\"\\'\\(\\)\\[\\]\\{\\}\\.\\,\\!\\?\\;\\:\"]+$", "", move_match.group(1).strip())'''

content = content.replace(old_move, new_move)

# 修复 hide_in
old_hide = '''        # 进入藏匿点
        hide_match = re.search(r"(?:躲进|藏到|藏入|进入|躲到)[了：:]?\s*(\S+)", text)
        if hide_match:
            result.hide_in = re.sub(r'[。，！？、；：\\"\\'\\(\\)\\[\\]\\{\\}\\.\\,\\!\\?\\;\\:\"]+$','', hide_match.group(1).strip())'''

new_hide = '''        # 进入藏匿点
        hide_match = re.search(r"(?:躲进|藏到|藏入|进入|躲到)[了：:]?\s*(\S+)", text)
        if hide_match:
            result.hide_in = re.sub(r"[。，！？、；：\\"\\'\\(\\)\\[\\]\\{\\}\\.\\,\\!\\?\\;\\:\"]+$", "", hide_match.group(1).strip())'''

content = content.replace(old_hide, new_hide)

with open('scripts/orchestrator/action_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("fixed")
