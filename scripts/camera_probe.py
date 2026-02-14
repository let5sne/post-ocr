#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
摄像头探测脚本（用于排查 macOS/iPhone 连续互通相机无画面问题）

用法：
  source .venv/bin/activate
  python scripts/camera_probe.py

输出：
- 列出 0~9 号摄像头是否可打开、是否可读到有效帧、帧尺寸与亮度均值
"""

from __future__ import annotations

import sys


def open_cap(cv2, cam_id: int):
    if sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
        return cv2.VideoCapture(cam_id, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(cam_id)


def main() -> int:
    import cv2  # pylint: disable=import-error

    print(f"平台: {sys.platform}")
    print(f"OpenCV: {cv2.__version__}")
    print("")

    found_any = False
    for cam_id in range(10):
        cap = open_cap(cv2, cam_id)
        opened = cap.isOpened()
        ok = False
        shape = None
        mean = None
        if opened:
            for _ in range(30):
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    ok = True
                    shape = frame.shape
                    mean = float(frame.mean())
                    break
        cap.release()

        if opened:
            found_any = True
        status = "OK" if ok else ("打开但无画面" if opened else "无法打开")
        print(f"摄像头 {cam_id}: {status}", end="")
        if ok:
            print(f" | shape={shape} | mean={mean:.1f}")
        else:
            print("")

    if not found_any:
        print("\n未检测到可打开的摄像头。")
    else:
        print("\n如果出现“打开但无画面”，优先检查 macOS 相机权限。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

