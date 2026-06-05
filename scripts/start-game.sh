#!/usr/bin/env bash
#
# 《海猫鸣泣之时：六轩岛黄昏》启动脚本 (Unix/macOS/Linux)
#
# 用法:
#   ./start-game.sh local           # 本地文件系统模式
#   ./start-game.sh server          # WebSocket服务器模式
#   ./start-game.sh role 战人        # 启动特定角色进程
#   ./start-game.sh gm              # 启动GM进程

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
INBOX_DIR="$ROOT_DIR/shared/inbox"

# 颜色
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
MAGENTA='\033[0;35m'
WHITE='\033[1;37m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
header() {
    echo -e "${CYAN}\n========================================"
    echo -e "  $1"
    echo -e "========================================${NC}"
}

# 检查Python
PYTHON=$(command -v python3 || command -v python || echo "")
if [ -z "$PYTHON" ]; then
    warn "未找到 Python。请安装 Python 3.8+ 并添加到 PATH。"
    exit 1
fi
info "Python: $PYTHON"

# 确保目录存在
mkdir -p "$INBOX_DIR/outbox"

# 角色目录映射
declare -A ROLE_DIRS=(
    ["gm"]="gm"
    ["战人"]="roles/右代宫战人"
    ["朱志香"]="roles/右代宫朱志香"
    ["让治"]="roles/右代宫让治"
    ["真里亚"]="roles/右代宫真里亚"
    ["嘉音"]="roles/嘉音"
    ["纱音"]="roles/纱音"
    ["秀吉"]="roles/右代宫秀吉"
    ["贝阿朵莉切"]="roles/贝阿朵莉切"
)

MODE="${1:-}"
ROLE="${2:-}"
NPC="${3:-}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8765}"

# 启动特定角色
if [ "$MODE" = "role" ] && [ -n "$ROLE" ]; then
    dir="${ROLE_DIRS[$ROLE]}"
    if [ -z "$dir" ]; then
        warn "未知角色: $ROLE"
        exit 1
    fi
    role_dir="$ROOT_DIR/$dir"
    pipe_path="$INBOX_DIR/$ROLE/agent_pipe.jsonl"
    if [ "$NPC" = "npc" ]; then
        header "启动NPC角色: $ROLE"
        info "工作目录: $role_dir"
        echo -e "\n${WHITE}请执行:${NC}\n  cd '$role_dir'\n  kimi --hide-thinking --agent-mode --agent-pipe '$pipe_path'\n"
    else
        header "启动角色: $ROLE"
        info "工作目录: $role_dir"
        echo -e "\n${WHITE}请执行:${NC}\n  cd '$role_dir'\n  kimi\n"
    fi
    exit 0
fi

if [ "$MODE" = "gm" ]; then
    gm_dir="$ROOT_DIR/gm"
    header "启动GM进程"
    info "工作目录: $gm_dir"
    echo -e "\n${WHITE}请执行:${NC}\n  cd '$gm_dir'\n  kimi\n"
    exit 0
fi

# 启动系统组件
header "《海猫鸣泣之时：六轩岛黄昏》客户端启动器"

if [ "$MODE" = "local" ]; then
    info "模式: 本地文件系统 (Local)"
    info "收件箱目录: $INBOX_DIR"

    header "启动消息路由器"
    info "在新的终端中执行:"
    echo -e "  ${WHITE}cd '$SCRIPT_DIR' && $PYTHON router.py --mode local --inbox-dir '$INBOX_DIR'${NC}"

    header "GM辅助控制台"
    info "在新的终端中执行:"
    echo -e "  ${WHITE}cd '$SCRIPT_DIR' && $PYTHON game_master.py --status${NC}"

elif [ "$MODE" = "server" ]; then
    info "模式: WebSocket 服务器 (Server)"
    info "地址: ws://$HOST:$PORT"

    # 检查 websockets
    info "检查 websockets 库..."
    if ! $PYTHON -c "import websockets" 2>/dev/null; then
        warn "需要安装 websockets 库"
        info "执行: pip install websockets"
        pip install websockets
    fi

    header "启动 WebSocket 消息服务器"
    info "在新的终端中执行:"
    echo -e "  ${WHITE}cd '$SCRIPT_DIR' && $PYTHON router.py --mode server --host $HOST --port $PORT${NC}"
else
    warn "未知模式: $MODE"
    echo "用法:"
    echo "  $0 local                  # 本地模式"
    echo "  $0 server                 # 服务器模式"
    echo "  $0 role 战人               # 启动角色进程"
    echo "  $0 role 贝阿朵莉切 npc     # 启动NPC角色进程"
    echo "  $0 gm                     # 启动GM进程"
    exit 1
fi

# 显示角色启动命令
header "角色进程启动命令"
echo -e "${WHITE}请为每个角色在新终端中执行对应的命令:${NC}\n"

for r in "${!ROLE_DIRS[@]}"; do
    dir="$ROOT_DIR/${ROLE_DIRS[$r]}"
    echo -e "  ${CYAN}[$r]${NC} cd '$dir'; kimi"
done

echo -e "\n${MAGENTA}GM进程:${NC} cd '$ROOT_DIR/gm'; kimi"

echo -e "\n${MAGENTA}NPC进程（AI驱动）:${NC}"
for r in "贝阿朵莉切"; do
    dir="$ROOT_DIR/${ROLE_DIRS[$r]}"
    pipe="$INBOX_DIR/$r/agent_pipe.jsonl"
    echo "  [$r] cd '$dir'; kimi --hide-thinking --agent-mode --agent-pipe '$pipe'"
done

echo -e "\n${YELLOW}提示:${NC}"
echo "  1. 先启动路由器，再启动各角色进程"
echo "  2. 所有角色需要在同一网络/共享文件夹下通信"
echo "  3. GM使用 game_master.py 管理游戏状态"
echo "  4. 角色切换时，关闭当前进程并启动新角色的进程"
echo "  5. NPC使用 npc 参数启动: $0 role 贝阿朵莉切 npc"
