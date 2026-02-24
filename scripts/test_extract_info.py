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


def case_company_contact_with_phone() -> None:
    """单位名含地址关键字 + 电话同行，地址跨两行。"""
    ocr_lines = [
        {"text": "610000", "box": [[80, 40], [180, 40], [180, 80], [80, 80]], "source": "main"},
        {"text": "四川省成都市蒲江县鹤山街道", "box": [[80, 100], [520, 100], [520, 132], [80, 132]], "source": "main"},
        {"text": "健民路246号2栋1楼3号", "box": [[80, 140], [460, 140], [460, 172], [80, 172]], "source": "main"},
        {"text": "蒲江县宏利物流有限公司 15600000000", "box": [[80, 180], [560, 180], [560, 212], [80, 212]], "source": "main"},
        {"text": "20260200425708", "box": [[280, 60], [760, 60], [760, 94], [280, 94]], "source": "number"},
    ]
    result = extract_info(ocr_lines)
    _print_case("单位名+电话同行（带坐标）", result)

    assert result["邮编"] == "610000"
    assert result["电话"] == "15600000000"
    assert "四川省成都市蒲江县鹤山街道" in result["地址"]
    assert "健民路246号2栋1楼3号" in result["地址"]
    assert "蒲江县宏利物流有限公司" not in result["地址"], f"单位名不应混入地址: {result['地址']}"
    assert "宏利物流" in result["联系人/单位名"], f"联系人应含单位名: {result['联系人/单位名']}"
    assert result["编号"] == "20260200425708"


def case_company_contact_separate_line() -> None:
    """单位名和电话分两行（无坐标回退）。"""
    ocr_texts = [
        "610000",
        "四川省成都市蒲江县鹤山街道",
        "健民路246号2栋1楼3号",
        "蒲江县宏利物流有限公司",
        "15600000000",
    ]
    result = extract_info(ocr_texts)
    _print_case("单位名+电话分行（纯文本）", result)

    assert result["邮编"] == "610000"
    assert result["电话"] == "15600000000"
    assert "四川省成都市蒲江县鹤山街道" in result["地址"]
    assert "健民路246号2栋1楼3号" in result["地址"]
    assert "宏利物流" in result["联系人/单位名"], f"联系人应含单位名: {result['联系人/单位名']}"


def case_split_roi_address() -> None:
    """模拟 ROI 切片后坐标已偏移还原的场景：地址跨两个切片。

    切片1 (y_offset=0): 邮编 + 地址第一行
    切片2 (y_offset=200): 地址第二行 + 联系人+电话
    坐标已在 worker 中加上 y_offset，此处直接传最终坐标。
    """
    ocr_lines = [
        # 切片1 的结果（y_offset=0，坐标不变）
        {"text": "610000", "box": [[80, 30], [180, 30], [180, 60], [80, 60]], "source": "main"},
        {"text": "四川省成都市蒲江县鹤山街道健民路246号2栋1", "box": [[80, 80], [560, 80], [560, 112], [80, 112]], "source": "main"},
        # 切片2 的结果（原始 y 约 10~42，加上 y_offset=200 后变成 210~242）
        {"text": "楼3号", "box": [[80, 210], [160, 210], [160, 242], [80, 242]], "source": "main"},
        {"text": "蒲江县宏利物流有限公司 15600000000", "box": [[80, 260], [560, 260], [560, 292], [80, 292]], "source": "main"},
        # 编号区域
        {"text": "20260200425708", "box": [[280, 400], [760, 400], [760, 434], [280, 434]], "source": "number"},
    ]
    result = extract_info(ocr_lines)
    _print_case("ROI切片坐标还原", result)

    assert result["邮编"] == "610000"
    assert result["电话"] == "15600000000"
    # 关键：地址两行应正确拼接
    assert "健民路246号2栋1" in result["地址"], f"地址应含第一行: {result['地址']}"
    assert "楼3号" in result["地址"], f"地址应含第二行: {result['地址']}"
    assert "宏利物流" in result["联系人/单位名"], f"联系人应含单位名: {result['联系人/单位名']}"


def main() -> None:
    case_layout_multi_column()
    case_layout_single_column()
    case_text_fallback()
    case_company_contact_with_phone()
    case_company_contact_separate_line()
    case_split_roi_address()
    print("\n所有场景断言通过。")


if __name__ == "__main__":
    main()
