# Post-OCR Data Extraction Project

## 项目愿景
实现工厂环境下信封背面信息的自动化提取与结构化录入。

## 技术栈
- **OCR**: PaddleOCR (本地部署)
- **数据处理**: Python, Pandas
- **解析逻辑**: 正则表达式 + 语义校验

## 目录结构
- `data/input/`: 原始图片存放处
- `data/output/`: 结果 Excel 及处理日志
- `src/`: 源代码

## 开发规范
1. 错误处理：所有 OCR 失败或解析不完全的记录必须记录在 `data/output/error_log.csv` 中。
2. 验证：在保存前进行邮编（6位）和电话（正则）的合法性校验。
