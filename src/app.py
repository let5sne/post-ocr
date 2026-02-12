import os
import tempfile
import pandas as pd
import streamlit as st
from paddleocr import PaddleOCR
from processor import extract_info, save_to_excel

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

st.set_page_config(page_title="信封信息提取系统", page_icon="📮", layout="wide")
st.title("📮 信封信息提取系统")


@st.cache_resource
def load_ocr():
    return PaddleOCR(use_textline_orientation=True, lang="ch", show_log=False)


ocr = load_ocr()


def process_image(image_file):
    """处理单张图片"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(image_file.getvalue())
        tmp_path = tmp.name

    try:
        result = ocr.ocr(tmp_path, cls=False)
        ocr_texts = []
        if result and result[0]:
            for line in result[0]:
                if line and len(line) >= 2:
                    ocr_texts.append(line[1][0])
        return extract_info(ocr_texts), ocr_texts
    finally:
        os.unlink(tmp_path)


# 文件上传
uploaded_files = st.file_uploader(
    "上传信封图片（支持批量）",
    type=["jpg", "jpeg", "png", "bmp"],
    accept_multiple_files=True,
)

if uploaded_files:
    all_records = []

    progress = st.progress(0)
    status = st.empty()

    for i, file in enumerate(uploaded_files):
        status.text(f"正在处理: {file.name}")
        record, raw_texts = process_image(file)
        record["文件名"] = file.name
        all_records.append(record)
        progress.progress((i + 1) / len(uploaded_files))

    status.text("处理完成！")

    # 显示结果表格
    df = pd.DataFrame(all_records)
    cols = ["文件名", "编号", "邮编", "地址", "联系人/单位名", "电话"]
    df = df.reindex(columns=cols)

    st.subheader("📋 提取结果")
    st.dataframe(df, use_container_width=True)

    # 下载按钮
    output_path = tempfile.mktemp(suffix=".xlsx")
    df.to_excel(output_path, index=False)
    with open(output_path, "rb") as f:
        st.download_button(
            label="📥 下载 Excel",
            data=f,
            file_name="信封提取结果.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    os.unlink(output_path)

    # 预览图片和识别详情
    with st.expander("🔍 查看识别详情"):
        cols = st.columns(min(3, len(uploaded_files)))
        for i, file in enumerate(uploaded_files):
            with cols[i % 3]:
                st.image(file, caption=file.name, use_container_width=True)
                st.json(all_records[i])
