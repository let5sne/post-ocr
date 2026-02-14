# 信封信息提取系统

工厂环境下信封背面信息的自动化提取与结构化录入工具。

## 功能特性

- 自动识别信封图片中的文字信息
- 结构化提取：编号、邮编、地址、联系人、电话
- 支持批量处理，结果导出为 Excel
- 提供桌面应用，支持摄像头实时拍照识别

## 系统要求

| 项目 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 4 核 | 8 核 |
| 内存 | 4 GB | 8 GB |
| 硬盘 | 2 GB | 5 GB |
| 系统 | Ubuntu 20.04 / Windows 10 | Ubuntu 22.04 |
| Python | 3.8 | 3.10 |

## 快速开始

### 1. 安装依赖

```bash
# Ubuntu 需要安装系统依赖
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0

# 安装 Python 依赖
pip install -r requirements.txt
```

### 2. 运行方式

**命令行批处理**
```bash
# 将图片放入 data/input/ 目录
python src/main.py

# 结果保存在 data/output/result.xlsx
```

**桌面应用**
```bash
python src/desktop.py

# 启动 PyQt6 窗口，可选择摄像头实时拍照识别
```

---

## Windows 桌面离线版（zip 目录包）

本项目桌面版入口为 `src/desktop.py`（PyQt6 + OpenCV），适合现场工位离线使用。

### 1. 准备离线模型（在有网机器执行一次）

```bash
pip install -r requirements.txt
python scripts/prepare_models.py --models-dir models
```

执行完成后会生成 `models/whl/...` 目录结构；该 `models/` 目录需要与最终的 exe 同级分发。

### 2. Windows 打包（建议使用 PyInstaller 的 onedir）

请在 Windows 机器上构建 Windows 包（不要跨平台交叉打包）。

```powershell
pip install -r requirements.txt
pip install pyinstaller

pyinstaller --noconfirm --clean --windowed --onedir `
  --name "post-ocr-desktop" `
  --paths "src" `
  --collect-all "Cython" `
  --collect-all "paddleocr" `
  --collect-all "paddle" `
  --add-data "models;models" `
  "src/desktop.py"
```

打包完成后，将 `dist\post-ocr-desktop\` 整个目录压缩为 zip 交付即可。

注意：
- 本项目默认使用 PaddleOCR 2.10.0（PP-OCRv4 中文）离线模型目录结构
- 若 `models/` 缺失，程序会直接报错提示，避免触发联网下载

## 目录结构

```
post-ocr/
├── data/
│   ├── input/          # 原始图片存放处
│   └── output/         # 结果 Excel 及处理日志
├── src/
│   ├── main.py         # 命令行入口
│   ├── desktop.py      # 桌面应用入口
│   └── processor.py    # 核心处理逻辑
├── requirements.txt
└── README.md
```

## 技术栈

- OCR 引擎: PaddleOCR 2.10 (PP-OCRv4)
- 桌面框架: PyQt6
- 数据处理: Pandas

## 常见问题

**Q: 识别准确率不高怎么办？**
- 确保图片清晰、光线充足
- 避免图片倾斜或模糊
- 手写字体识别率较低，建议使用印刷体

**Q: 处理速度慢？**
- 首次运行需下载模型（约 200MB）
- 有 GPU 可安装 paddlepaddle-gpu 加速
- 批量处理时建议使用命令行模式
