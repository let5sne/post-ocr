#!/usr/bin/env python3
"""
打包脚本 - 将桌面程序打包成独立可执行文件
使用方法: pip install pyinstaller && python build_exe.py

调试版本: python build_exe.py --debug
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent)


def build(debug=False):
    """使用 PyInstaller 打包"""

    print("正在打包，请稍候...")
    print(f"工作目录: {PROJECT_ROOT}")
    print("-" * 50)

    # 使用 Python -m PyInstaller 方式
    # --paths 将 src 目录添加到 Python 路径，避免导入问题
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--name=信封信息提取系统",
        "--onefile",
        "--clean",
        "--noconfirm",
        "--paths=src",
    ]

    # 调试模式：显示控制台窗口，便于查看错误
    if not debug:
        cmd.append("--windowed")

    cmd.append("src/desktop.py")

    try:
        subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))
        print("-" * 50)
        print("打包完成！")
        exe_path = PROJECT_ROOT / "dist" / "信封信息提取系统.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / 1024 / 1024
            print(f"可执行文件: {exe_path}")
            print(f"文件大小: {size_mb:.1f} MB")
        else:
            print("警告: 未找到输出文件")
    except subprocess.CalledProcessError as e:
        print("-" * 50)
        print(f"打包失败: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("-" * 50)
        print("错误: 未找到 PyInstaller")
        print("请先安装: pip install pyinstaller")
        sys.exit(1)


if __name__ == "__main__":
    debug = "--debug" in sys.argv
    build(debug=debug)
