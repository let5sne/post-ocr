import os
import tempfile
import base64
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from paddleocr import PaddleOCR
from processor import extract_info, save_to_excel

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

st.set_page_config(
    page_title="信封信息提取系统",
    page_icon="📮",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .stApp { max-width: 100%; }
    .stButton>button { width: 100%; height: 3em; font-size: 1.2em; }
    .stDownloadButton>button { width: 100%; height: 3em; }
</style>
""", unsafe_allow_html=True)

st.title("📮 信封信息提取")


@st.cache_resource
def load_ocr():
    return PaddleOCR(use_textline_orientation=True, lang="ch", show_log=False)


ocr = load_ocr()


def process_image(image_data):
    """处理图片数据"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(image_data)
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


# 自定义摄像头组件，带叠加扫描框
CAMERA_COMPONENT = """
<div id="camera-container" style="position:relative; width:100%; max-width:500px; margin:0 auto;">
    <video id="video" autoplay playsinline style="width:100%; border-radius:10px; background:#000;"></video>

    <!-- 扫描框叠加层 -->
    <div id="overlay" style="
        position: absolute;
        top: 8%;
        left: 50%;
        transform: translateX(-50%);
        width: 88%;
        height: 70%;
        border: 3px solid #00ff00;
        box-sizing: border-box;
        pointer-events: none;
    ">
        <!-- 四角 -->
        <div style="position:absolute; top:-3px; left:-3px; width:20px; height:20px; border-top:4px solid #00ff00; border-left:4px solid #00ff00;"></div>
        <div style="position:absolute; top:-3px; right:-3px; width:20px; height:20px; border-top:4px solid #00ff00; border-right:4px solid #00ff00;"></div>
        <div style="position:absolute; bottom:-3px; left:-3px; width:20px; height:20px; border-bottom:4px solid #00ff00; border-left:4px solid #00ff00;"></div>
        <div style="position:absolute; bottom:-3px; right:-3px; width:20px; height:20px; border-bottom:4px solid #00ff00; border-right:4px solid #00ff00;"></div>

        <!-- 字段提示：邮编(左上)、地址(中间)、联系人+电话(底部) -->
        <div style="position:absolute; top:8px; left:10px; color:rgba(255,255,255,0.6); font-size:12px;">邮编</div>
        <div style="position:absolute; top:35%; left:10px; right:10px; color:rgba(255,255,255,0.6); font-size:12px; border-bottom:1px dashed rgba(255,255,255,0.3); padding-bottom:30%;">地址</div>
        <div style="position:absolute; bottom:8px; left:10px; color:rgba(255,255,255,0.6); font-size:12px;">联系人</div>
        <div style="position:absolute; bottom:8px; right:10px; color:rgba(255,255,255,0.6); font-size:12px;">电话</div>
    </div>

    <!-- 编号提示在框外底部 -->
    <div style="position:absolute; bottom:18%; left:50%; transform:translateX(-50%); color:rgba(255,255,255,0.6); font-size:11px;">
        ↑ 编号在此处 ↑
    </div>

    <canvas id="canvas" style="display:none;"></canvas>

    <p id="hint" style="text-align:center; color:#666; margin:10px 0; font-size:14px;">
        📌 将信封背面对齐绿色框，编号对准底部
    </p>

    <button id="capture-btn" onclick="capturePhoto()" style="
        width: 100%;
        padding: 15px;
        font-size: 18px;
        background: #ff4b4b;
        color: white;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        margin-top: 10px;
    ">📷 拍照识别</button>
</div>

<script>
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const hint = document.getElementById('hint');

// 启动后置摄像头
async function startCamera() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
        });
        video.srcObject = stream;
    } catch (err) {
        hint.textContent = '❌ 无法访问摄像头: ' + err.message;
        console.error(err);
    }
}

function capturePhoto() {
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);

    const dataUrl = canvas.toDataURL('image/jpeg', 0.9);

    // 发送到 Streamlit
    window.parent.postMessage({
        type: 'streamlit:setComponentValue',
        value: dataUrl
    }, '*');

    hint.textContent = '✅ 已拍照，正在识别...';
    document.getElementById('capture-btn').disabled = true;
}

startCamera();
</script>
"""

# 初始化 session state
if "records" not in st.session_state:
    st.session_state.records = []

# 输入方式选择
tab_camera, tab_upload = st.tabs(["📷 拍照扫描", "📁 上传图片"])

with tab_camera:
    # 使用自定义摄像头组件
    photo_data = components.html(CAMERA_COMPONENT, height=550)

    # 检查是否有拍照数据
    if "captured_image" not in st.session_state:
        st.session_state.captured_image = None

    # 文件上传作为备用（用于接收JS传来的数据）
    uploaded_photo = st.file_uploader(
        "或直接上传照片",
        type=["jpg", "jpeg", "png"],
        key="camera_upload",
        label_visibility="collapsed"
    )

    if uploaded_photo:
        with st.spinner("识别中..."):
            record, raw_texts = process_image(uploaded_photo.getvalue())

        st.success("✅ 识别完成！")

        col1, col2 = st.columns(2)
        with col1:
            st.image(uploaded_photo, caption="拍摄图片", use_container_width=True)
        with col2:
            st.metric("邮编", record.get("邮编", "-"))
            st.metric("电话", record.get("电话", "-"))
            st.metric("联系人", record.get("联系人/单位名", "-"))

        st.text_area("地址", record.get("地址", ""), disabled=True, height=68)
        st.text_input("编号", record.get("编号", ""), disabled=True)

        if st.button("✅ 添加到列表", type="primary", key="add_camera"):
            record["来源"] = "拍照"
            st.session_state.records.append(record)
            st.success(f"已添加！当前共 {len(st.session_state.records)} 条记录")
            st.rerun()

with tab_upload:
    uploaded_files = st.file_uploader(
        "选择图片文件",
        type=["jpg", "jpeg", "png", "bmp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    if uploaded_files:
        if st.button("🚀 开始识别", type="primary"):
            progress = st.progress(0)

            for i, file in enumerate(uploaded_files):
                with st.spinner(f"处理 {file.name}..."):
                    record, _ = process_image(file.getvalue())
                    record["来源"] = file.name
                    st.session_state.records.append(record)
                progress.progress((i + 1) / len(uploaded_files))

            st.success(f"完成！已添加 {len(uploaded_files)} 条记录")
            st.rerun()

# 显示已收集的记录
st.divider()
st.subheader(f"📋 已收集 {len(st.session_state.records)} 条记录")

if st.session_state.records:
    df = pd.DataFrame(st.session_state.records)
    cols = ["来源", "编号", "邮编", "地址", "联系人/单位名", "电话"]
    df = df.reindex(columns=[c for c in cols if c in df.columns])

    st.dataframe(df, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)

    with col1:
        output_path = tempfile.mktemp(suffix=".xlsx")
        df.to_excel(output_path, index=False)
        with open(output_path, "rb") as f:
            st.download_button(
                "📥 下载 Excel",
                data=f,
                file_name="信封提取结果.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        os.unlink(output_path)

    with col2:
        if st.button("🗑️ 清空列表"):
            st.session_state.records = []
            st.rerun()
else:
    st.info("👆 使用上方拍照或上传功能添加记录")
