#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线模型准备脚本（建议在“有网机器”执行一次）

用途：
- 将 PaddleOCR 2.10.0（PP-OCRv4 中文）所需模型下载到指定 models/ 目录
- 该 models/ 目录可直接随 Windows zip 目录包分发，实现完全离线运行

设计说明：
- 脚本只做“下载/补齐”，不做删除或覆盖，避免误删用户已有模型（高风险操作）
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="准备 post-ocr 离线模型（PP-OCRv4 中文）")
    parser.add_argument(
        "--models-dir",
        default="models",
        help="模型输出目录（默认：models，建议与 exe 同级）",
    )
    parser.add_argument(
        "--show-log",
        action="store_true",
        help="显示 PaddleOCR 初始化日志（默认关闭）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    models_dir = Path(args.models_dir).resolve()
    models_dir.mkdir(parents=True, exist_ok=True)

    # 关键：把 PaddleOCR 默认 base_dir 指到我们指定的 models/
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_OCR_BASE_DIR"] = str(models_dir)

    # 延迟导入：确保环境变量在模块加载前生效
    from paddleocr import PaddleOCR  # pylint: disable=import-error

    print(f"将下载/补齐模型到: {models_dir}")
    print("首次执行需要联网下载（约数百 MB），请耐心等待。")

    # 初始化会自动下载 det/rec/cls 模型到 BASE_DIR/whl/...
    PaddleOCR(lang="ch", show_log=args.show_log, use_angle_cls=False)

    print("完成。你可以将该 models/ 目录随 zip 目录包一起分发（与 exe 同级）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
