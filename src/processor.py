import re
from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from pydantic import BaseModel, Field


ZIP_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")
PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9}|0\d{2,3}-?\d{7,8})(?!\d)")
LONG_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{10,20})(?!\d)")
ADDRESS_HINT_PATTERN = re.compile(r"(省|市|区|县|乡|镇|街|路|村|号|栋|单元|室)")


@dataclass
class OCRLine:
    text: str
    source: str
    order: int
    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    row_idx: int = -1
    col_idx: int = -1

    @property
    def has_pos(self) -> bool:
        return (
            self.x1 is not None
            and self.y1 is not None
            and self.x2 is not None
            and self.y2 is not None
        )

    @property
    def cx(self) -> float:
        if not self.has_pos:
            return float(self.order)
        return (self.x1 + self.x2) / 2.0  # type: ignore[operator]

    @property
    def cy(self) -> float:
        if not self.has_pos:
            return float(self.order)
        return (self.y1 + self.y2) / 2.0  # type: ignore[operator]

    @property
    def height(self) -> float:
        if not self.has_pos:
            return 0.0
        return max(0.0, float(self.y2) - float(self.y1))

    @property
    def width(self) -> float:
        if not self.has_pos:
            return 0.0
        return max(0.0, float(self.x2) - float(self.x1))


class EnvelopeRecord(BaseModel):
    编号: str = ""
    邮编: str = ""
    地址: str = ""
    联系人_单位名: str = Field(default="", alias="联系人/单位名")
    电话: str = ""


def clean_text(text: str) -> str:
    """清理 OCR 识别文本中的空白和无意义分隔符。"""
    if not text:
        return ""
    text = text.replace("\u3000", " ").strip()
    return re.sub(r"\s+", "", text)


def _parse_box(raw_box: Any) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if not isinstance(raw_box, (list, tuple)) or len(raw_box) < 4:
        return None, None, None, None

    xs: List[float] = []
    ys: List[float] = []
    for p in raw_box:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        try:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
        except Exception:
            continue
    if not xs or not ys:
        return None, None, None, None
    return min(xs), min(ys), max(xs), max(ys)


def _to_ocr_line(item: Any, idx: int) -> Optional[OCRLine]:
    if isinstance(item, str):
        text = clean_text(item)
        if not text:
            return None
        return OCRLine(text=text, source="main", order=idx)

    if not isinstance(item, dict):
        return None

    text = clean_text(str(item.get("text", "")))
    if not text:
        return None

    source = str(item.get("source", "main"))
    x1, y1, x2, y2 = _parse_box(item.get("box"))
    if x1 is None:
        # 兼容直接传坐标的输入
        try:
            x1 = float(item.get("x1"))
            y1 = float(item.get("y1"))
            x2 = float(item.get("x2"))
            y2 = float(item.get("y2"))
        except Exception:
            x1, y1, x2, y2 = None, None, None, None

    return OCRLine(text=text, source=source, order=idx, x1=x1, y1=y1, x2=x2, y2=y2)


def _normalize_ocr_results(ocr_results: Sequence[Any]) -> List[OCRLine]:
    lines: List[OCRLine] = []
    seen = set()
    for idx, item in enumerate(ocr_results):
        line = _to_ocr_line(item, idx)
        if line is None:
            continue
        if line.has_pos:
            key = (
                line.text,
                line.source,
                round(line.cx, 1),
                round(line.cy, 1),
            )
        else:
            key = (line.text, line.source, line.order)
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return lines


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    if not m:
        return ""
    if m.lastindex:
        return m.group(1)
    return m.group(0)


def _find_anchor(lines: Iterable[OCRLine], pattern: re.Pattern[str], prefer_bottom: bool) -> Optional[Tuple[OCRLine, str]]:
    candidates: List[Tuple[OCRLine, str]] = []
    for line in lines:
        m = pattern.search(line.text)
        if not m:
            continue
        token = m.group(1) if m.lastindex else m.group(0)
        candidates.append((line, token))

    if not candidates:
        return None

    if prefer_bottom:
        return max(candidates, key=lambda item: (item[0].row_idx, item[0].cy, item[0].cx, item[0].order))
    return min(candidates, key=lambda item: (item[0].row_idx, item[0].cy, item[0].cx, item[0].order))


def _build_rows(lines: List[OCRLine]) -> List[List[OCRLine]]:
    positioned = [line for line in lines if line.has_pos]
    if not positioned:
        return []
    positioned.sort(key=lambda line: (line.cy, line.cx))

    heights = [line.height for line in positioned if line.height > 1.0]
    h_med = median(heights) if heights else 20.0
    y_threshold = max(8.0, h_med * 0.65)

    rows: List[List[OCRLine]] = []
    for line in positioned:
        if not rows:
            rows.append([line])
            continue
        row = rows[-1]
        mean_y = sum(item.cy for item in row) / len(row)
        if abs(line.cy - mean_y) <= y_threshold:
            row.append(line)
        else:
            rows.append([line])

    for row_idx, row in enumerate(rows):
        row.sort(key=lambda line: (line.cx, line.x1 or 0.0))
        for col_idx, line in enumerate(row):
            line.row_idx = row_idx
            line.col_idx = col_idx
    return rows


