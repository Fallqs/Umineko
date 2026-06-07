with open('scripts/orchestrator/core.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Merge line 301 (index 300) and 302 (index 301)
if lines[300].strip() == 'death_text = "' and lines[301].strip().startswith('"'):
    lines[300] = '            death_text = "\\n".join([f"☠️ {r}: {c}" for r, c in deaths])\n'
    del lines[301]
    print('Merged death_text lines')
else:
    print(f'Line 301: {repr(lines[300])}')
    print(f'Line 302: {repr(lines[301])}')

# After deletion, line 302 (original 303) and 303 (original 304)
# Check if we need to merge them
if len(lines) > 302:
    if '发现了新的死亡：' in lines[301] and lines[302].strip().startswith('{death_text}'):
        lines[301] = '            await self._broadcast_notification("清晨事件", f"发现了新的死亡：\\n{death_text}", severity="error")\n'
        del lines[302]
        print('Merged broadcast lines')
    else:
        print(f'Line 302: {repr(lines[301])}')
        print(f'Line 303: {repr(lines[302])}')

with open('scripts/orchestrator/core.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Done')
