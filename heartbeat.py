#!/usr/bin/env python3
"""心跳程序 - 保持服务活跃"""
import sys
import time
import subprocess
import requests
from datetime import datetime

# 禁用输出缓冲
sys.stdout.reconfigure(line_buffering=True)


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def check_streamlit():
    """检查 Streamlit 服务"""
    try:
        r = requests.get("http://localhost:8501", timeout=5)
        return r.status_code == 200
    except:
        return False


def restart_streamlit():
    """重启 Streamlit"""
    subprocess.run(["pkill", "-f", "streamlit run"], capture_output=True)
    time.sleep(2)
    subprocess.Popen(
        ["streamlit", "run", "src/app.py", "--server.port", "8501", "--server.address", "0.0.0.0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"[{datetime.now():%H:%M:%S}] Streamlit 已重启")


def main():
    log("心跳程序启动")

    while True:
        if not check_streamlit():
            log("Streamlit 无响应，正在重启...")
            restart_streamlit()
            time.sleep(10)
        else:
            log("✓ 服务正常")

        time.sleep(60)  # 每分钟检查一次


if __name__ == "__main__":
    main()
