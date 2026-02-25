# 信封信息提取系统

工厂环境下信封背面信息的自动化提取与结构化录入工具。

## 功能特性

- 自动识别信封图片中的文字信息
- 结构化提取：编号、邮编、地址、联系人、电话
- 支持批量处理，结果导出为 Excel
- 提供桌面应用，支持摄像头实时拍照识别
- 内置 RapidOCR/PaddleOCR 双引擎切换，支持脱机运行
- **支持 GitHub Actions 自动化跨平台出包**

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
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 运行方式

**命令行批处理**
```bash
# 将图片放入 data/input/ 目录
.venv/bin/python src/main.py

# 结果保存在 data/output/result.xlsx
```

**桌面应用**
```bash
.venv/bin/python src/desktop.py

# 启动 PyQt6 窗口，可选择摄像头实时拍照识别
```

### 3. OCR 后端切换（RapidOCR / PaddleOCR）

默认后端为 **RapidOCR(ONNX)**，可通过环境变量切换：

```bash
# 默认：RapidOCR（推荐，跨平台更稳）
POST_OCR_BACKEND=rapidocr .venv/bin/python src/desktop.py

# 强制使用 PaddleOCR
POST_OCR_BACKEND=paddle .venv/bin/python src/desktop.py

# 自动：优先 RapidOCR，失败回退 PaddleOCR
POST_OCR_BACKEND=auto .venv/bin/python src/desktop.py
```

常用相关环境变量（RapidOCR）：
- `POST_OCR_RAPID_DET_BOX_THRESH`：检测框置信度阈值（默认 0.3），调低可提升小字检出率。
- `POST_OCR_RAPID_TEXT_SCORE`：识别结果置信度阈值（默认 0.3），调低可保留可疑单字。
- `POST_OCR_MAIN_SPLIT`：主 ROI 分片数（默认 1）
- `POST_OCR_MAX_ROI_WIDTH`：识别前缩放宽度上限（默认 1920）

常用通用环境变量：
- `POST_OCR_BACKEND_FALLBACK_PADDLE=1|0`：是否允许回退到 Paddle
- `POST_OCR_MP_START_METHOD=spawn|fork`：强制指定 OCR 子进程启动方式
- `POST_OCR_JOB_TIMEOUT_SEC`：单次识别超时秒数（默认 25）
---

## 桌面版打包与分发 (独立运行)

本项目提供基于 **RapidOCR** 的轻量级桌面端（脱离 Python 环境运行），极难受系统环境干扰，且安装包体积更小（~200MB）。

### 推荐方案：GitHub Actions 自动打包

我们配置了自动化的 CI/CD 流程：
1. 确保代码已推送到 GitHub
2. 运行 `git tag v1.0.0` 及 `git push origin v1.0.0`（触发构建）
3. 2~3分钟后，即可前往 [GitHub Releases](https://github.com/let5sne/post-ocr/releases) 下载最新构建好的 `.zip`
4. 下载后解压即可在对应平台的现场电脑直接运行

目前支持生成的系统平台：
- `信封信息提取系统-windows.zip`
- `信封信息提取系统-macos-arm64.zip`

---

### 备选方案：本地手动打包

如果你需要在本地测试打包过程：

```bash
# 1. 安装打包最小依赖
pip install -r requirements-build.txt

# 2. 运行打包脚本 (以 macOS 为例，Windows 同理运行 build_win.py)
python build_mac.py
```

打包完成后，`dist/信封信息提取系统/` 目录即为可分发版本。

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

- 桌面 UI 框架: PyQt6 + OpenCV 
- OCR 引擎: RapidOCR (默认) / PaddleOCR (兼容备用)
- 数据处理: Pandas + openpyxl

## 常见问题

**Q: 识别准确率不高怎么办？**
- 确保图片清晰、光线充足
- 避免图片倾斜或模糊
- 手写字体识别率较低，建议使用印刷体

**Q: 处理速度慢？**
- 首次运行需下载模型（约 200MB）
- 有 GPU 可安装 paddlepaddle-gpu 加速
- 批量处理时建议使用命令行模式
