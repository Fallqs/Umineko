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
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u85cf_u81fc
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫藏臼 --seat-id NPC_右代宫藏臼 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u91d1_u85cf
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫金藏 --seat-id NPC_右代宫金藏 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u96fe_u6c5f
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\右代宫雾江 --seat-id NPC_右代宫雾江 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u718a_u6cfd
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\熊泽 --seat-id NPC_熊泽 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal
setlocal
set KIMI_SHARE_DIR=C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u8d1d_u963f_u6735_u8389_u5207
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /min "" python scripts\agent_wrapper.py --work-dir roles\贝阿朵莉切 --seat-id NPC_贝阿朵莉切 --orchestrator-host %HOST% --orchestrator-port %PORT% --mode npc --yolo --access-token %TOKEN%
endlocal