# -*- coding: utf-8 -*-
"""
离线 OCR 初始化工具

适配 PaddleOCR 2.10.0（PP-OCRv4）。

模型默认缓存在 ~/.paddleocr/whl/，首次运行会自动下载。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import logging


def _is_frozen() -> bool:
    """判断是否为 PyInstaller 打包后的运行环境"""
    return bool(getattr(sys, "frozen", False))


def get_app_base_dir() -> Path:
    """
    获取"应用根目录"：
    - 开发态：项目根目录（src 的上一级）
    - 打包态：exe 所在目录
    """
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_models_base_dir(app_base_dir: Path | None = None) -> Path:
    """默认模型目录：与应用同级的 models/"""
    base = app_base_dir or get_app_base_dir()
    return base / "models"


def _configure_windows_dll_search_path(app_base_dir: Path) -> None:
    """
    Windows 下 PaddlePaddle 依赖的 mkml.dll 等动态库，通常位于打包目录的：
    - <exe_dir>/_internal/paddle/libs

    某些情况下动态库加载不会自动命中该路径（error code 126），需要显式加入 DLL 搜索路径。
    """
    if not sys.platform.startswith("win"):
        return

    add_dll_dir = getattr(os, "add_dll_directory", None)
    internal_dir = app_base_dir / "_internal"

    candidates = [
        internal_dir / "paddle" / "libs",
        internal_dir / "paddle",
        internal_dir,
        app_base_dir,
    ]

    path_parts = [os.environ.get("PATH", "")]
    for p in candidates:
        if p.exists():
            if add_dll_dir is not None:
                try:
                    add_dll_dir(str(p))
                except Exception:
                    pass
            path_parts.insert(0, str(p))
    os.environ["PATH"] = ";".join([x for x in path_parts if x])


def create_offline_ocr(models_base_dir: Path | None = None):
    """
    创建 PaddleOCR 2.x 实例（PP-OCRv4 中文）。

    首次运行会自动下载模型到 ~/.paddleocr/whl/。
    """
    log = logging.getLogger("post_ocr.ocr")

    # Windows 打包运行时，先配置 DLL 搜索路径
    _configure_windows_dll_search_path(get_app_base_dir())

    log.info("create_offline_ocr: importing paddleocr")
    from paddleocr import PaddleOCR

    log.info("create_offline_ocr: creating PaddleOCR(lang=ch)")
    ocr = PaddleOCR(
        lang="ch",
        use_angle_cls=False,
        show_log=False,
    )
    log.info("create_offline_ocr: PaddleOCR created")
    return ocr
