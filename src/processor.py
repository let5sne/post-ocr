import re
import pandas as pd
from typing import List, Dict, Any
from pydantic import BaseModel, Field


class EnvelopeRecord(BaseModel):
    编号: str = ""
    邮编: str = ""
    地址: str = ""
    联系人_单位名: str = Field(default="", alias="联系人/单位名")
    电话: str = ""


def clean_text(text: str) -> str:
    """清理OCR识别出的杂质字符"""
    return text.strip().replace(" ", "")


def extract_info(ocr_results: List[str]) -> Dict[str, str]:
    """
    从OCR结果列表中提取结构化信息。
    """
    data = {"编号": "", "邮编": "", "地址": "", "联系人/单位名": "", "电话": ""}

    full_content = " ".join(ocr_results)

    # 1. 提取邮编 (6位数字)
    zip_match = re.search(r"\b(\d{6})\b", full_content)
    if zip_match:
        data["邮编"] = zip_match.group(1)

    # 2. 提取电话 (11位手机号或带区号固话)
    phone_match = re.search(r"(1[3-9]\d{9}|0\d{2,3}-\d{7,8})", full_content)
    if phone_match:
        data["电话"] = phone_match.group(0)

    # 3. 提取联系人 (通常在电话前面，或者是独立的短行)
    # 遍历每一行寻找包含电话的行
    for line in ocr_results:
        if data["电话"] and data["电话"] in line:
            # 移除电话部分，剩下的可能是姓名
            name_part = line.replace(data["电话"], "").strip()
            # 进一步清洗姓名（移除符号）
            name_part = re.sub(r"[^\w\u4e00-\u9fa5]", "", name_part)
            if name_part:
                data["联系人/单位名"] = name_part
            break

    # 如果还没找到联系人，尝试找不含数字的短行
    if not data["联系人/单位名"]:
        for line in ocr_results:
            clean_line = re.sub(r"[^\w\u4e00-\u9fa5]", "", line)
            if 2 <= len(clean_line) <= 10 and not re.search(r"\d", clean_line):
                data["联系人/单位名"] = clean_line
                break

    # 4. 提取地址
    address_match = re.search(
        r"([^,，。\s]*(?:省|市|区|县|乡|镇|路|街|村|组|号)[^,，。\s]*)", full_content
    )
    if address_match:
        data["地址"] = address_match.group(1)
    else:
        # 兜底：寻找较长的包含地名特征的行
        for line in ocr_results:
            if any(k in line for k in ["省", "市", "区", "县", "乡", "镇", "村"]):
                data["地址"] = line.strip()
                break

    # 5. 提取编号 (长数字串)
    # 排除邮编和电话后的最长数字串
    long_numbers = re.findall(r"\b\d{10,20}\b", full_content)
    for num in long_numbers:
        if num != data["电话"]:
            data["编号"] = num
            break

    return data


def save_to_excel(records: List[Dict[str, Any]], output_path: str):
    df = pd.DataFrame(records)
    # 调整列顺序
    cols = ["编号", "邮编", "地址", "联系人/单位名", "电话"]
    df = df.reindex(columns=cols)
    df.to_excel(output_path, index=False)
