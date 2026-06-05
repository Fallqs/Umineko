<#
.SYNOPSIS
    《海猫鸣泣之时：六轩岛黄昏》启动脚本 (Windows PowerShell)

.DESCRIPTION
    本脚本帮助启动整个联机客户端的各个组件：
    1. 消息路由器 (local 或 server 模式)
    2. GM控制台辅助进程
    3. 提供各角色进程的启动命令

.PARAMETER Mode
    运行模式: local (单机/共享文件夹) 或 server (WebSocket服务器)

.PARAMETER Role
    启动特定角色进程: gm, 战人, 朱志香, 让治, 真里亚, 嘉音, 纱音, 秀吉

.EXAMPLE
    .\start-game.ps1 -Mode local
    .\start-game.ps1 -Mode server -Host 0.0.0.0 -Port 8765
    .\start-game.ps1 -Role 战人
#>

param(
    [Parameter()]
    [ValidateSet("local", "server", "")]
    [string]$Mode = "",

    [Parameter()]
    [ValidateSet("", "gm", "战人", "朱志香", "让治", "真里亚", "嘉音", "纱音", "秀吉", "贝阿朵莉切")]
    [string]$Role = "",

    [switch]$Npc,

    [string]$Host = "0.0.0.0",
    [int]$Port = 8765
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$InboxDir = Join-Path $RootDir "shared\inbox"

function Write-Header($text) {
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

function Write-Info($text) {
    Write-Host "[INFO] $text" -ForegroundColor Green
}

function Write-Warn($text) {
    Write-Host "[WARN] $text" -ForegroundColor Yellow
}

# 检查Python
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $Python) {
    Write-Warn "未找到 Python。请安装 Python 3.8+ 并添加到 PATH。"
    exit 1
}

Write-Info "Python: $($Python.Source)"

# 确保目录存在
if (-not (Test-Path $InboxDir)) {
    New-Item -ItemType Directory -Path $InboxDir -Force | Out-Null
}
$OutboxDir = Join-Path $InboxDir "outbox"
if (-not (Test-Path $OutboxDir)) {
    New-Item -ItemType Directory -Path $OutboxDir -Force | Out-Null
}

# 角色目录映射
$RoleDirs = @{
    "gm"      = "gm"
    "战人"    = "roles\右代宫战人"
    "朱志香"  = "roles\右代宫朱志香"
    "让治"    = "roles\右代宫让治"
    "真里亚"  = "roles\右代宫真里亚"
    "嘉音"    = "roles\嘉音"
    "纱音"    = "roles\纱音"
    "秀吉"    = "roles\右代宫秀吉"
    "贝阿朵莉切" = "roles\贝阿朵莉切"
}

# 启动特定角色
if ($Role) {
    $dirName = $RoleDirs[$Role]
    $roleDir = Join-Path $RootDir $dirName

    if (-not (Test-Path $roleDir)) {
        Write-Warn "角色目录不存在: $roleDir"
        exit 1
    }

    $pipePath = Join-Path $InboxDir "$Role\agent_pipe.jsonl"

    if ($Npc) {
        Write-Header "启动NPC角色: $Role"
        Write-Info "工作目录: $roleDir"
        Write-Info "启动命令: cd '$roleDir'; kimi --hide-thinking --agent-mode --agent-pipe '$pipePath'"
        Write-Host "`n请在新终端中执行:`n  cd '$roleDir'`n  kimi --hide-thinking --agent-mode --agent-pipe '$pipePath'`n" -ForegroundColor White
    } else {
        Write-Header "启动角色: $Role"
        Write-Info "工作目录: $roleDir"
        Write-Info "启动命令: cd '$roleDir'; kimi"
        Write-Host "`n请在新终端中执行:`n  cd '$roleDir'`n  kimi`n" -ForegroundColor White
    }
    exit 0
}

# 启动系统组件
Write-Header "《海猫鸣泣之时：六轩岛黄昏》客户端启动器"

if ($Mode -eq "local") {
    Write-Info "模式: 本地文件系统 (Local)"
    Write-Info "收件箱目录: $InboxDir"

    # 启动路由器
    Write-Header "启动消息路由器"
    $routerCmd = "& '$($Python.Source)' '$ScriptDir\router.py' --mode local --inbox-dir '$InboxDir'"
    Write-Info "执行: $routerCmd"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $routerCmd -WindowStyle Normal

    # 启动GM辅助控制台（可选）
    Write-Host "`n是否启动GM辅助控制台? (y/n): " -ForegroundColor Yellow -NoNewline
    $answer = Read-Host
    if ($answer -eq "y" -or $answer -eq "Y") {
        $gmCmd = "& '$($Python.Source)' '$ScriptDir\game_master.py' --status"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", $gmCmd -WindowStyle Normal
    }

} elseif ($Mode -eq "server") {
    Write-Info "模式: WebSocket 服务器 (Server)"
    Write-Info "地址: ws://$Host`:$Port"

    # 检查 websockets
    Write-Info "检查 websockets 库..."
    & $Python.Source -c "import websockets" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "需要安装 websockets 库"
        Write-Info "执行: pip install websockets"
        & $Python.Source -m pip install websockets
    }

    # 启动服务器
    Write-Header "启动 WebSocket 消息服务器"
    $serverCmd = "& '$($Python.Source)' '$ScriptDir\router.py' --mode server --host $Host --port $Port"
    Write-Info "执行: $serverCmd"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $serverCmd -WindowStyle Normal
}

# 显示角色启动命令
Write-Header "角色进程启动命令"
Write-Host "请为每个角色在新终端中执行对应的命令:`n" -ForegroundColor White

foreach ($r in $RoleDirs.Keys) {
    $dir = Join-Path $RootDir $RoleDirs[$r]
    Write-Host "  [$r] " -NoNewline -ForegroundColor Cyan
    Write-Host "cd '$dir'; kimi"
}

Write-Host "`nGM进程: cd '$(Join-Path $RootDir "gm")'; kimi" -ForegroundColor Magenta

Write-Host "`nNPC进程（AI驱动）:" -ForegroundColor Magenta
foreach ($r in @("贝阿朵莉切")) {
    $dir = Join-Path $RootDir $RoleDirs[$r]
    $pipe = Join-Path $InboxDir "$r\agent_pipe.jsonl"
    Write-Host "  [$r] cd '$dir'; kimi --hide-thinking --agent-mode --agent-pipe '$pipe'"
}

Write-Host "`n提示:" -ForegroundColor Yellow
Write-Host "  1. 先启动路由器，再启动各角色进程"
Write-Host "  2. 所有角色需要在同一网络/共享文件夹下通信"
Write-Host "  3. GM使用 game_master.py 管理游戏状态"
Write-Host "  4. 角色切换时，关闭当前进程并启动新角色的进程"
Write-Host "  5. NPC使用 -Npc 参数启动: .\start-game.ps1 -Role 贝阿朵莉切 -Npc"
