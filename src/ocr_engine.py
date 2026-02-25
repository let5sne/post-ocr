from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
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


class RapidOCREngine(BaseOCREngine):
    backend_name = "rapidocr"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR

        kwargs: dict[str, Any] = {}
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

        # Det.box_thresh default 0.5 misses small text on envelopes; lower to 0.3
        det_box_thresh_env = os.environ.get("POST_OCR_RAPID_DET_BOX_THRESH", "").strip()
        det_box_thresh = 0.3
        if det_box_thresh_env:
            try:
                det_box_thresh = float(det_box_thresh_env)
            except ValueError:
                pass
        kwargs["det_box_thresh"] = det_box_thresh

        text_score_env = os.environ.get("POST_OCR_RAPID_TEXT_SCORE", "").strip()
        text_score = 0.3
        if text_score_env:
            try:
                text_score = float(text_score_env)
            except ValueError:
                pass
        kwargs["text_score"] = text_score

        self._ocr = RapidOCR(**kwargs)

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

        # Format 1: [box, text, score]
        if len(item) >= 2 and isinstance(item[1], str):
            box = item[0]
            text = item[1].strip()
            conf = _to_float(item[2]) if len(item) >= 3 else None
            if text:
                return OCRLine(text=text, box=box, conf=conf)
            return None

        # Format 2 (Paddle-style): [box, (text, score)]
        if len(item) >= 2 and isinstance(item[1], (list, tuple)) and len(item[1]) >= 1:
            text = str(item[1][0]).strip()
            if not text:
                return None
            conf = _to_float(item[1][1]) if len(item[1]) >= 2 else None
            return OCRLine(text=text, box=item[0], conf=conf)

        return None

    def infer_lines(self, img: Any) -> List[OCRLine]:
        raw = self._ocr(img)
        result = raw[0] if isinstance(raw, tuple) and len(raw) >= 1 else raw
        if result is None:
            return []

        lines: List[OCRLine] = []

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


def create_ocr_engine() -> BaseOCREngine:
    """Create OCR engine (RapidOCR only)."""
    logger.info("create_ocr_engine: initializing RapidOCR, python=%s", sys.executable)
    engine = RapidOCREngine()
    logger.info("create_ocr_engine: using backend=%s", engine.backend_name)
    return engine
