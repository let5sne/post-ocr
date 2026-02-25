#!/usr/bin/env python3
"""
macOS 打包脚本（纯 RapidOCR）
使用方法: python build_mac.py [--debug]

产出: dist/信封信息提取系统.app  （或 dist/信封信息提取系统/ 目录）
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_NAME = "信封信息提取系统"


def build(debug=False):
    print("正在打包（macOS + RapidOCR），请稍候...")
    print(f"工作目录: {PROJECT_ROOT}")
    print(f"模式: {'调试（带控制台）' if debug else '正式（无控制台）'}")
    print("-" * 50)

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        f"--name={DIST_NAME}",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--paths=src",
        # --- hidden imports ---
        "--hidden-import=cv2",
        "--hidden-import=PIL",
        "--hidden-import=processor",
        "--hidden-import=ocr_offline",
        "--hidden-import=ocr_engine",
        "--hidden-import=ocr_worker_process",
        # --- 收集 RapidOCR 全部数据（ONNX 模型、字典等） ---
        "--collect-all=rapidocr_onnxruntime",
        "--collect-all=onnxruntime",
    ]

    if not debug:
        cmd.append("--windowed")
    else:
        cmd.append("--console")

    # macOS multiprocessing spawn 需要这个
    cmd.append("--argv-emulation")

    cmd.append("src/desktop.py")

    try:
        subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))
    except subprocess.CalledProcessError as e:
        print(f"打包失败: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("错误: 未找到 PyInstaller，请先安装: pip install pyinstaller")
        sys.exit(1)

    # macOS onedir 产出可能是 .app 或目录
    app_path = PROJECT_ROOT / "dist" / f"{DIST_NAME}.app"
    dir_path = PROJECT_ROOT / "dist" / DIST_NAME
    out = app_path if app_path.exists() else dir_path

    if out.exists():
        folder_size = sum(
            f.stat().st_size for f in out.rglob("*") if f.is_file()
        ) / 1024 / 1024
        print(f"\n打包完成！")
        print(f"输出: {out}")
        print(f"总大小: {folder_size:.1f} MB")
        print(f"\n分发方式: 将输出目录压缩为 zip 即可。")
    else:
        print("警告: 未找到输出文件")


if __name__ == "__main__":
    debug = "--debug" in sys.argv
    build(debug=debug)
