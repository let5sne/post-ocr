#!/usr/bin/env python3
"""
打包脚本 - 将桌面程序打包成可离线分发的目录包
使用方法: python build_exe.py [--debug]

产出: dist/信封信息提取系统/
  ├── 信封信息提取系统.exe
  ├── _internal/          (运行时依赖)
  └── models/             (OCR 模型，需提前通过 prepare_models.py 准备)
"""
import os
import subprocess
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_NAME = "信封信息提取系统"

# paddle DLLs 所在目录（mklml.dll 等不会被 PyInstaller 自动收集）
import paddle as _paddle
PADDLE_LIBS = str(Path(_paddle.__file__).parent / "libs")


def build(debug=False):
    """使用 PyInstaller 打包（onedir 模式）"""

    print("正在打包，请稍候...")
    print(f"工作目录: {PROJECT_ROOT}")
    print(f"模式: {'调试（带控制台）' if debug else '正式（无控制台）'}")
    print("-" * 50)

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        f"--name={DIST_NAME}",
        "--onedir",
        "--noconfirm",
        "--paths=src",
        # --- hidden imports ---
        "--hidden-import=cv2",
        "--hidden-import=PIL",
        "--hidden-import=processor",
        "--hidden-import=ocr_offline",
        "--hidden-import=paddleocr",
        "--hidden-import=paddle",
        # --- paddle DLLs（mklml.dll 等不会被自动收集） ---
        f"--add-binary={PADDLE_LIBS}/*.dll{os.pathsep}paddle/libs",
        # --- runtime hook: stub 掉 paddle 开发模块，避免 Cython 缺文件崩溃 ---
        "--runtime-hook=rthook_paddle.py",
        # --- 收集 paddleocr 全部数据（模型配置、字典等） ---
        "--collect-all=paddleocr",
        # --- 元数据（部分库在运行时通过 importlib.metadata 查版本） ---
        "--copy-metadata=paddlepaddle",
        "--copy-metadata=paddleocr",
    ]

    if not debug:
        cmd.append("--windowed")
    else:
        cmd.append("--console")

    cmd.append("src/desktop.py")

    try:
        subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))
    except subprocess.CalledProcessError as e:
        print("-" * 50)
        print(f"打包失败: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("-" * 50)
        print("错误: 未找到 PyInstaller，请先安装: pip install pyinstaller")
        sys.exit(1)

    print("-" * 50)

    # 复制 models/ 到输出目录（与 exe 同级）
    dist_dir = PROJECT_ROOT / "dist" / DIST_NAME
    models_src = PROJECT_ROOT / "models"
    models_dst = dist_dir / "models"

    if models_src.exists() and any(models_src.rglob("*.pdmodel")):
        print(f"复制离线模型: {models_src} -> {models_dst}")
        if models_dst.exists():
            shutil.rmtree(models_dst)
        shutil.copytree(models_src, models_dst)
    else:
        print("⚠️  未找到离线模型。请先执行:")
        print("    python scripts/prepare_models.py --models-dir models")
        print("   然后重新打包，或手动将 models/ 放到 dist 目录中。")

    # 统计大小
    exe_path = dist_dir / f"{DIST_NAME}.exe"
    if exe_path.exists():
        folder_size = sum(
            f.stat().st_size for f in dist_dir.rglob("*") if f.is_file()
        ) / 1024 / 1024
        print(f"\n打包完成！")
        print(f"输出目录: {dist_dir}")
        print(f"总大小: {folder_size:.1f} MB")
        print(f"\n分发方式: 将 {dist_dir.name}/ 整个文件夹打成 zip 即可。")
    else:
        print("警告: 未找到输出的 exe 文件")


if __name__ == "__main__":
    debug = "--debug" in sys.argv
    build(debug=debug)
