from __future__ import annotations

# 必须在所有 paddle/numpy import 之前设置，否则 macOS spawn 子进程推理会死锁
import os
import logging
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_DISABLE_SIGNAL_HANDLER"] = "1"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

from pathlib import Path
from typing import Any

from ocr_engine import create_ocr_engine
from processor import extract_info

logger = logging.getLogger("post_ocr.ocr_worker")


def run_ocr_worker(models_base_dir: str, request_q, response_q) -> None:
    """
    OCR 子进程主循环：
    - 在子进程内初始化 PaddleOCR，避免阻塞主 UI 进程
    - 接收任务并返回结构化结果
    """
    try:
        response_q.put({"type": "progress", "stage": "init_start"})
        engine = create_ocr_engine(models_base_dir=Path(models_base_dir))
        response_q.put({"type": "ready", "backend": getattr(engine, "backend_name", "unknown")})
    except Exception as e:
        logger.exception("OCR 子进程初始化失败")
        response_q.put({"type": "init_error", "error": str(e)})
        return

    while True:
        item = request_q.get()
        if item is None:
            break

        job_id = -1
        try:
            job_id, images = item
            if not isinstance(images, (list, tuple)) or len(images) == 0:
                raise ValueError("内部错误：未传入有效图片数据")

            response_q.put({"type": "progress", "job_id": int(job_id), "stage": "job_received", "images": len(images)})
            ocr_texts: list[str] = []
            ocr_lines: list[dict[str, Any]] = []
            for roi_index, entry in enumerate(images):
                source = "main"
                img = entry
                y_offset = 0
                if isinstance(entry, dict):
                    source = str(entry.get("source", "main"))
                    img = entry.get("img")
                    y_offset = int(entry.get("y_offset", 0))
                elif roi_index > 0:
                    source = "number"
                if img is None:
                    continue
                response_q.put({"type": "progress", "job_id": int(job_id), "stage": f"roi_{roi_index}_start"})
                lines = engine.infer_lines(img)
                response_q.put({"type": "progress", "job_id": int(job_id), "stage": f"roi_{roi_index}_done"})
                for line in lines:
                    text = str(line.text).strip()
                    if not text:
                        continue
                    ocr_texts.append(text)
                    # 将切片内的局部坐标还原为完整 ROI 坐标
                    box = line.box
                    if y_offset and isinstance(box, (list, tuple)):
                        box = [[p[0], p[1] + y_offset] for p in box]
                    ocr_lines.append(
                        {
                            "text": text,
                            "box": box,
                            "conf": line.conf,
                            "source": source,
                            "roi_index": roi_index,
                        }
                    )

            record = extract_info(ocr_lines if ocr_lines else ocr_texts)
            response_q.put({"type": "progress", "job_id": int(job_id), "stage": "parse_done", "texts": len(ocr_texts)})
            response_q.put(
                {
                    "type": "result",
                    "job_id": int(job_id),
                    "record": record,
                    "texts": ocr_texts,
                }
            )
        except Exception as e:
            logger.exception("OCR 子进程处理任务失败 job=%s", job_id)
            response_q.put({"type": "error", "job_id": int(job_id), "error": str(e)})
