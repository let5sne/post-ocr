from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger("post_ocr.ocr_engine")


@dataclass
class OCRLine:
    text: str
    box: Any
    conf: Optional[float] = None


class BaseOCREngine:
    backend_name: str = "unknown"

    def infer_lines(self, img: Any) -> List[OCRLine]:
        raise NotImplementedError


def _to_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


class PaddleOCREngine(BaseOCREngine):
    backend_name = "paddle"

    def __init__(self, models_base_dir: Path):
        from ocr_offline import create_offline_ocr

        self._ocr = create_offline_ocr(models_base_dir=models_base_dir)

    def infer_lines(self, img: Any) -> List[OCRLine]:
        result = self._ocr.ocr(img, cls=False)
        lines: List[OCRLine] = []
        if result and result[0]:
            for line in result[0]:
                if not line or len(line) < 2:
                    continue
                text = str(line[1][0]) if isinstance(line[1], (list, tuple)) and line[1] else ""
                if not text:
                    continue
                conf = None
                if isinstance(line[1], (list, tuple)) and len(line[1]) >= 2:
                    conf = _to_float(line[1][1])
                lines.append(OCRLine(text=text, box=line[0], conf=conf))
        return lines


class RapidOCREngine(BaseOCREngine):
    backend_name = "rapidocr"

    def __init__(self, models_base_dir: Path):
        # 按官方包名导入：rapidocr-onnxruntime -> rapidocr_onnxruntime
        from rapidocr_onnxruntime import RapidOCR

        kwargs: dict[str, Any] = {}
        # 可选：如果用户准备了本地 ONNX 模型，可通过环境变量覆盖路径
        det_path = os.environ.get("POST_OCR_RAPID_DET_MODEL", "").strip()
        cls_path = os.environ.get("POST_OCR_RAPID_CLS_MODEL", "").strip()
        rec_path = os.environ.get("POST_OCR_RAPID_REC_MODEL", "").strip()
        dict_path = os.environ.get("POST_OCR_RAPID_KEYS_PATH", "").strip()
        if det_path:
            kwargs["det_model_path"] = det_path
        if cls_path:
            kwargs["cls_model_path"] = cls_path
        if rec_path:
            kwargs["rec_model_path"] = rec_path
        if dict_path:
            kwargs["rec_keys_path"] = dict_path

        self._ocr = RapidOCR(**kwargs)
        self._models_base_dir = models_base_dir

    def _parse_result_item(self, item: Any) -> Optional[OCRLine]:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("txt") or "").strip()
            if not text:
                return None
            box = item.get("box") or item.get("points")
            conf = _to_float(item.get("score", item.get("conf")))
            return OCRLine(text=text, box=box, conf=conf)

        if not isinstance(item, (list, tuple)):
            return None

        # 常见格式1: [box, text, score]
        if len(item) >= 2 and isinstance(item[1], str):
            box = item[0]
            text = item[1].strip()
            conf = _to_float(item[2]) if len(item) >= 3 else None
            if text:
                return OCRLine(text=text, box=box, conf=conf)
            return None

        # 常见格式2（Paddle风格）: [box, (text, score)]
        if len(item) >= 2 and isinstance(item[1], (list, tuple)) and len(item[1]) >= 1:
            text = str(item[1][0]).strip()
            if not text:
                return None
            conf = _to_float(item[1][1]) if len(item[1]) >= 2 else None
            return OCRLine(text=text, box=item[0], conf=conf)

        return None

    def infer_lines(self, img: Any) -> List[OCRLine]:
        # RapidOCR 常见返回：(ocr_res, elapse)
        raw = self._ocr(img)
        result = raw[0] if isinstance(raw, tuple) and len(raw) >= 1 else raw
        if result is None:
            return []

        lines: List[OCRLine] = []

        # 一些版本返回对象：boxes/txts/scores
        if hasattr(result, "boxes") and hasattr(result, "txts"):
            boxes = list(getattr(result, "boxes") or [])
            txts = list(getattr(result, "txts") or [])
            scores = list(getattr(result, "scores") or [])
            for idx, text in enumerate(txts):
                t = str(text).strip()
                if not t:
                    continue
                box = boxes[idx] if idx < len(boxes) else None
                conf = _to_float(scores[idx]) if idx < len(scores) else None
                lines.append(OCRLine(text=t, box=box, conf=conf))
            return lines

        if isinstance(result, (list, tuple)):
            for item in result:
                parsed = self._parse_result_item(item)
                if parsed is not None:
                    lines.append(parsed)
        return lines