def _sanitize_address(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"^(地址|收件地址|详细地址)[:：]?", "", text)
    return text


def _sanitize_contact(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"^(收件人|联系人|单位|收)[:：]?", "", text)
    return text.strip("，,。；;:")


def _join_entries(entries: List[Tuple[int, int, str]]) -> str:
    if not entries:
        return ""
    entries.sort(key=lambda item: (item[0], item[1]))
    merged: List[str] = []
    for _, _, text in entries:
        if not text:
            continue
        if merged and merged[-1] == text:
            continue
        merged.append(text)
    return "".join(merged)


def _extract_tracking_number(lines: List[OCRLine], zip_code: str, phone: str) -> str:
    phone_digits = re.sub(r"\D", "", phone)
    candidates: List[Tuple[int, int, str]] = []
    for line in lines:
        for match in LONG_NUMBER_PATTERN.finditer(line.text):
            number = match.group(1)
            if number == zip_code:
                continue
            if phone and (number == phone or number == phone_digits):
                continue
            src_score = 2 if line.source == "number" else 1
            candidates.append((src_score, len(number), number))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][2]


def _extract_with_layout(lines: List[OCRLine], data: Dict[str, str]) -> Tuple[str, str, bool]:
    main_lines = [line for line in lines if line.source != "number"]
    if len(main_lines) < 2:
        return "", "", False

    rows = _build_rows(main_lines)
    if not rows:
        return "", "", False

    zip_anchor = _find_anchor(main_lines, ZIP_PATTERN, prefer_bottom=False)
    phone_anchor = _find_anchor(main_lines, PHONE_PATTERN, prefer_bottom=True)
    if zip_anchor and not data["邮编"]:
        data["邮编"] = zip_anchor[1]
    if phone_anchor and not data["电话"]:
        data["电话"] = phone_anchor[1]

    if zip_anchor:
        start_row = zip_anchor[0].row_idx
    else:
        start_row = min(line.row_idx for line in main_lines)
    if phone_anchor:
        end_row = phone_anchor[0].row_idx
    else:
        end_row = max(line.row_idx for line in main_lines)
    if start_row > end_row:
        start_row, end_row = end_row, start_row

    single_column_mode = False
    if zip_anchor and phone_anchor:
        line_widths = [line.width for line in main_lines if line.width > 0]
        width_ref = median(line_widths) if line_widths else 120.0
        single_column_mode = abs(phone_anchor[0].cx - zip_anchor[0].cx) < max(60.0, width_ref * 0.6)

    if zip_anchor and phone_anchor and phone_anchor[0].cx > zip_anchor[0].cx and not single_column_mode:
        split_x = (zip_anchor[0].cx + phone_anchor[0].cx) / 2.0
    elif phone_anchor:
        split_x = phone_anchor[0].cx - max(40.0, phone_anchor[0].width * 0.6)
    elif zip_anchor:
        split_x = zip_anchor[0].cx + max(80.0, zip_anchor[0].width * 1.5)
    else:
        split_x = median([line.cx for line in main_lines])

    address_entries: List[Tuple[int, int, str]] = []
    contact_entries: List[Tuple[int, int, str]] = []

    for line in main_lines:
        if line.row_idx < start_row or line.row_idx > end_row:
            continue

        text = line.text
        if zip_anchor and line is zip_anchor[0]:
            text = text.replace(zip_anchor[1], "")
        if phone_anchor and line is phone_anchor[0]:
            text = text.replace(phone_anchor[1], "")
        text = clean_text(text)
        if not text:
            continue
        if re.fullmatch(r"\d{6,20}", text):
            continue

        if single_column_mode:
            if phone_anchor and line is phone_anchor[0]:
                contact_entries.append((line.row_idx, line.col_idx, text))
            else:
                address_entries.append((line.row_idx, line.col_idx, text))
            continue

        if line.cx <= split_x:
            address_entries.append((line.row_idx, line.col_idx, text))
        else:
            contact_entries.append((line.row_idx, line.col_idx, text))

    # 联系人优先取靠近电话的一段，降低把地址误分到联系人的概率
    if phone_anchor and contact_entries:
        phone_row = phone_anchor[0].row_idx
        min_dist = min(abs(item[0] - phone_row) for item in contact_entries)
        contact_entries = [
            item for item in contact_entries if abs(item[0] - phone_row) <= min_dist + 1
        ]

    contact_text = _sanitize_contact(_join_entries(contact_entries))
    address_text = _sanitize_address(_join_entries(address_entries))

    # 如果联系人仍为空，尝试从“电话所在行去掉电话号码”的残余文本提取
    if not contact_text and phone_anchor:
        fallback_contact = clean_text(phone_anchor[0].text.replace(phone_anchor[1], ""))
        if fallback_contact and not re.fullmatch(r"\d{2,20}", fallback_contact):
            contact_text = _sanitize_contact(fallback_contact)

    # 若仍缺联系人，尝试从靠近电话的地址候选中回退一行
    if not contact_text and phone_anchor and address_entries:
        phone_row = phone_anchor[0].row_idx
        sorted_candidates = sorted(
            address_entries,
            key=lambda item: (abs(item[0] - phone_row), -item[0], item[1]),
        )
        for row_idx, col_idx, txt in sorted_candidates:
            if ADDRESS_HINT_PATTERN.search(txt):
                continue
            contact_text = _sanitize_contact(txt)
            if contact_text:
                address_entries = [
                    item
                    for item in address_entries
                    if not (item[0] == row_idx and item[1] == col_idx and item[2] == txt)
                ]
                address_text = _sanitize_address(_join_entries(address_entries))
                break

    has_signal = bool(zip_anchor or phone_anchor)
    return address_text, contact_text, has_signal


