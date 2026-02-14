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
from PyQt6.QtGui import QImage, QPixmap, QFont, QAction, QKeySequence, QShortcut

from processor import extract_info
from ocr_offline import create_offline_ocr, get_models_base_dir

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
    OCR 后台服务（运行在标准 Python 线程内）。

    关键点：
    - 避免使用 QThread：在 macOS 上，QThread(Dummy-*) 内 import paddleocr 可能卡死
    - PaddleOCR 实例在后台线程内创建并使用，避免跨线程调用导致卡死/死锁
    - 单线程串行处理任务：避免并发推理挤爆内存或引发底层库竞争
    """

    finished = pyqtSignal(int, dict, list)
    error = pyqtSignal(int, str)
    ready = pyqtSignal()
    init_error = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, models_base_dir: Path):
        super().__init__()
        self._models_base_dir = models_base_dir
        self._ocr = None
        self._busy = False
        self._stop_event = threading.Event()
        self._queue: "queue.Queue[tuple[int, object] | None]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="OCRThread", daemon=True)

    def _set_busy(self, busy: bool) -> None:
        if self._busy != busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def start(self) -> None:
        """启动后台线程并执行 warmup。"""

        self._thread.start()

    def stop(self, timeout_ms: int = 8000) -> bool:
        """请求停止后台线程并等待退出（后台线程为 daemon，退出失败也不阻塞进程）。"""

        try:
            self._stop_event.set()
            # 用 sentinel 唤醒阻塞在 queue.get() 的线程
            try:
                self._queue.put_nowait(None)
            except Exception:
                pass
            self._thread.join(timeout=max(0.0, timeout_ms / 1000.0))
            return not self._thread.is_alive()
        except Exception:
            return False

    def _ensure_ocr(self) -> None:
        if self._ocr is None:
            logger.info("OCR ensure_ocr: 开始创建 PaddleOCR（线程=%s）", threading.current_thread().name)
            self._ocr = create_offline_ocr(models_base_dir=self._models_base_dir)
            logger.info("OCR ensure_ocr: PaddleOCR 创建完成")
            self.ready.emit()

    def _warmup(self) -> None:
        """提前加载 OCR 模型，避免首次识别时才初始化导致“像卡死”"""

        logger.info("OCR 预热开始（线程=%s）", threading.current_thread().name)
        self._ensure_ocr()
        logger.info("OCR 预热完成")

    def _run(self) -> None:
        try:
            self._warmup()
        except Exception as e:
            logger.exception("OCR 预热失败：%s", str(e))
            self.init_error.emit(str(e))
            return

        while not self._stop_event.is_set():
            item = None
            try:
                item = self._queue.get()
            except Exception:
                continue

            if item is None:
                # sentinel: stop
                break

            job_id, images = item
            if self._stop_event.is_set():
                break
            self._process_job(job_id, images)

    @pyqtSlot(int, object)
    def process(self, job_id: int, images: object) -> None:
        """接收 UI 请求：把任务放进队列，由后台线程串行处理。"""

        if self._stop_event.is_set():
            self.error.emit(job_id, "OCR 服务正在关闭，请稍后重试。")
            return
        # 忙碌或已有排队任务时，直接拒绝，避免积压导致“看起来一直在识别”
        if self._busy or (not self._queue.empty()):
            self.error.emit(job_id, "OCR 正在进行中，请稍后再试。")
            return
        try:
            # 注意：这里不做耗时工作，只入队，避免阻塞 UI
            self._queue.put_nowait((job_id, images))
        except Exception as e:
            self.error.emit(job_id, f"OCR 入队失败：{str(e)}")

    def _process_job(self, job_id: int, images: object) -> None:
        self._set_busy(True)
        try:
            self._ensure_ocr()
            if not isinstance(images, (list, tuple)) or len(images) == 0:
                raise ValueError("内部错误：未传入有效图片数据")

            shapes = []
            for img in images:
                try:
                    shapes.append(getattr(img, "shape", None))
                except Exception:
                    shapes.append(None)
            logger.info("OCR job=%s 开始，images=%s", job_id, shapes)

            ocr_texts: list[str] = []
            for img in images:
                if img is None:
                    continue
                result = self._ocr.ocr(img, cls=False)
                if result and result[0]:
                    for line in result[0]:
                        if line and len(line) >= 2:
                            ocr_texts.append(line[1][0])

            record = extract_info(ocr_texts)
            logger.info(
                "OCR job=%s 完成，lines=%s, record_keys=%s",
                job_id,
                len(ocr_texts),
                list(record.keys()),
            )
            self.finished.emit(job_id, record, ocr_texts)
        except Exception as e:
            logger.exception("OCR job=%s 失败：%s", job_id, str(e))
            self.error.emit(job_id, str(e))
        finally:
            self._set_busy(False)


class MainWindow(QMainWindow):
    request_ocr = pyqtSignal(int, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("📮 信封信息提取系统")
        self.setMinimumSize(1200, 700)

        # OCR 工作线程（避免 UI 卡死）
        self._ocr_job_id = 0
        self._ocr_start_time_by_job: dict[int, float] = {}
        self._ocr_ready = False
        self._ocr_busy = False
        self._shutting_down = False
        self._ocr_timeout_prompted = False

        # 摄像头
        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self._frame_fail_count = 0

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

        # 主线程预加载：在 macOS 上，必须在主线程 import paddleocr，否则后台线程会卡死
        self.statusBar().showMessage("正在加载 OCR 模块...")
        QApplication.processEvents()
        try:
            logger.info("主线程预加载：import paddleocr")
            import paddleocr  # noqa: F401
            logger.info("主线程预加载：paddleocr 导入完成")
        except Exception as e:
            logger.error("主线程预加载失败：%s", e, exc_info=True)
            QMessageBox.critical(self, "启动失败", f"无法加载 OCR 模块：{e}")
            raise

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
        try:
            self._progress.setVisible(False)
        except Exception:
            pass

        try:
            svc = getattr(self, "_ocr_service", None)
            if svc is not None:
                ok = svc.stop(timeout_ms=8000 if force else 3000)
                if (not ok) and force:
                    # Python 线程无法可靠“强杀”，这里只做提示并继续退出流程。
                    logger.warning("OCR 服务停止超时：后台线程可能仍在运行，建议重启应用。")
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
        self.statusBar().showMessage("正在重启 OCR 服务...")
        self._stop_ocr_service(force=True)
        self._init_ocr_service()

    def _init_ocr_service(self) -> None:
        models_dir = get_models_base_dir()

        # 先校验模型路径是否存在（缺失直接抛错给 UI）
        # create_offline_ocr 内部会做更完整校验，这里不提前创建模型，避免阻塞 UI
        if not models_dir.exists():
            raise FileNotFoundError(f"离线模型目录不存在：{models_dir}")

        self._ocr_service = OCRService(models_base_dir=models_dir)

        # 注意：OCRService 内部使用 Python 线程做 warmup 与推理。
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
            self.statusBar().showMessage("OCR 模型已加载（离线）")
            btn = getattr(self, "btn_capture", None)
            if btn is not None:
                btn.setEnabled(self.cap is not None and not self._ocr_busy)
            logger.info("OCR ready")
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

    def _tick_ocr_watchdog(self) -> None:
        """识别进行中：更新耗时，超时则提示是否重启 OCR 服务。"""

        if not self._ocr_busy:
            return
        start_t = self._ocr_start_time_by_job.get(self._ocr_job_id)
        if start_t is None:
            return
        cost = time.monotonic() - start_t
        self.statusBar().showMessage(f"正在识别...（已用 {cost:.1f}s）")

        # 超时保护：底层推理偶发卡住时，让用户可以自救
        if cost >= 45 and not self._ocr_timeout_prompted:
            self._ocr_timeout_prompted = True
            reply = QMessageBox.question(
                self,
                "识别超时",
                "识别已超过 45 秒仍未完成，可能卡住。\n\n是否重启 OCR 服务？\n（若仍无响应，建议直接退出并重新打开应用）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._restart_ocr_service()

    def _on_ocr_finished_job(self, job_id: int, record: dict, texts: list) -> None:
        start_t = self._ocr_start_time_by_job.pop(job_id, None)

        # 只处理最新一次请求，避免旧结果回写
        if job_id != self._ocr_job_id:
            return

        self.records.append(record)
        self.update_table()
        cost = ""
        if start_t is not None:
            cost = f"（耗时 {time.monotonic() - start_t:.1f}s）"
        self.statusBar().showMessage(f"识别完成: {record.get('联系人/单位名', '未知')}{cost}")
        logger.info("OCR job=%s UI 回写完成 %s", job_id, cost)

    def _on_ocr_error_job(self, job_id: int, error: str) -> None:
        self._ocr_start_time_by_job.pop(job_id, None)
        if job_id != self._ocr_job_id:
            return
        self.statusBar().showMessage("识别失败")
        QMessageBox.warning(self, "识别失败", error)
        logger.error("OCR job=%s error: %s", job_id, error)

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
            # 绘制扫描框
            h, w = frame.shape[:2]
            # 框的位置：上方 70%，编号在下方
            x1, y1 = int(w * 0.06), int(h * 0.08)
            x2, y2 = int(w * 0.94), int(h * 0.78)

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

            # 提示文字
            cv2.putText(frame, "You Bian", (x1 + 10, y1 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, "Di Zhi", (x1 + 10, y1 + int((y2-y1)*0.4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, "Lian Xi Ren", (x1 + 10, y2 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, "Dian Hua", (x2 - 80, y2 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # 编号提示
            cv2.putText(frame, "^ Bian Hao ^", (int(w*0.4), int(h*0.88)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

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
        if self.cap is None:
            self.statusBar().showMessage("请先连接摄像头")
            return
        if not self._ocr_ready:
            self.statusBar().showMessage("OCR 模型尚未就绪，请稍等")
            return
        if self._ocr_busy:
            self.statusBar().showMessage("正在识别中，请稍后再按空格")
            return

        ret, frame = self.cap.read()
        if not ret:
            self.statusBar().showMessage("拍照失败")
            return

        # 裁剪两块 ROI（主信息框 + 编号区域），显著减小像素量，提升速度与稳定性
        h, w = frame.shape[:2]
        x1, y1 = int(w * 0.06), int(h * 0.08)
        x2 = int(w * 0.94)
        y2_box = int(h * 0.78)

        roi_images = []
        try:
            roi_box = frame[y1:y2_box, x1:x2]
            if roi_box is not None and roi_box.size > 0:
                roi_images.append(roi_box)
        except Exception:
            pass

        try:
            # 编号一般在底部中间，取较小区域即可
            nx1, nx2 = int(w * 0.30), int(w * 0.70)
            ny1, ny2 = int(h * 0.80), int(h * 0.98)
            roi_num = frame[ny1:ny2, nx1:nx2]
            if roi_num is not None and roi_num.size > 0:
                roi_images.append(roi_num)
        except Exception:
            pass

        if not roi_images:
            self.statusBar().showMessage("拍照失败：未截取到有效区域")
            return

        # 超大分辨率下适当缩放（提高稳定性与速度）
        resized_images = []
        for img in roi_images:
            try:
                max_w = 1400
                if img.shape[1] > max_w:
                    scale = max_w / img.shape[1]
                    img = cv2.resize(img, (int(img.shape[1] * scale), int(img.shape[0] * scale)))
            except Exception:
                pass
            resized_images.append(img)

        logger.info("UI 触发识别：frame=%s, rois=%s", getattr(frame, "shape", None), [getattr(i, "shape", None) for i in resized_images])

        self.statusBar().showMessage("正在识别...")
        self.btn_capture.setEnabled(False)

        # 派发到 OCR 工作线程
        self._ocr_job_id += 1
        job_id = self._ocr_job_id
        self._ocr_start_time_by_job[job_id] = time.monotonic()
        self.request_ocr.emit(job_id, resized_images)

    def update_table(self):
        """更新表格"""
        self.table.setRowCount(len(self.records))
        for i, r in enumerate(self.records):
            self.table.setItem(i, 0, QTableWidgetItem(r.get("编号", "")))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("邮编", "")))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("地址", "")))
            self.table.setItem(i, 3, QTableWidgetItem(r.get("联系人/单位名", "")))
            self.table.setItem(i, 4, QTableWidgetItem(r.get("电话", "")))

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
        """导出 Excel"""
        if not self.records:
            QMessageBox.warning(self, "提示", "没有可导出的记录")
            return

        default_name = f"信封提取_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "保存 Excel", default_name, "Excel Files (*.xlsx)")

        if path:
            df = pd.DataFrame(self.records)
            cols = ["编号", "邮编", "地址", "联系人/单位名", "电话"]
            df = df.reindex(columns=cols)
            df.to_excel(path, index=False)
            self.statusBar().showMessage(f"已导出: {path}")
            QMessageBox.information(self, "成功", f"已导出 {len(self.records)} 条记录到:\n{path}")

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
