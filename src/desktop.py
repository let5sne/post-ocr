#!/usr/bin/env python3
"""
信封信息提取系统 - 桌面版
使用 Droidcam 将手机作为摄像头，实时预览并识别信封信息
"""
import os
import sys
import cv2
import tempfile
import pandas as pd
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QComboBox,
    QFileDialog, QMessageBox, QGroupBox, QSplitter, QHeaderView,
    QStatusBar, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QFont, QAction

from paddleocr import PaddleOCR
from processor import extract_info

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"


class OCRWorker(QThread):
    """OCR 识别线程"""
    finished = pyqtSignal(dict, list)
    error = pyqtSignal(str)

    def __init__(self, ocr, image_path):
        super().__init__()
        self.ocr = ocr
        self.image_path = image_path

    def run(self):
        try:
            result = self.ocr.ocr(self.image_path, cls=False)
            ocr_texts = []
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2:
                        ocr_texts.append(line[1][0])
            record = extract_info(ocr_texts)
            self.finished.emit(record, ocr_texts)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("📮 信封信息提取系统")
        self.setMinimumSize(1200, 700)

        # 初始化 OCR
        self.statusBar().showMessage("正在加载 OCR 模型...")
        QApplication.processEvents()
        self.ocr = PaddleOCR(use_textline_orientation=True, lang="ch", show_log=False)
        self.statusBar().showMessage("OCR 模型加载完成")

        # 摄像头
        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)

        # 数据
        self.records = []

        self.init_ui()
        self.load_cameras()

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
        self.btn_capture.setEnabled(False)
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
        self.shortcut_capture = QAction(self)
        self.shortcut_capture.setShortcut("Space")
        self.shortcut_capture.triggered.connect(self.capture_and_recognize)
        self.addAction(self.shortcut_capture)

    def load_cameras(self):
        """扫描可用摄像头"""
        self.cam_combo.clear()
        for i in range(10):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    self.cam_combo.addItem(f"摄像头 {i}", i)
                cap.release()

        if self.cam_combo.count() == 0:
            self.cam_combo.addItem("未检测到摄像头", -1)
            self.statusBar().showMessage("未检测到摄像头，请连接 Droidcam")
        else:
            self.statusBar().showMessage(f"检测到 {self.cam_combo.count()} 个摄像头")

    def toggle_camera(self):
        """连接/断开摄像头"""
        if self.cap is None:
            cam_id = self.cam_combo.currentData()
            if cam_id is None or cam_id < 0:
                QMessageBox.warning(self, "错误", "请先选择有效的摄像头")
                return

            self.cap = cv2.VideoCapture(cam_id)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            if self.cap.isOpened():
                self.timer.start(30)  # ~33 FPS
                self.btn_connect.setText("⏹ 断开")
                self.btn_capture.setEnabled(True)
                self.cam_combo.setEnabled(False)
                self.statusBar().showMessage("摄像头已连接")
            else:
                self.cap = None
                QMessageBox.warning(self, "错误", "无法打开摄像头")
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
        if ret:
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

    def capture_and_recognize(self):
        """拍照并识别"""
        if self.cap is None:
            return

        ret, frame = self.cap.read()
        if not ret:
            self.statusBar().showMessage("拍照失败")
            return

        # 保存临时文件
        tmp_path = tempfile.mktemp(suffix=".jpg")
        cv2.imwrite(tmp_path, frame)

        self.statusBar().showMessage("正在识别...")
        self.btn_capture.setEnabled(False)

        # 启动 OCR 线程
        self.worker = OCRWorker(self.ocr, tmp_path)
        self.worker.finished.connect(lambda r, t: self.on_ocr_finished(r, t, tmp_path))
        self.worker.error.connect(lambda e: self.on_ocr_error(e, tmp_path))
        self.worker.start()

    def on_ocr_finished(self, record, texts, tmp_path):
        """OCR 完成"""
        os.unlink(tmp_path)
        self.btn_capture.setEnabled(True)

        # 添加到记录
        self.records.append(record)
        self.update_table()

        self.statusBar().showMessage(f"识别完成: {record.get('联系人/单位名', '未知')}")

    def on_ocr_error(self, error, tmp_path):
        """OCR 错误"""
        os.unlink(tmp_path)
        self.btn_capture.setEnabled(True)
        self.statusBar().showMessage(f"识别失败: {error}")

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
        if self.cap:
            self.timer.stop()
            self.cap.release()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
