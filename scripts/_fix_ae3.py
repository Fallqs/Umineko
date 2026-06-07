#!/usr/bin/env python3
punct = '"\'()[]{}.,!?;:。，！？、；：'

with open('scripts/orchestrator/action_engine.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if 'result.move_target = re.sub' in line:
        new_lines.append(f'            result.move_target = move_match.group(1).strip().rstrip("{punct}")\n')
    elif 'result.hide_in = re.sub' in line:
        new_lines.append(f'            result.hide_in = hide_match.group(1).strip().rstrip("{punct}")\n')
    else:
        new_lines.append(line)

with open('scripts/orchestrator/action_engine.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("fixed3")