def _extract_with_text_order(lines: List[OCRLine], data: Dict[str, str]) -> Tuple[str, str, bool]:
    if not lines:
        return "", "", False

    zip_idx = -1
    zip_token = ""
    for idx, line in enumerate(lines):
        m = ZIP_PATTERN.search(line.text)
        if m:
            zip_idx = idx
            zip_token = m.group(1)
            break

    phone_idx = -1
    phone_token = ""
    for idx in range(len(lines) - 1, -1, -1):
        m = PHONE_PATTERN.search(lines[idx].text)
        if m:
            phone_idx = idx
            phone_token = m.group(1)
            break

    if zip_idx < 0 or phone_idx < 0 or zip_idx > phone_idx:
        return "", "", False

    if not data["邮编"]:
        data["邮编"] = zip_token
    if not data["电话"]:
        data["电话"] = phone_token

    address_parts: List[Tuple[int, str]] = []
    contact_text = ""
    for idx in range(zip_idx, phone_idx + 1):
        text = lines[idx].text
        if idx == zip_idx:
            text = text.replace(zip_token, "")
        if idx == phone_idx:
            text = text.replace(phone_token, "")
        text = clean_text(text)
        if not text:
            continue
        if idx == phone_idx:
            contact_text = _sanitize_contact(text)
        else:
            address_parts.append((idx, text))

    if not contact_text and address_parts:
        for idx, text in reversed(address_parts):
            if ADDRESS_HINT_PATTERN.search(text):
                continue
            contact_text = _sanitize_contact(text)
            if contact_text:
                address_parts = [item for item in address_parts if item[0] != idx]
                break

    address_text = _sanitize_address("".join(text for _, text in address_parts))
    return address_text, contact_text, True


def extract_info(ocr_results: List[Any]) -> Dict[str, str]:
    """
    从 OCR 结果中提取结构化信息。

    支持两类输入：
    1. 纯文本列表：`List[str]`
    2. 带坐标的行对象列表：`List[{"text": "...", "box": [[x,y],...], "source": "..."}]`
    """
    data = {"编号": "", "邮编": "", "地址": "", "联系人/单位名": "", "电话": ""}
    lines = _normalize_ocr_results(ocr_results)
    if not lines:
        return data

    full_content = " ".join(line.text for line in lines)
    data["邮编"] = _first_match(ZIP_PATTERN, full_content)
    data["电话"] = _first_match(PHONE_PATTERN, full_content)
    data["编号"] = _extract_tracking_number(lines, data["邮编"], data["电话"])

    # 第一优先级：使用版面坐标进行“邮编-电话锚点 + 连续块”解析
    address_text, contact_text, used_layout = _extract_with_layout(lines, data)
    if not used_layout:
        # 第二优先级：无坐标时按文本顺序回退
        address_text, contact_text, _ = _extract_with_text_order(lines, data)

    data["地址"] = _sanitize_address(address_text)
    data["联系人/单位名"] = _sanitize_contact(contact_text)

    # 最终兜底：联系人和地址任一为空时，补旧规则避免完全丢字段
    if not data["联系人/单位名"]:
        for line in lines:
            text = clean_text(line.text)
            if not text:
                continue
            if data["电话"] and data["电话"] in text:
                name_part = _sanitize_contact(text.replace(data["电话"], ""))
                if name_part:
                    data["联系人/单位名"] = name_part
                    break
        if not data["联系人/单位名"]:
            for line in lines:
                text = clean_text(line.text)
                if 2 <= len(text) <= 20 and not re.search(r"\d", text):
                    data["联系人/单位名"] = _sanitize_contact(text)
                    break

    if not data["地址"]:
        hint_lines = [line.text for line in lines if ADDRESS_HINT_PATTERN.search(line.text)]
        if hint_lines:
            hint_lines.sort(key=lambda txt: len(clean_text(txt)), reverse=True)
            data["地址"] = _sanitize_address(hint_lines[0])

    return data


def save_to_excel(records: List[Dict[str, Any]], output_path: str):
    df = pd.DataFrame(records)
    cols = ["编号", "邮编", "地址", "联系人/单位名", "电话"]
    df = df.reindex(columns=cols)
    df.to_excel(output_path, index=False)
