#!/usr/bin/env bash
# 全自动剧本杀完整测试启动脚本
# 用法: bash run_full_test.sh

cd "$(dirname "$0")" || exit 1

# 自动找 Python
PYTHON="${PYTHON:-$(command -v python3 || command -v python || echo '')}"
if [ -z "$PYTHON" ]; then
    echo "错误: 找不到 python，请设置 PYTHON 环境变量"
    exit 1
fi
echo "使用 Python: $PYTHON"

echo "[1/3] 清除旧 session..."
rm -rf ~/.kimi/sessions/P1_* ~/.kimi/sessions/P2_* ~/.kimi/sessions/P3_* \
  ~/.kimi/sessions/P4_* ~/.kimi/sessions/P5_* ~/.kimi/sessions/P6_* \
  ~/.kimi/sessions/P7_* ~/.kimi/sessions/NPC1_*
echo "  完成"

echo "[2/3] 启动完整 7 天测试..."
PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
  nohup "$PYTHON" -u scripts/test_orchestrator.py --python "$PYTHON" --max-day 7 \
  > shared/orchestrator_full.log 2>&1 &
PID=$!
echo "  后台运行 PID: $PID"

echo "[3/3] 查看日志:"
echo "  tail -f shared/orchestrator_full.log"
echo "  停止测试: kill $PID"
