# -*- coding: utf-8 -*-
"""
离线 OCR 初始化工具

目标：
1. Windows 交付 zip 目录包时，模型随包携带，程序完全离线可用
2. 如果模型缺失，明确报错并阻止 PaddleOCR 自动联网下载
3. 统一桌面版 / Web 版 / 命令行的 OCR 初始化逻辑，避免参数漂移
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
import logging


@dataclass(frozen=True)
class OCRModelPaths:
    """PP-OCRv4（中文）模型目录结构（对应 paddleocr==2.10.0 默认下载结构）"""

    base_dir: Path
    det_dir: Path
    rec_dir: Path
    cls_dir: Path


def _is_frozen() -> bool:
    """判断是否为 PyInstaller 打包后的运行环境"""

    return bool(getattr(sys, "frozen", False))


def get_app_base_dir() -> Path:
    """
    获取“应用根目录”：
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


def get_ppocr_v4_ch_model_paths(models_base_dir: Path | None = None) -> OCRModelPaths:
    """
    返回 PP-OCRv4（中文）默认模型目录。

    注意：这里的目录结构与 PaddleOCR 2.x 默认下载到 ~/.paddleocr 的结构一致，
    只是我们把 BASE_DIR 指向了随包的 models/，从而实现离线。
    """

    base = models_base_dir or get_models_base_dir()
    det_dir = base / "whl" / "det" / "ch" / "ch_PP-OCRv4_det_infer"
    rec_dir = base / "whl" / "rec" / "ch" / "ch_PP-OCRv4_rec_infer"
    cls_dir = base / "whl" / "cls" / "ch_ppocr_mobile_v2.0_cls_infer"
    return OCRModelPaths(base_dir=base, det_dir=det_dir, rec_dir=rec_dir, cls_dir=cls_dir)


def _configure_windows_dll_search_path(app_base_dir: Path) -> None:
    """
    Windows 下 PaddlePaddle 依赖的 mkml.dll 等动态库，通常位于打包目录的：
    - <exe_dir>/_internal/paddle/libs

    某些情况下动态库加载不会自动命中该路径（error code 126），需要显式加入 DLL 搜索路径。
    """

    if not sys.platform.startswith("win"):
        return

    # Python 3.8+ on Windows 支持 os.add_dll_directory
    add_dll_dir = getattr(os, "add_dll_directory", None)
    internal_dir = app_base_dir / "_internal"

    candidates = [
        internal_dir / "paddle" / "libs",
        internal_dir / "paddle",
        internal_dir,
        app_base_dir,
    ]

    # 同时设置 PATH，兼容不走 add_dll_directory 的加载路径
    path_parts = [os.environ.get("PATH", "")]
    for p in candidates:
        if p.exists():
            if add_dll_dir is not None:
                try:
                    add_dll_dir(str(p))
                except Exception:
                    # add_dll_directory 在某些权限/路径场景可能失败，PATH 兜底
                    pass
            path_parts.insert(0, str(p))
    os.environ["PATH"] = ";".join([x for x in path_parts if x])


def _check_infer_dir(dir_path: Path) -> bool:
    """判断一个推理模型目录是否完整（至少包含 inference.pdmodel / inference.pdiparams）"""

    return (dir_path / "inference.pdmodel").exists() and (dir_path / "inference.pdiparams").exists()


def verify_offline_models_or_raise(model_paths: OCRModelPaths) -> None:
    """
    校验离线模型是否存在。

    设计选择：
    - 直接抛异常：由上层（桌面/UI/CLI）决定如何展示错误
    - 不允许缺失时继续初始化：避免触发 PaddleOCR 自动联网下载
    """

    missing = []
    if not _check_infer_dir(model_paths.det_dir):
        missing.append(str(model_paths.det_dir))
    if not _check_infer_dir(model_paths.rec_dir):
        missing.append(str(model_paths.rec_dir))
    if not _check_infer_dir(model_paths.cls_dir):
        missing.append(str(model_paths.cls_dir))

    if missing:
        hint = (
            "离线模型缺失，无法在离线模式启动。\n\n"
            "缺失目录：\n- "
            + "\n- ".join(missing)
            + "\n\n"
            "解决方式：\n"
            "1) 在有网机器执行：python scripts/prepare_models.py --models-dir models\n"
            "2) 将生成的 models/ 目录随 zip 包一起分发（与 exe 同级）"
        )
        raise FileNotFoundError(hint)


def create_offline_ocr(models_base_dir: Path | None = None, show_log: bool = False):
    """
    创建 PaddleOCR（离线模式）。

    关键点：
    - 通过环境变量 PADDLE_OCR_BASE_DIR 将默认下载/查找目录指向随包 models/（与 paddleocr==2.10.0 行为匹配）
    - 显式传入 det/rec/cls 的模型目录，避免目录不一致导致重复下载
    - 如果模型缺失，提前报错，阻止联网下载
    """

    log = logging.getLogger("post_ocr.ocr")
    model_paths = get_ppocr_v4_ch_model_paths(models_base_dir=models_base_dir)
    verify_offline_models_or_raise(model_paths)

    # Windows 打包运行时，先配置 DLL 搜索路径，避免 mkml.dll 等加载失败（error code 126）
    _configure_windows_dll_search_path(get_app_base_dir())

    # 禁用联网检查（加快启动），并把默认 base_dir 指向随包 models/
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_OCR_BASE_DIR"] = str(model_paths.base_dir)

    # 延迟导入：确保环境变量在 paddleocr 模块加载前设置生效
    log.info("create_offline_ocr: importing paddleocr (base_dir=%s)", str(model_paths.base_dir))
    from paddleocr import PaddleOCR  # pylint: disable=import-error

    # 注意：paddleocr==2.10.0 不支持 use_textline_orientation 这类 3.x pipeline 参数
    log.info("create_offline_ocr: creating PaddleOCR(det=%s, rec=%s)", str(model_paths.det_dir), str(model_paths.rec_dir))
    ocr = PaddleOCR(
        lang="ch",
        show_log=show_log,
        use_angle_cls=False,
        det_model_dir=str(model_paths.det_dir),
        rec_model_dir=str(model_paths.rec_dir),
        cls_model_dir=str(model_paths.cls_dir),
    )
    log.info("create_offline_ocr: PaddleOCR created")
    return ocr
