import os
import glob
import pandas as pd
from tqdm import tqdm
from paddleocr import PaddleOCR
from processor import extract_info, save_to_excel

# 禁用联网检查，加快启动速度
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"


def main():
    # 初始化 PaddleOCR
    ocr = PaddleOCR(use_textline_orientation=True, lang="ch")

    input_dir = "data/input"
    output_dir = "data/output"
    output_excel = os.path.join(output_dir, "result.xlsx")
    error_log = os.path.join(output_dir, "error_log.csv")

    # 支持常见的图片格式
    extensions = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tiff")
    image_paths = []
    for ext in extensions:
        image_paths.extend(glob.glob(os.path.join(input_dir, ext)))

    if not image_paths:
        print(f"错误: 在 {input_dir} 文件夹中未找到任何图片文件。")
        return

    all_records = []
    errors = []

    print(f"检测到 {len(image_paths)} 个待处理信封。开始提取...")

    for img_path in tqdm(image_paths):
        try:
            # 1. 执行 OCR 识别
            result = ocr.ocr(img_path, cls=False)

            # 2. 提取文字行
            ocr_texts = []
            if result and result[0]:
                for line in result[0]:
                    # line 格式: [box, (text, confidence)]
                    if line and len(line) >= 2:
                        ocr_texts.append(line[1][0])

            # 3. 结构化解析
            if ocr_texts:
                record = extract_info(ocr_texts)
                all_records.append(record)
            else:
                errors.append(
                    {"file": os.path.basename(img_path), "error": "未识别到任何文字"}
                )

        except Exception as e:
            errors.append({"file": os.path.basename(img_path), "error": str(e)})

    # 4. 保存最终结果到 Excel
    if all_records:
        save_to_excel(all_records, output_excel)
        print(f"\n[成功] 已提取 {len(all_records)} 条数据，保存至: {output_excel}")

    # 5. 记录失败项
    if errors:
        pd.DataFrame(errors).to_csv(error_log, index=False)
        print(f"[警告] 有 {len(errors)} 张图片处理失败，详情请查看: {error_log}")


if __name__ == "__main__":
    main()
