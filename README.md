# 信封信息提取系统

工厂环境下信封背面信息的自动化提取与结构化录入工具。

## 功能特性

- 自动识别信封图片中的文字信息
- 结构化提取：编号、邮编、地址、联系人、电话
- 支持批量处理，结果导出为 Excel
- 提供 Web 界面，操作简单

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

**Web 界面**
```bash
streamlit run src/app.py --server.port 8501

# 浏览器访问 http://localhost:8501
```

## 部署方案

### 方案一：内网服务器部署（推荐）

适合多人使用，有内网环境的工厂。

```bash
# 启动服务（监听所有网卡）
streamlit run src/app.py --server.address 0.0.0.0 --server.port 8501

# 工人通过浏览器访问: http://服务器IP:8501
```

### 方案二：Docker 容器化部署

适合需要隔离环境或快速部署的场景。

```bash
# 构建镜像
docker build -t envelope-ocr .

# 运行容器
docker run -d -p 8501:8501 --name envelope-ocr envelope-ocr
```

Dockerfile:
```dockerfile
FROM python:3.10-slim
RUN apt-get update && apt-get install -y libgl1-mesa-glx libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8501
CMD ["streamlit", "run", "src/app.py", "--server.address", "0.0.0.0"]
```

### 方案三：系统服务（开机自启）

适合长期稳定运行的生产环境。

创建服务文件 `/etc/systemd/system/envelope-ocr.service`:
```ini
[Unit]
Description=Envelope OCR Service
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/post-ocr
ExecStart=/usr/bin/streamlit run src/app.py --server.address 0.0.0.0 --server.port 8501
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用服务:
```bash
sudo systemctl daemon-reload
sudo systemctl enable envelope-ocr
sudo systemctl start envelope-ocr
```

## 目录结构

```
post-ocr/
├── data/
│   ├── input/          # 原始图片存放处
│   └── output/         # 结果 Excel 及处理日志
├── src/
│   ├── main.py         # 命令行入口
│   ├── app.py          # Web 界面
│   └── processor.py    # 核心处理逻辑
├── requirements.txt
└── README.md
```

## 技术栈

- OCR 引擎: PaddleOCR 2.10 (PP-OCRv4)
- Web 框架: Streamlit
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
