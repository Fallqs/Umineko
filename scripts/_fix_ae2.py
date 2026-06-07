#!/usr/bin/env python3
with open('scripts/orchestrator/action_engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

punct = '"\'()[]{}.,!?;:。，！？、；：'

# 替换 move_target
old = '            result.move_target = re.sub(r"[。，！？、；：\\"\\\'\\(\\)\\[\\]\\{\\}\\.\\,\\!\\?\\;\\:\"]+$", "", move_match.group(1).strip())'
new = f'            result.move_target = move_match.group(1).strip().rstrip("{punct}")'
content = content.replace(old, new)

# 替换 hide_in
old2 = '            result.hide_in = re.sub(r"[。，！？、；：\\"\\\'\\(\\)\\[\\]\\{\\}\\.\\,\\!\\?\\;\\:\"]+$", "", hide_match.group(1).strip())'
new2 = f'            result.hide_in = hide_match.group(1).strip().rstrip("{punct}")'
content = content.replace(old2, new2)

with open('scripts/orchestrator/action_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("fixed2")
