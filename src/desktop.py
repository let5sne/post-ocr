#!/usr/bin/env python3
"""
信封信息提取系统 - 桌面版
使用 Droidcam 将手机作为摄像头，实时预览并识别信封信息
"""
import os
import sys
import cv2
import pandas as pd
import time
import logging
import threading
import queue
import multiprocessing as mp
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QComboBox,
    QFileDialog, QMessageBox, QGroupBox, QSplitter, QHeaderView,
    QStatusBar, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap, QFont, QAction, QKeySequence, QShortcut, QColor, QBrush

from ocr_worker_process import run_ocr_worker

logger = logging.getLogger("post_ocr.desktop")


def setup_logging() -> Path:
    """
    日志输出：
    - 终端实时打印
    - 写入 data/output/desktop.log（便于用户反馈与排查）
    """

    level_name = os.environ.get("POST_OCR_LOG_LEVEL", "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)

    log_dir = Path("data/output").resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "desktop.log"

    fmt = "%(asctime)s.%(msecs)03d %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(level)

    # 清理旧 handler，避免重复输出
    for h in list(root.handlers):
        root.removeHandler(h)

    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setLevel(level)
    sh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    root.addHandler(sh)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    root.addHandler(fh)

    logger.info("日志已初始化，level=%s, file=%s", level_name, str(log_file))
    return log_file


class OCRService(QObject):
    """
    OCR 后台服务（运行在独立子进程中）。

    关键点：
    - PaddleOCR 初始化与推理都放到子进程，避免阻塞 UI 主进程
    - 主进程只做任务投递与结果回调
    - 子进程异常或卡住时，可通过重启服务恢复
    """

    finished = pyqtSignal(int, dict, list)
    error = pyqtSignal(int, str)
    ready = pyqtSignal()
    init_error = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._busy = False
        self.backend_name = "unknown"
        self._stop_event = threading.Event()
        backend_req = os.environ.get("POST_OCR_BACKEND", "rapidocr").strip().lower() or "rapidocr"
        if sys.platform == "darwin":
            # macOS + PyQt/OpenCV 场景下 fork 对 ONNX 推理稳定性较差，rapidocr 默认走 spawn。
            # Paddle 在 macOS 历史上与 spawn 组合更容易出现卡住，因此保留 fork。
            method_default = "spawn"
        else:
            method_default = "spawn"
        method = os.environ.get("POST_OCR_MP_START_METHOD", method_default).strip() or method_default
        try:
            self._ctx = mp.get_context(method)
        except ValueError:
            method = method_default
            self._ctx = mp.get_context(method_default)
        logger.info("OCR multiprocessing start_method=%s (backend_req=%s)", method, backend_req)
        self._req_q = None
        self._resp_q = None
        self._proc = None
        self._reader_thread = None

    def _set_busy(self, busy: bool) -> None:
        if self._busy != busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def start(self) -> None:
        """启动 OCR 子进程与响应监听线程。"""

        self._stop_event.clear()
        self._req_q = self._ctx.Queue(maxsize=1)
        self._resp_q = self._ctx.Queue()
        self._proc = self._ctx.Process(
            target=run_ocr_worker,
            args=(self._req_q, self._resp_q),
            name="OCRProcess",
            daemon=True,
        )
        self._proc.start()
        self._reader_thread = threading.Thread(
            target=self._read_responses,
            name="OCRRespReader",
            daemon=True,
        )
        self._reader_thread.start()

    def stop(self, timeout_ms: int = 8000) -> bool:
        """停止 OCR 子进程与监听线程。"""

        try:
            self._stop_event.set()
            try:
                if self._req_q is not None:
                    self._req_q.put_nowait(None)
            except Exception:
                pass
            if self._reader_thread is not None:
                self._reader_thread.join(timeout=max(0.0, timeout_ms / 1000.0))

            proc_alive = False
            if self._proc is not None:
                self._proc.join(timeout=max(0.0, timeout_ms / 1000.0))
                if self._proc.is_alive():
                    proc_alive = True
                    self._proc.terminate()
                    self._proc.join(timeout=1.0)

            self._set_busy(False)
            return not proc_alive
        except Exception:
            self._set_busy(False)
            return False
        finally:
            self._proc = None
            self._reader_thread = None
            self._req_q = None
            self._resp_q = None

    def _read_responses(self) -> None:
        """读取 OCR 子进程响应并转发为 Qt 信号。"""
        while not self._stop_event.is_set():
            try:
                if self._resp_q is None:
                    return
                msg = self._resp_q.get(timeout=0.2)
            except queue.Empty:
                continue
            except Exception:
                if not self._stop_event.is_set():
                    self.init_error.emit("OCR 子进程通信失败")
                return

            if not isinstance(msg, dict):
                continue
            msg_type = str(msg.get("type", "")).strip()
            if msg_type == "progress":
                job_id = msg.get("job_id", "-")
                stage = msg.get("stage", "")
                extra = []
                if "images" in msg:
                    extra.append(f"images={msg.get('images')}")
                if "texts" in msg:
                    extra.append(f"texts={msg.get('texts')}")
                suffix = f" ({', '.join(extra)})" if extra else ""
                logger.info("OCR 子进程进度 job=%s stage=%s%s", job_id, stage, suffix)
                continue
            if msg_type == "ready":
                self.backend_name = str(msg.get("backend", "unknown"))
                logger.info(
                    "OCR 子进程已就绪 pid=%s backend=%s",
                    getattr(self._proc, "pid", None),
                    self.backend_name,
                )
                self.ready.emit()
                continue
            if msg_type == "init_error":
                self._set_busy(False)
                self.init_error.emit(str(msg.get("error", "OCR 初始化失败")))
                continue
            if msg_type == "result":
                self._set_busy(False)
                try:
                    job_id = int(msg.get("job_id"))
                except Exception:
                    job_id = -1
                record = msg.get("record") if isinstance(msg.get("record"), dict) else {}
                texts = msg.get("texts") if isinstance(msg.get("texts"), list) else []
                self.finished.emit(job_id, record, texts)
                continue
            if msg_type == "error":
                self._set_busy(False)
                try:
                    job_id = int(msg.get("job_id"))
                except Exception:
                    job_id = -1
                self.error.emit(job_id, str(msg.get("error", "OCR 处理失败")))
                continue

    @pyqtSlot(int, object)
    def process(self, job_id: int, images: object) -> None:
        """接收 UI 请求并投递到 OCR 子进程。"""

        if self._stop_event.is_set():
            self.error.emit(job_id, "OCR 服务正在关闭，请稍后重试。")
            return
        if self._proc is None or (not self._proc.is_alive()):
            self.error.emit(job_id, "OCR 服务未就绪，请稍后重试。")
            return
        if self._busy:
            self.error.emit(job_id, "OCR 正在进行中，请稍后再试。")
            return
        if not isinstance(images, (list, tuple)) or len(images) == 0:
            self.error.emit(job_id, "内部错误：未传入有效图片数据")
            return
        try:
            shapes = []
            for item in images:
                img = item
                source = "main"
                if isinstance(item, dict):
                    img = item.get("img")
                    source = str(item.get("source", "main"))
                try:
                    shapes.append({"source": source, "shape": getattr(img, "shape", None)})
                except Exception:
                    shapes.append({"source": source, "shape": None})
            logger.info("OCR job=%s 投递到子进程，images=%s", job_id, shapes)

            self._set_busy(True)
            if self._req_q is None:
                raise RuntimeError("OCR 请求队列不可用")
            self._req_q.put_nowait((int(job_id), list(images)))
        except queue.Full:
            self._set_busy(False)
            self.error.emit(job_id, "OCR 队列已满，请稍后再试。")
        except Exception as e:
            self._set_busy(False)
            self.error.emit(job_id, f"OCR 入队失败：{str(e)}")


class MainWindow(QMainWindow):
    request_ocr = pyqtSignal(int, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("📮 信封信息提取系统")
        self.setMinimumSize(1200, 700)

        # OCR 工作线程（避免 UI 卡死）
        self._ocr_job_id = 0
        self._ocr_pending_job_id = None
        self._ocr_start_time_by_job: dict[int, float] = {}
        self._ocr_ready = False
        self._ocr_busy = False
        self._shutting_down = False
        self._ocr_timeout_prompted = False
        self._ocr_restarting = False

        # 摄像头
        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self._frame_fail_count = 0
        self._last_frame = None
        self._last_frame_ts = 0.0
        self._capture_in_progress = False

        # 状态栏进度（识别中显示）
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(160)
        self._progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._progress)

        # OCR 看门狗：显示耗时、并在疑似卡住时提示重启
        self._ocr_watchdog = QTimer()
        self._ocr_watchdog.setInterval(300)
        self._ocr_watchdog.timeout.connect(self._tick_ocr_watchdog)

        # 数据
        self.records = []

        self.init_ui()
        self.load_cameras()

        # OCR 服务放在 UI 初始化之后启动，避免 ready/busy 信号回调时 btn_capture 尚未创建
        self.statusBar().showMessage("正在启动 OCR 服务...")
        QApplication.processEvents()
        try:
            self._init_ocr_service()
        except FileNotFoundError as e:
            QMessageBox.critical(self, "离线模型缺失", str(e))
            raise
        except Exception as e:
            QMessageBox.critical(self, "启动失败", str(e))
            raise

    def shutdown(self, force: bool = False) -> None:
        """停止摄像头并关闭后台服务，避免退出时后台任务仍在运行。"""

        if self._shutting_down:
            return
        self._shutting_down = True

        # 先停止摄像头，避免继续读帧
        try:
            if self.cap:
                self.timer.stop()
                self.cap.release()
                self.cap = None
        except Exception:
            pass

        try:
            self._stop_ocr_service(force=force)
        except Exception:
            pass

    def _stop_ocr_service(self, force: bool = False) -> None:
        """仅停止 OCR 服务（用于超时重启/退出）。"""

        try:
            self._ocr_watchdog.stop()
        except Exception:
            pass

        self._ocr_ready = False
        self._ocr_busy = False
        self._ocr_timeout_prompted = False
        self._ocr_pending_job_id = None
        self._ocr_start_time_by_job.clear()
        try:
            self._progress.setVisible(False)
        except Exception:
            pass

        try:
            svc = getattr(self, "_ocr_service", None)
            if svc is not None:
                try:
                    self.request_ocr.disconnect(svc.process)
                except Exception:
                    pass
                ok = svc.stop(timeout_ms=8000 if force else 3000)
                if (not ok) and force:
                    logger.warning("OCR 服务停止超时：子进程可能仍在退出中，建议重启应用。")
        except Exception:
            pass

        try:
            self._ocr_service = None
        except Exception:
            pass

    def _restart_ocr_service(self) -> None:
        """重启 OCR 服务（用于超时恢复）。"""

        if self._shutting_down:
            return
        if self._ocr_restarting:
            return
        self._ocr_restarting = True
        try:
            self.statusBar().showMessage("正在重启 OCR 服务...")
            self._stop_ocr_service(force=True)
            self._init_ocr_service()
        finally:
            self._ocr_restarting = False

    def _init_ocr_service(self) -> None:
        self._ocr_service = OCRService()

        # 注意：OCRService 内部使用独立子进程做 warmup 与推理。
        # 这里强制使用 QueuedConnection，确保 UI 回调始终在主线程执行。
        self.request_ocr.connect(self._ocr_service.process, Qt.ConnectionType.QueuedConnection)
        self._ocr_service.ready.connect(self._on_ocr_ready, Qt.ConnectionType.QueuedConnection)
        self._ocr_service.init_error.connect(self._on_ocr_init_error, Qt.ConnectionType.QueuedConnection)
        self._ocr_service.busy_changed.connect(self._on_ocr_busy_changed, Qt.ConnectionType.QueuedConnection)
        self._ocr_service.finished.connect(self._on_ocr_finished_job, Qt.ConnectionType.QueuedConnection)
        self._ocr_service.error.connect(self._on_ocr_error_job, Qt.ConnectionType.QueuedConnection)

        self._ocr_service.start()

    def _on_ocr_ready(self) -> None:
        try:
            self._ocr_ready = True
            backend = "unknown"
            try:
                backend = str(getattr(self._ocr_service, "backend_name", "unknown"))
            except Exception:
                backend = "unknown"
            self.statusBar().showMessage(f"OCR 模型已加载（{backend}）")
            btn = getattr(self, "btn_capture", None)
            if btn is not None:
                btn.setEnabled(self.cap is not None and not self._ocr_busy)
            logger.info("OCR ready backend=%s", backend)
        except Exception as e:
            logger.exception("处理 OCR ready 回调失败：%s", str(e))

    def _on_ocr_init_error(self, error: str) -> None:
        self.statusBar().showMessage("OCR 模型加载失败")
        QMessageBox.critical(self, "OCR 初始化失败", error)
        logger.error("OCR init error: %s", error)

    def _on_ocr_busy_changed(self, busy: bool) -> None:
        try:
            self._ocr_busy = busy
            if busy:
                # OCR 线程已开始处理，提交阶段不再算“待接收”
                self._ocr_pending_job_id = None
                self._progress.setRange(0, 0)  # 不确定进度条
                self._progress.setVisible(True)
                self._ocr_timeout_prompted = False
                self._ocr_watchdog.start()
            else:
                self._progress.setVisible(False)
                self._ocr_watchdog.stop()
            btn = getattr(self, "btn_capture", None)
            if btn is not None:
                btn.setEnabled(self.cap is not None and self._ocr_ready and not busy)
        except Exception as e:
            logger.exception("处理 OCR busy 回调失败：%s", str(e))

    def _guard_ocr_submission(self, job_id: int) -> None:
        """
        兜底保护：
        如果提交后一段时间仍未进入 busy 状态，说明任务可能未被 OCR 线程接收，
        主动恢复按钮，避免界面一直停留在“正在识别...”。
        """

        if job_id != self._ocr_pending_job_id:
            return
        if self._ocr_busy:
            return

        self._ocr_pending_job_id = None
        self._ocr_start_time_by_job.pop(job_id, None)
        logger.warning("OCR job=%s 提交后未被接收，已自动恢复 UI 状态", job_id)
        self.statusBar().showMessage("识别请求未被处理，请重试一次（已自动恢复）")
        if self.btn_capture is not None:
            self.btn_capture.setEnabled(self.cap is not None and self._ocr_ready)

    def _tick_ocr_watchdog(self) -> None:
        """识别进行中：更新耗时，超时自动重启 OCR 服务。"""

        if not self._ocr_busy:
            return
        start_t = self._ocr_start_time_by_job.get(self._ocr_job_id)
        if start_t is None:
            return
        cost = time.monotonic() - start_t
        self.statusBar().showMessage(f"正在识别...（已用 {cost:.1f}s）")

        # 超时保护：底层推理偶发卡住时，自动重启 OCR 服务并恢复可用状态
        timeout_sec = 25
        try:
            timeout_sec = max(
                8, int(os.environ.get("POST_OCR_JOB_TIMEOUT_SEC", "25").strip() or "25")
            )
        except Exception:
            timeout_sec = 25
        if cost >= timeout_sec and not self._ocr_timeout_prompted:
            self._ocr_timeout_prompted = True
            logger.warning("OCR job=%s 超时 %.1fs，自动重启 OCR 服务", self._ocr_job_id, cost)
            self.statusBar().showMessage(f"识别超时（{cost:.1f}s），正在自动恢复...")
            # 当前任务视为失败并回收，避免界面一直等待结果
            self._ocr_start_time_by_job.pop(self._ocr_job_id, None)
            self._restart_ocr_service()
            QMessageBox.warning(
                self,
                "识别超时",
                "本次识别超时，已自动重启 OCR 服务。\n请再次拍照识别。",
            )

    def _on_ocr_finished_job(self, job_id: int, record: dict, texts: list) -> None:
        if self._ocr_pending_job_id == job_id:
            self._ocr_pending_job_id = None
        start_t = self._ocr_start_time_by_job.pop(job_id, None)

        # 只处理最新一次请求，避免旧结果回写
        if job_id != self._ocr_job_id:
            return

        logger.info("OCR job=%s 原始文本: %s", job_id, texts)
        logger.info("OCR job=%s 解析结果: %s", job_id, record)

        self.records.append(record)
        self.update_table()
        cost = ""
        if start_t is not None:
            cost = f"（耗时 {time.monotonic() - start_t:.1f}s）"
        self.statusBar().showMessage(f"识别完成: {record.get('联系人/单位名', '未知')}{cost}")
        logger.info("OCR job=%s UI 回写完成 %s", job_id, cost)
        self.btn_capture.setEnabled(self.cap is not None and self._ocr_ready and not self._ocr_busy)

    def _on_ocr_error_job(self, job_id: int, error: str) -> None:
        if self._ocr_pending_job_id == job_id:
            self._ocr_pending_job_id = None
        self._ocr_start_time_by_job.pop(job_id, None)
        if job_id != self._ocr_job_id:
            return
        self.statusBar().showMessage("识别失败")
        QMessageBox.warning(self, "识别失败", error)
        logger.error("OCR job=%s error: %s", job_id, error)
        self.btn_capture.setEnabled(self.cap is not None and self._ocr_ready and not self._ocr_busy)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # 左侧：摄像头预览
        left_panel = QGroupBox("📷 摄像头预览")
        left_layout = QVBoxLayout(left_panel)

        # 摄像头选择
        cam_layout = QHBoxLayout()
        cam_layout.addWidget(QLabel("摄像头:"))
        self.cam_combo = QComboBox()
        self.cam_combo.setMinimumWidth(200)
        cam_layout.addWidget(self.cam_combo)
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self.load_cameras)
        cam_layout.addWidget(self.btn_refresh)
        self.btn_connect = QPushButton("▶ 连接")
        self.btn_connect.clicked.connect(self.toggle_camera)
        cam_layout.addWidget(self.btn_connect)
        cam_layout.addStretch()
        left_layout.addLayout(cam_layout)

        # 视频画面
        self.video_label = QLabel()
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #1a1a1a; border: 2px solid #333; border-radius: 8px;")
        self.video_label.setText("点击「连接」启动摄像头\n\n支持 Droidcam / Iriun 等虚拟摄像头")
        left_layout.addWidget(self.video_label)

        # 拍照按钮
        self.btn_capture = QPushButton("📸 拍照识别 (空格键)")
        self.btn_capture.setMinimumHeight(50)
        self.btn_capture.setFont(QFont("", 14))
        self.btn_capture.setStyleSheet("background-color: #ff4b4b; color: white; border-radius: 8px;")
        self.btn_capture.clicked.connect(self.capture_and_recognize)
        self.btn_capture.setEnabled(False)  # 等摄像头连接 + OCR ready 后启用
        left_layout.addWidget(self.btn_capture)

        # 右侧：结果列表
        right_panel = QGroupBox(f"📋 已识别记录 (0)")
        self.right_panel = right_panel
        right_layout = QVBoxLayout(right_panel)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["编号", "邮编", "地址", "联系人", "电话"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        right_layout.addWidget(self.table)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self.btn_delete = QPushButton("🗑 删除选中")
        self.btn_delete.clicked.connect(self.delete_selected)
        btn_layout.addWidget(self.btn_delete)

        self.btn_clear = QPushButton("🧹 清空全部")
        self.btn_clear.clicked.connect(self.clear_all)
        btn_layout.addWidget(self.btn_clear)

        self.btn_export = QPushButton("📥 导出 Excel")
        self.btn_export.setStyleSheet("background-color: #4CAF50; color: white;")
        self.btn_export.clicked.connect(self.export_excel)
        btn_layout.addWidget(self.btn_export)

        right_layout.addLayout(btn_layout)

        # 分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([600, 500])
        layout.addWidget(splitter)

        # 快捷键
        # macOS/Qt 下 Space 经常被控件吞掉（按钮激活/表格选择等），用 ApplicationShortcut 更稳
        self._shortcut_capture2 = QShortcut(QKeySequence("Space"), self)
        self._shortcut_capture2.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut_capture2.setAutoRepeat(False)
        self._shortcut_capture2.activated.connect(self.capture_and_recognize)

    def load_cameras(self):
        """扫描可用摄像头"""
        self.cam_combo.clear()

        # 始终提供手机 MJPEG 流入口（Android 端 MjpegServer 默认端口 8080）
        # 使用前需：1) USB 连接手机  2) adb forward tcp:8080 tcp:8080
        mjpeg_url = os.environ.get("POST_OCR_MJPEG_URL", "http://localhost:8080").strip()
        self.cam_combo.addItem(f"📱 手机摄像头 (USB)", mjpeg_url)

        # macOS 上设备编号会变化（尤其"连续互通相机"/虚拟摄像头），这里多扫一些更稳。
        # 若你想减少探测范围，可设置环境变量 POST_OCR_MAX_CAMERAS，例如：POST_OCR_MAX_CAMERAS=3
        try:
            max_probe = int(os.environ.get("POST_OCR_MAX_CAMERAS", "").strip() or "10")
        except Exception:
            max_probe = 10
        logger.info("开始扫描摄像头：max_probe=%s", max_probe)

        found = 0
        for i in range(max_probe):
            cap = None
            try:
                cap = self._open_capture(i)
                if cap is None or (not cap.isOpened()):
                    continue

                # 暖机：有些设备首帧为空或延迟较大（尤其手机/虚拟摄像头）
                has_frame = False
                for _ in range(25):
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        has_frame = True
                        break
                label = f"摄像头 {i}" if has_frame else f"摄像头 {i}（未验证画面）"
                self.cam_combo.addItem(label, i)
                logger.info("摄像头探测：id=%s opened, has_frame=%s", i, has_frame)
                found += 1
            finally:
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass

        if found == 0:
            # 自动探测失败时，仅提供少量手动入口（0~2），避免列出大量不存在的设备误导用户
            fallback_count = min(3, max_probe)
            for i in range(fallback_count):
                self.cam_combo.addItem(f"摄像头 {i}（手动尝试）", i)
            if sys.platform == "win32":
                hint = (
                    "未检测到摄像头。请确认：1) 已连接摄像头或已启动 Droidcam/Iriun；"
                    "2) 其他应用未占用摄像头；3) 可手动选择编号后点击「连接」尝试。"
                )
            else:
                hint = (
                    "未检测到摄像头。"
                    "macOS 请在 系统设置->隐私与安全->相机 中允许访问；"
                    "并确保 iPhone 已解锁且未被其他应用占用。"
                )
            self.statusBar().showMessage(hint)
        else:
            self.statusBar().showMessage(f"检测到 {found} 个摄像头")
        logger.info("摄像头扫描结束：found=%s", found)

    def _adb_forward(self, local_port: int = 8080, remote_port: int = 8080) -> bool:
        """自动执行 adb forward，将手机端口映射到本地。成功返回 True。"""
        cmd = ["adb", "forward", f"tcp:{local_port}", f"tcp:{remote_port}"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                logger.info("adb forward 成功：%s", " ".join(cmd))
                return True
            # adb 存在但执行失败（如无设备）
            stderr = (r.stderr or "").strip()
            logger.warning("adb forward 失败(rc=%s): %s", r.returncode, stderr)
            QMessageBox.warning(
                self,
                "ADB 端口转发失败",
                f"执行 adb forward 失败：\n{stderr}\n\n"
                "排查建议：\n"
                "1) 手机通过 USB 数据线连接电脑\n"
                "2) 手机开启 USB 调试（开发者选项）\n"
                "3) 首次连接时在手机上点击「允许 USB 调试」\n",
            )
            return False
        except FileNotFoundError:
            logger.warning("adb 未找到，请确认已安装 Android SDK Platform-Tools")
            QMessageBox.warning(
                self,
                "未找到 ADB",
                "未找到 adb 命令。\n\n"
                "请安装 Android SDK Platform-Tools 并确保 adb 在 PATH 中。\n"
                "下载地址：https://developer.android.com/tools/releases/platform-tools",
            )
            return False
        except subprocess.TimeoutExpired:
            logger.warning("adb forward 超时")
            QMessageBox.warning(self, "ADB 超时", "adb forward 执行超时，请检查 USB 连接。")
            return False

    def _open_capture(self, cam_id):
        """
        打开摄像头。

        cam_id 可以是：
        - int: 本地摄像头索引（0, 1, 2...）
        - str: MJPEG 流 URL（如 http://localhost:8080）

        本地摄像头：
        - Windows 优先使用 DirectShow 后端（更快更稳定）
        - macOS 优先使用 AVFoundation 后端（对"连续互通相机"等更友好）
        """

        # MJPEG 流 URL：直接用 OpenCV 打开
        if isinstance(cam_id, str):
            logger.info("打开 MJPEG 流：%s", cam_id)
            return cv2.VideoCapture(cam_id)

        if sys.platform == "win32" and hasattr(cv2, "CAP_DSHOW"):
            cap = cv2.VideoCapture(cam_id, cv2.CAP_DSHOW)
            try:
                if cap is not None and cap.isOpened():
                    return cap
            except Exception:
                pass
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
        elif sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
            cap = cv2.VideoCapture(cam_id, cv2.CAP_AVFOUNDATION)
            try:
                if cap is not None and cap.isOpened():
                    return cap
            except Exception:
                pass
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
        return cv2.VideoCapture(cam_id)

    def toggle_camera(self):
        """连接/断开摄像头"""
        if self.cap is None:
            cam_id = self.cam_combo.currentData()
            if cam_id is None:
                QMessageBox.warning(self, "错误", "请先选择有效的摄像头")
                return
            # int 类型的 cam_id 需 >= 0；str 类型为 MJPEG URL
            if isinstance(cam_id, int) and cam_id < 0:
                QMessageBox.warning(self, "错误", "请先选择有效的摄像头")
                return

            is_mjpeg = isinstance(cam_id, str)
            if is_mjpeg:
                self.statusBar().showMessage("正在设置 ADB 端口转发...")
                QApplication.processEvents()
                if not self._adb_forward():
                    return
                self.statusBar().showMessage(f"正在连接手机摄像头 {cam_id} ...")
                QApplication.processEvents()

            self.cap = self._open_capture(cam_id)

            if self.cap.isOpened():
                # 不强制分辨率：某些设备（尤其虚拟摄像头/连续互通相机）被强设后会输出黑屏
                # self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                # self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

                # 暖机读取，尽早发现“能打开但无画面”的情况
                ok = False
                for _ in range(20):
                    ret, frame = self.cap.read()
                    if ret and frame is not None and frame.size > 0:
                        ok = True
                        break
                if not ok:
                    self.cap.release()
                    self.cap = None
                    if is_mjpeg:
                        QMessageBox.warning(
                            self,
                            "手机摄像头无画面",
                            "已连接但读取不到画面。\n\n"
                            "排查建议：\n"
                            "1) 确认手机端 App 已点击「启动」\n"
                            "2) 确认已执行：adb forward tcp:8080 tcp:8080\n"
                            "3) 检查 USB 线是否为数据线（非纯充电线）\n",
                        )
                    else:
                        QMessageBox.warning(
                            self,
                            "摄像头无画面",
                            "摄像头已打开，但读取不到画面。\n\n"
                            "排查建议：\n"
                            "1) 确认摄像头未被其他应用占用\n"
                            "2) 依次切换「摄像头 0/1/2」尝试\n",
                        )
                    return

                self.timer.start(30)  # ~33 FPS
                self.btn_connect.setText("⏹ 断开")
                self.btn_capture.setEnabled(self._ocr_ready and not self._ocr_busy)
                self.cam_combo.setEnabled(False)
                self.statusBar().showMessage("摄像头已连接")
            else:
                self.cap = None
                if is_mjpeg:
                    QMessageBox.warning(
                        self,
                        "无法连接手机摄像头",
                        f"无法连接 {cam_id}\n\n"
                        "排查步骤：\n"
                        "1) 手机通过 USB 数据线连接电脑\n"
                        "2) 手机开启 USB 调试（开发者选项）\n"
                        "3) 手机端 App 点击「启动」\n"
                        "4) 电脑终端执行：adb forward tcp:8080 tcp:8080\n"
                        "5) 再点击「连接」\n",
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "无法打开摄像头",
                        "无法打开摄像头。\n\n"
                        "排查建议：\n"
                        "1) 确认摄像头未被其他应用占用\n"
                        "2) 在下拉框中切换不同编号重试\n",
                    )
        else:
            self.timer.stop()
            self.cap.release()
            self.cap = None
            self.btn_connect.setText("▶ 连接")
            self.btn_capture.setEnabled(False)
            self.cam_combo.setEnabled(True)
            self.video_label.setText("摄像头已断开")
            self.statusBar().showMessage("摄像头已断开")

    def update_frame(self):
        """更新视频帧"""
        if self.cap is None:
            return

        ret, frame = self.cap.read()
        if ret and frame is not None and frame.size > 0:
            self._frame_fail_count = 0
            # 缓存原始帧，拍照时直接使用，避免按空格再读摄像头导致主线程阻塞
            try:
                self._last_frame = frame.copy()
                self._last_frame_ts = time.monotonic()
            except Exception:
                self._last_frame = frame
                self._last_frame_ts = time.monotonic()
            # 绘制扫描框
            h, w = frame.shape[:2]
            # 主内容区：邮编+地址+联系人+电话，占上方 85%
            x1, y1 = int(w * 0.04), int(h * 0.04)
            x2, y2 = int(w * 0.96), int(h * 0.85)

            # 绘制绿色边框
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

            # 四角加粗
            corner_len = 25
            cv2.line(frame, (x1, y1), (x1 + corner_len, y1), (0, 255, 0), 4)
            cv2.line(frame, (x1, y1), (x1, y1 + corner_len), (0, 255, 0), 4)
            cv2.line(frame, (x2, y1), (x2 - corner_len, y1), (0, 255, 0), 4)
            cv2.line(frame, (x2, y1), (x2, y1 + corner_len), (0, 255, 0), 4)
            cv2.line(frame, (x1, y2), (x1 + corner_len, y2), (0, 255, 0), 4)
            cv2.line(frame, (x1, y2), (x1, y2 - corner_len), (0, 255, 0), 4)
            cv2.line(frame, (x2, y2), (x2 - corner_len, y2), (0, 255, 0), 4)
            cv2.line(frame, (x2, y2), (x2, y2 - corner_len), (0, 255, 0), 4)

            # 编号区域提示（主内容区下方偏左）
            nx1, ny1 = int(w * 0.04), int(h * 0.87)
            nx2, ny2 = int(w * 0.50), int(h * 0.97)
            cv2.rectangle(frame, (nx1, ny1), (nx2, ny2), (0, 255, 0), 1)
            cv2.putText(frame, "Bian Hao", (nx1 + 10, ny1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # 转换为 Qt 图像
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            scaled = qimg.scaled(self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.video_label.setPixmap(QPixmap.fromImage(scaled))
        else:
            self._frame_fail_count += 1
            if self._frame_fail_count == 1:
                self.statusBar().showMessage("摄像头无画面：请检查权限/切换摄像头")

    def capture_and_recognize(self):
        """拍照并识别"""
        if self._capture_in_progress:
            self.statusBar().showMessage("正在拍照，请稍候")
            return
        if self.cap is None:
            self.statusBar().showMessage("请先连接摄像头")
            return
        if not self._ocr_ready:
            self.statusBar().showMessage("OCR 模型尚未就绪，请稍等")
            return
        if self._ocr_busy:
            self.statusBar().showMessage("正在识别中，请稍后再按空格")
            return

        self._capture_in_progress = True
        try:
            # 直接使用预览缓存帧，避免在按键回调中阻塞式 read 摄像头导致卡顿
            frame = None
            now = time.monotonic()
            if self._last_frame is not None and (now - self._last_frame_ts) <= 1.5:
                try:
                    frame = self._last_frame.copy()
                except Exception:
                    frame = self._last_frame

            if frame is None:
                self.statusBar().showMessage("尚未拿到稳定画面，请稍后再按空格")
                return

            # 裁剪主信息 ROI 与编号 ROI（与预览框一致）
            h, w = frame.shape[:2]
            x1, y1 = int(w * 0.04), int(h * 0.04)
            x2 = int(w * 0.96)
            y2_box = int(h * 0.85)

            roi_inputs = []
            try:
                roi_box = frame[y1:y2_box, x1:x2]
                if roi_box is not None and roi_box.size > 0:
                    # 主信息区域切成多段，规避大图整块检测偶发卡住
                    split_count = 1
                    try:
                        split_count = max(
                            1,
                            int(
                                os.environ.get("POST_OCR_MAIN_SPLIT", "1").strip()
                                or "1"
                            ),
                        )
                    except Exception:
                        split_count = 1
                    split_count = min(split_count, 4)

                    if split_count <= 1 or roi_box.shape[0] < 120:
                        roi_inputs.append({"img": roi_box, "source": "main", "y_offset": 0})
                    else:
                        h_box = roi_box.shape[0]
                        step = h_box / float(split_count)
                        overlap = max(8, int(h_box * 0.06))
                        for i in range(split_count):
                            sy = int(max(0, i * step - (overlap if i > 0 else 0)))
                            ey = int(
                                min(
                                    h_box,
                                    (i + 1) * step
                                    + (overlap if i < split_count - 1 else 0),
                                )
                            )
                            part = roi_box[sy:ey, :]
                            if part is not None and part.size > 0:
                                roi_inputs.append({"img": part, "source": "main", "y_offset": sy})
            except Exception:
                pass

            try:
                # 编号在主内容区下方偏左
                nx1, nx2 = int(w * 0.04), int(w * 0.50)
                ny1, ny2 = int(h * 0.87), int(h * 0.97)
                roi_num = frame[ny1:ny2, nx1:nx2]
                if roi_num is not None and roi_num.size > 0:
                    roi_inputs.append({"img": roi_num, "source": "number"})
            except Exception:
                pass

            if not roi_inputs:
                self.statusBar().showMessage("拍照失败：未截取到有效区域")
                return

            # 超大分辨率下适当缩放（提高稳定性与速度）
            resized_inputs = []
            max_w = 960
            try:
                max_w = max(
                    600, int(os.environ.get("POST_OCR_MAX_ROI_WIDTH", "960").strip() or "960")
                )
            except Exception:
                max_w = 960

            for item in roi_inputs:
                img = item.get("img")
                source = item.get("source", "main")
                y_off = item.get("y_offset", 0)
                scale = 1.0
                try:
                    if img is not None and img.shape[1] > max_w:
                        scale = max_w / img.shape[1]
                        img = cv2.resize(img, (int(img.shape[1] * scale), int(img.shape[0] * scale)))
                except Exception:
                    pass
                resized_inputs.append({"img": img, "source": source, "y_offset": int(y_off * scale)})

            logger.info(
                "UI 触发识别：frame=%s, rois=%s, frame_age=%.3fs",
                getattr(frame, "shape", None),
                [
                    {
                        "source": item.get("source", "main"),
                        "shape": getattr(item.get("img"), "shape", None),
                    }
                    for item in resized_inputs
                ],
                max(0.0, now - self._last_frame_ts),
            )

            self.statusBar().showMessage("正在识别...")
            self.btn_capture.setEnabled(False)

            # 派发到 OCR 工作线程
            self._ocr_job_id += 1
            job_id = self._ocr_job_id
            self._ocr_pending_job_id = job_id
            self._ocr_start_time_by_job[job_id] = time.monotonic()
            self.request_ocr.emit(job_id, resized_inputs)
            QTimer.singleShot(2000, lambda j=job_id: self._guard_ocr_submission(j))
        finally:
            self._capture_in_progress = False

    def update_table(self):
        """更新表格"""
        self.table.setRowCount(len(self.records))
        red_brush = QBrush(QColor(220, 40, 40))
        red_bg = QColor(255, 230, 230)
        default_brush = QBrush(QColor(0, 0, 0))
        for i, r in enumerate(self.records):
            warnings = r.get("_warnings", [])
            has_warning = bool(warnings)
            tooltip = "\n".join(warnings) if has_warning else ""

            for col, key in enumerate(["编号", "邮编", "地址", "联系人/单位名", "电话"]):
                value = r.get(key, "")
                item = QTableWidgetItem(value)
                # 整行有警告 或 当前字段为空 → 标红
                if has_warning or not value.strip():
                    item.setForeground(red_brush)
                    if not value.strip():
                        item.setBackground(red_bg)
                        item.setToolTip(f"⚠ {key}为空")
                    elif tooltip:
                        item.setToolTip(tooltip)
                else:
                    item.setForeground(default_brush)
                self.table.setItem(i, col, item)

        self.right_panel.setTitle(f"📋 已识别记录 ({len(self.records)})")

    def delete_selected(self):
        """删除选中行"""
        rows = set(item.row() for item in self.table.selectedItems())
        for row in sorted(rows, reverse=True):
            del self.records[row]
        self.update_table()

    def clear_all(self):
        """清空全部"""
        if self.records:
            reply = QMessageBox.question(self, "确认", f"确定清空全部 {len(self.records)} 条记录？")
            if reply == QMessageBox.StandardButton.Yes:
                self.records.clear()
                self.update_table()

    def export_excel(self):
        """导出 Excel，有警告的行标红"""
        if not self.records:
            QMessageBox.warning(self, "提示", "没有可导出的记录")
            return

        default_name = f"信封提取_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "保存 Excel", default_name, "Excel Files (*.xlsx)")

        if path:
            from openpyxl.styles import PatternFill, Font as XlFont

            # 构建导出数据，增加"警告"列
            export_rows = []
            for r in self.records:
                row = {k: r.get(k, "") for k in ["编号", "邮编", "地址", "联系人/单位名", "电话"]}
                warnings = r.get("_warnings", [])
                row["警告"] = "\n".join(warnings) if warnings else ""
                export_rows.append(row)

            df = pd.DataFrame(export_rows)
            cols = ["编号", "邮编", "地址", "联系人/单位名", "电话", "警告"]
            df = df.reindex(columns=cols)
            df.to_excel(path, index=False)

            # 用 openpyxl 对有警告的行标红
            from openpyxl import load_workbook
            wb = load_workbook(path)
            ws = wb.active
            red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
            red_font = XlFont(color="9C0006")
            for row_idx in range(2, ws.max_row + 1):  # 跳过表头
                warn_cell = ws.cell(row=row_idx, column=6)  # 警告列
                has_warn = bool(warn_cell.value)
                for col_idx in range(1, 6):  # 编号~电话（1~5列）
                    cell = ws.cell(row=row_idx, column=col_idx)
                    # 有警告的整行标红，或单个空字段标红
                    if has_warn or not (cell.value and str(cell.value).strip()):
                        cell.fill = red_fill
                        cell.font = red_font
                # 警告列本身也标红
                if has_warn:
                    warn_cell.fill = red_fill
                    warn_cell.font = red_font
            wb.save(path)

            def _has_issue(r):
                if r.get("_warnings"):
                    return True
                return any(not r.get(k, "").strip() for k in ["编号", "邮编", "地址", "联系人/单位名", "电话"])

            warn_count = sum(1 for r in self.records if _has_issue(r))
            msg = f"已导出 {len(self.records)} 条记录到：\n{path}"
            if warn_count:
                msg += f"\n\n❗ 其中 {warn_count} 条需人工复核（已标红）"
            self.statusBar().showMessage(f"已导出: {path}")
            QMessageBox.information(self, "成功", msg)

    def closeEvent(self, event):
        """关闭窗口"""
        if self._ocr_busy:
            reply = QMessageBox.question(
                self,
                "正在识别",
                "当前正在识别，直接关闭可能导致任务中断。\n\n是否强制退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self.shutdown(force=True)
            event.accept()
            return

        self.shutdown(force=False)
        event.accept()


def main():
    mp.freeze_support()
    log_file = setup_logging()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    app.aboutToQuit.connect(lambda: window.shutdown(force=False))
    logger.info("应用启动完成，PID=%s，日志=%s", os.getpid(), str(log_file))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
