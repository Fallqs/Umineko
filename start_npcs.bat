@echo off
cd /d C:\Users\27382\Documents\repo\umi_client

REM 读取配置
for /f "tokens=*" %%a in ('powershell -Command "(Get-Content shared\.npc_config.json | ConvertFrom-Json).access_token"') do set TOKEN=%%a
for /f "tokens=*" %%a in ('powershell -Command "(Get-Content shared\.npc_config.json | ConvertFrom-Json).host"') do set HOST=%%a
for /f "tokens=*" %%a in ('powershell -Command "(Get-Content shared\.npc_config.json | ConvertFrom-Json).port"') do set PORT=%%a

REM 启动所有 NPC
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u4e61_u7530
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\乡田 --seat-id NPC_乡田 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u5357_u6761_u533b_u5e08
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\南条医师 --seat-id NPC_南条医师 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u590f_u5983
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫夏妃 --seat-id NPC_右代宫夏妃 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u6731_u5fd7_u9999
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫朱志香 --seat-id NPC_右代宫朱志香 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u697c_u5ea7
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫楼座 --seat-id NPC_右代宫楼座 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u7559_u5f17_u592b
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫留弗夫 --seat-id NPC_右代宫留弗夫 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u771f_u91cc_u4e9a
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫真里亚 --seat-id NPC_右代宫真里亚 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u79c0_u5409
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫秀吉 --seat-id NPC_右代宫秀吉 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u85cf_u81fc
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫藏臼 --seat-id NPC_右代宫藏臼 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u8ba9_u6cbb
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫让治 --seat-id NPC_右代宫让治 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u96fe_u6c5f
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫雾江 --seat-id NPC_右代宫雾江 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u5609_u97f3
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\嘉音 --seat-id NPC_嘉音 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u718a_u6cfd
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\熊泽 --seat-id NPC_熊泽 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u7eb1_u97f3
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\纱音 --seat-id NPC_纱音 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u8d1d_u963f_u6735_u8389_u5207
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\贝阿朵莉切 --seat-id NPC_贝阿朵莉切 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal