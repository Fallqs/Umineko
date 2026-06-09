"""测试 subprocess.Popen 完整参数下环境变量传递"""
import subprocess, sys, os

env = os.environ.copy()
env["KIMI_SHARE_DIR"] = "C:\\test_kimi_share_dir\\NPC_嘉音"
proc = subprocess.Popen(
    [sys.executable, "-c", "import os; print('KIMI_SHARE_DIR=', os.getenv('KIMI_SHARE_DIR')); print('type=', type(os.getenv('KIMI_SHARE_DIR')))"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    close_fds=True,
    env=env,
)
out, _ = proc.communicate()
print(out)
