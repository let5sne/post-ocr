#!/usr/bin/env python3
"""
解析器快速自测脚本

运行方式：
    python scripts/test_extract_info.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from processor import extract_info  # noqa: E402


def _print_case(name: str, result: dict) -> None:
    print(f"\n=== {name} ===")
    for key in ["编号", "邮编", "地址", "联系人/单位名", "电话"]:
        print(f"{key}: {result.get(key, '')}")


def case_layout_multi_column() -> None:
    """多栏场景：左侧地址、右侧单位+联系人。"""
    ocr_lines = [
        {"text": "518000", "box": [[80, 40], [180, 40], [180, 80], [80, 80]], "source": "main"},
        {"text": "广东省深圳市南山区", "box": [[80, 100], [450, 100], [450, 132], [80, 132]], "source": "main"},
        {"text": "科技园高新南一道18号", "box": [[80, 140], [520, 140], [520, 172], [80, 172]], "source": "main"},
        {"text": "创新大厦3栋1201", "box": [[80, 180], [420, 180], [420, 212], [80, 212]], "source": "main"},
        {"text": "华南建设小组办公室", "box": [[620, 182], [960, 182], [960, 214], [620, 214]], "source": "main"},
        {"text": "张三13800138000", "box": [[620, 222], [960, 222], [960, 254], [620, 254]], "source": "main"},
        {"text": "202602241234567890", "box": [[280, 60], [760, 60], [760, 94], [280, 94]], "source": "number"},
    ]
    result = extract_info(ocr_lines)
    _print_case("多栏版面", result)

    assert result["邮编"] == "518000"
    assert result["电话"] == "13800138000"
    assert "广东省深圳市南山区" in result["地址"]
    assert "科技园高新南一道18号" in result["地址"]
    assert "华南建设小组办公室" in result["联系人/单位名"]
    assert result["编号"] == "202602241234567890"


def case_layout_single_column() -> None:
    """单列场景：邮编后连续地址，电话行包含联系人。"""
    ocr_lines = [
        {"text": "200120", "box": [[90, 42], [188, 42], [188, 76], [90, 76]], "source": "main"},
        {"text": "上海市浦东新区世纪大道100号", "box": [[90, 96], [620, 96], [620, 128], [90, 128]], "source": "main"},
        {"text": "A座1201室", "box": [[90, 136], [300, 136], [300, 168], [90, 168]], "source": "main"},
        {"text": "李四021-12345678", "box": [[90, 178], [420, 178], [420, 210], [90, 210]], "source": "main"},
    ]
    result = extract_info(ocr_lines)
    _print_case("单列版面", result)

    assert result["邮编"] == "200120"
    assert result["电话"] == "021-12345678"
    assert "上海市浦东新区世纪大道100号" in result["地址"]
    assert "A座1201室" in result["地址"]
    assert result["联系人/单位名"] == "李四"


def case_text_fallback() -> None:
    """无坐标回退：纯文本顺序规则。"""
    ocr_texts = [
        "518000",
        "广东省深圳市南山区科技园",
        "高新南一道18号",
        "华南建设小组办公室",
        "王五 13911112222",
    ]
    result = extract_info(ocr_texts)
    _print_case("纯文本回退", result)

    assert result["邮编"] == "518000"
    assert result["电话"] == "13911112222"
    assert "广东省深圳市南山区科技园" in result["地址"]
    assert "高新南一道18号" in result["地址"]
    assert "华南建设小组办公室" in result["联系人/单位名"] or result["联系人/单位名"] == "王五"


def main() -> None:
    case_layout_multi_column()
    case_layout_single_column()
    case_text_fallback()
    print("\n所有场景断言通过。")


if __name__ == "__main__":
    main()
