#!/usr/bin/env python3
"""
打包脚本 - 将桌面程序打包成独立可执行文件
使用方法: pip install pyinstaller && python build_exe.py
"""
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


def build():
    """使用 PyInstaller 打包"""

    # PyInstaller 命令
    cmd = [
        "pyinstaller",
        "--name=信封信息提取系统",
        "--onefile",              # 打包成单个 exe
        "--windowed",             # 无控制台窗口
        "--clean",                # 清理缓存
        "--noconfirm",            # 覆盖输出目录不询问
        "--add-data=src;src",    # 包含源码目录
        "--hidden-import=PaddleOCR",
        "--hidden-import=paddleocr",
        "--hidden-import=cv2",
        "--hidden-import=PyQt6",
        "--collect-all=PaddleOCR",
        "--collect-all=paddleocr",
        "src/desktop.py",
    ]

    print("正在打包，请稍候...")
    print(f"工作目录: {PROJECT_ROOT}")
    print(f"输出目录: {PROJECT_ROOT / 'dist'}")
    print("-" * 50)

    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)

    print("-" * 50)
    print("打包完成！")
    print(f"可执行文件: {PROJECT_ROOT / 'dist' / '信封信息提取系统.exe'}")


if __name__ == "__main__":
    build()