def create_ocr_engine(models_base_dir: Path) -> BaseOCREngine:
    """
    创建 OCR 引擎。

    环境变量：
    - POST_OCR_BACKEND: rapidocr | paddle | auto（默认 rapidocr）
    - POST_OCR_BACKEND_FALLBACK_PADDLE: 1/0（不设置时按后端类型决定）
    """
    backend_env = os.environ.get("POST_OCR_BACKEND")
    backend = (backend_env or "rapidocr").strip().lower() or "rapidocr"
    fallback_env = os.environ.get("POST_OCR_BACKEND_FALLBACK_PADDLE")
    if fallback_env is None or fallback_env.strip() == "":
        # 规则：
        # 1) auto 模式默认允许回退
        # 2) 用户显式指定 rapidocr 时，默认不静默回退（避免“看似切到 rapidocr 实际仍是 paddle”）
        # 3) 其他场景保持兼容，默认允许回退
        if backend == "auto":
            allow_fallback = True
        elif backend == "rapidocr" and backend_env is not None:
            allow_fallback = False
        else:
            allow_fallback = True
    else:
        allow_fallback = fallback_env.strip().lower() not in {"0", "false", "off", "no"}

    logger.info(
        "create_ocr_engine: request=%s explicit=%s fallback=%s python=%s",
        backend,
        backend_env is not None,
        allow_fallback,
        sys.executable,
    )

    if backend in {"rapidocr", "onnx"}:
        try:
            engine = RapidOCREngine(models_base_dir=models_base_dir)
            logger.info("create_ocr_engine: using backend=%s", engine.backend_name)
            return engine
        except Exception as e:
            logger.exception("create_ocr_engine: rapidocr 初始化失败")
            if allow_fallback:
                logger.warning("create_ocr_engine: 已回退到 paddle")
                engine = PaddleOCREngine(models_base_dir=models_base_dir)
                logger.info("create_ocr_engine: using backend=%s", engine.backend_name)
                return engine
            raise RuntimeError(
                "POST_OCR_BACKEND=rapidocr 初始化失败，且未启用回退。"
                "请先安装 rapidocr-onnxruntime，或设置 POST_OCR_BACKEND_FALLBACK_PADDLE=1。"
            ) from e

    if backend == "paddle":
        engine = PaddleOCREngine(models_base_dir=models_base_dir)
        logger.info("create_ocr_engine: using backend=%s", engine.backend_name)
        return engine

    # auto: 优先 rapidocr，失败回退 paddle
    if backend == "auto":
        try:
            engine = RapidOCREngine(models_base_dir=models_base_dir)
            logger.info("create_ocr_engine: using backend=%s", engine.backend_name)
            return engine
        except Exception:
            logger.exception("create_ocr_engine: auto 模式 rapidocr 初始化失败，回退 paddle")
            engine = PaddleOCREngine(models_base_dir=models_base_dir)
            logger.info("create_ocr_engine: using backend=%s", engine.backend_name)
            return engine

    # 未知值兜底
    logger.warning("create_ocr_engine: 未知后端 '%s'，回退 paddle", backend)
    engine = PaddleOCREngine(models_base_dir=models_base_dir)
    logger.info("create_ocr_engine: using backend=%s", engine.backend_name)
    return engine
