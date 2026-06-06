import re

with open("scripts/orchestrator/core.py", "r", encoding="utf-8") as f:
    content = f.read()

# 移除调查（观察玩家）的行为可见性
old1 = '''                    await self.action_engine.broadcast_action_visibility(
                        role, f"正在观察{parsed.investigate_target}", location, exclude_role=role
                    )
'''
if old1 in content:
    content = content.replace(old1, '')
    print("removed investigate_target visibility")

# 移除调查（场景）的行为可见性
old2 = '''                        await self.action_engine.broadcast_action_visibility(
                            role, f"正在仔细调查{location}的每个角落", location, exclude_role=role
                        )
'''
if old2 in content:
    content = content.replace(old2, '')
    print("removed investigate visibility")

# 移除验尸的行为可见性
old3 = '''                    await self.action_engine.broadcast_action_visibility(
                        role, "正在检查尸体", location, exclude_role=role
                    )
'''
if old3 in content:
    content = content.replace(old3, '')
    print("removed autopsy visibility")

# 移除搜身的行为可见性
old4 = '''                await self.action_engine.broadcast_action_visibility(
                    role, f"正在对{parsed.search_target}进行搜身", location, exclude_role=role
                )
'''
if old4 in content:
    content = content.replace(old4, '')
    print("removed search visibility")

# 移除拾取的行为可见性
old5 = '''                await self.action_engine.broadcast_action_visibility(
                    role, f"正在{location}寻找可以带走的东西", location, exclude_role=role
                )
'''
if old5 in content:
    content = content.replace(old5, '')
    print("removed pickup visibility")

# 移除使用物品的行为可见性
old6 = '''                await self.action_engine.broadcast_action_visibility(
                    role, "正在使用手中的某件物品", location, exclude_role=role
                )
'''
if old6 in content:
    content = content.replace(old6, '')
    print("removed use_item visibility")

# 移除赠送的行为可见性
old7 = '''            await self.action_engine.broadcast_action_visibility(
                role, f"正在将某物交给{parsed.gift_target}", location, exclude_role=role
            )
'''
if old7 in content:
    content = content.replace(old7, '')
    print("removed gift visibility")

with open("scripts/orchestrator/core.py", "w", encoding="utf-8") as f:
    f.write(content)

print("done")
