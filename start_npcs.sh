#!/bin/bash
cd 'C:\Users\27382\Documents\repo\umi_client'

# 读取配置
TOKEN=$(python3 -c "import json; print(json.load(open('shared/.npc_config.json'))['access_token'])")
HOST=$(python3 -c "import json; print(json.load(open('shared/.npc_config.json'))['host'])")
PORT=$(python3 -c "import json; print(json.load(open('shared/.npc_config.json'))['port'])")

# 启动所有 NPC
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u4e61_u7530" python3 scripts/agent_wrapper.py --work-dir roles/乡田 --seat-id NPC_乡田 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u5357_u6761_u533b_u5e08" python3 scripts/agent_wrapper.py --work-dir roles/南条医师 --seat-id NPC_南条医师 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u590f_u5983" python3 scripts/agent_wrapper.py --work-dir roles/右代宫夏妃 --seat-id NPC_右代宫夏妃 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u697c_u5ea7" python3 scripts/agent_wrapper.py --work-dir roles/右代宫楼座 --seat-id NPC_右代宫楼座 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u7559_u5f17_u592b" python3 scripts/agent_wrapper.py --work-dir roles/右代宫留弗夫 --seat-id NPC_右代宫留弗夫 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u85cf_u81fc" python3 scripts/agent_wrapper.py --work-dir roles/右代宫藏臼 --seat-id NPC_右代宫藏臼 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u91d1_u85cf" python3 scripts/agent_wrapper.py --work-dir roles/右代宫金藏 --seat-id NPC_右代宫金藏 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u53f3_u4ee3_u5bab_u96fe_u6c5f" python3 scripts/agent_wrapper.py --work-dir roles/右代宫雾江 --seat-id NPC_右代宫雾江 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u718a_u6cfd" python3 scripts/agent_wrapper.py --work-dir roles/熊泽 --seat-id NPC_熊泽 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
KIMI_SHARE_DIR="C:\Users\27382\Documents\repo\umi_client\shared\.kimi\NPC__u8d1d_u963f_u6735_u8389_u5207" python3 scripts/agent_wrapper.py --work-dir roles/贝阿朵莉切 --seat-id NPC_贝阿朵莉切 --orchestrator-host "$HOST" --orchestrator-port "$PORT" --mode npc --yolo --access-token "$TOKEN" &
wait