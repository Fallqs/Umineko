"""测试 subprocess.Popen 是否传递包含中文的 KIMI_SHARE_DIR 环境变量"""
import subprocess, sys, os

env = os.environ.copy()
env["KIMI_SHARE_DIR"] = "C:\\test_kimi_share_dir\\NPC_嘉音"
proc = subprocess.Popen(
    [sys.executable, "-c", "import os; print('KIMI_SHARE_DIR=', os.getenv('KIMI_SHARE_DIR'))"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    env=env,
)
out, _ = proc.communicate()
print(out)
