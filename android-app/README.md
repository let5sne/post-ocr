# USB 摄像头连接方案

## 概述

通过 USB 数据线将 Android 手机作为摄像头连接到电脑，无需 WiFi/网络。

## 架构

```
┌─────────────────┐       USB        ┌─────────────────┐
│   Android APP   │ ◄─────────────► │   电脑 ADB      │
│  (MJPEG服务)    │   adb forward   │   desktop.py    │
│   端口 8080     │                  │  localhost:8080 │
└─────────────────┘                  └─────────────────┘
```

## 使用步骤

### 1. 准备 Android APP

#### 方式A: 使用 Android Studio 编译（推荐）

1. 安装 Android Studio
2. 打开 `android-app` 目录
3. 连接手机或启动模拟器
4. 点击 Run 按钮

#### 方式B: 下载预编译 APK

如需预编译 APK，请联系开发者或自行编译。

### 2. 手机端操作

1. **安装并启动**「USB摄像头」APP
2. **开启 USB 调试**：
   - 设置 → 关于手机 → 连续点击"版本号" 7次
   - 设置 → 开发者选项 → USB调试（开启）
3. 点击 APP 中的「启动」按钮
4. 屏幕显示："服务运行中 端口: 8080"

### 3. 电脑端操作

#### 安装 ADB

```bash
# Windows: 下载 platform-tools
# https://developer.android.com/tools/releases/platform-tools

# 或使用 winget
winget install Google.PlatformTools

# 验证安装
adb version
```

#### 连接手机

```bash
# 1. USB 连接手机，手机上弹出"允许USB调试"时点击"允许"
# 2. 验证连接
adb devices

# 应显示类似：
# List of devices attached
# XXXXXXXX    device
```

#### 运行桌面程序

```bash
cd d:\code\post-ocr
py -3.12 src\desktop.py
```

#### 连接摄像头

1. 在程序中点击 **"🔌 USB连接"** 按钮
2. 程序会自动执行 `adb forward tcp:8080 tcp:8080`
3. 连接成功后显示实时画面

## 工作原理

1. 手机 APP 启动 MJPEG 流服务器（监听 8080 端口）
2. ADB 将手机端口转发到电脑：`adb forward tcp:8080 tcp:8080`
3. 电脑 OpenCV 读取：`cv2.VideoCapture("http://localhost:8080")`
4. 画面实时显示，支持拍照识别

## 故障排查

### 问题：ADB 找不到设备

- 检查 USB 线是否支持数据传输（非仅充电线）
- 手机上是否允许 USB 调试
- 尝试更换 USB 端口

### 问题：连接失败

- 确保 APP 已启动并显示"服务运行中"
- 检查端口 8080 是否被占用
- 尝试重启 APP

### 问题：画面卡顿

- 降低分辨率：在 CameraHelper.kt 中修改预览尺寸
- 检查 USB 线质量

## 技术栈

- **Android**: Kotlin + Camera2 API
- **网络**: MJPEG over HTTP
- **电脑端**: Python + OpenCV + PyQt6
- **通信**: ADB 端口转发
