"""Check that an export kept the template, apart from filled data cells.

Usage: python tools/compare_template.py <template> <output>
"""

import re
import sys
import zipfile
import posixpath
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
DATA_SHEET = "管理类_件"
EMPTY_SHEETS = ("管理类_卷", "管理类_卷内件")
ROW_RE = re.compile(r'<row\b[^>]*\br="(\d+)"[^>]*(?:/>|>.*?</row>)', re.S)


def _sheet_member(book_zip, sheet_name):
    workbook = ET.fromstring(book_zip.read("xl/workbook.xml"))
    node = next(
        (
            item
            for item in workbook.find("s:sheets", NS)
            if item.attrib["name"] == sheet_name
        ),
        None,
    )
    if node is None:
        return None
    rels = ET.fromstring(book_zip.read("xl/_rels/workbook.xml.rels"))
    target = next(
        item.attrib["Target"] for item in rels if item.attrib["Id"] == node.attrib[RID]
    )
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath("xl/" + target)


def _strip_data_rows(xml):
    def keep(match):
        if int(match.group(1)) >= 2:
            return ""
        return match.group(0)

    return ROW_RE.sub(keep, xml)


def _color_key(color):
    if color is None:
        return None
    return (color.type, color.theme, color.tint, getattr(color, "rgb", None))


def _font_key(font):
    return (
        font.name,
        font.size,
        font.bold,
        font.italic,
        font.underline,
        _color_key(font.color),
    )


def _side_key(side):
    if side is None:
        return None
    return (side.style, _color_key(side.color))


def _border_key(border):
    return tuple(
        _side_key(getattr(border, name)) for name in ("left", "right", "top", "bottom")
    )


def _same_header_style(source, result, kind):
    key = _font_key if kind == "font" else _border_key
    attr = "font" if kind == "font" else "border"
    for left, right in zip(source.worksheets, result.worksheets):
        width = max(left.max_column or 1, right.max_column or 1)
        for column in range(1, width + 1):
            if key(getattr(left.cell(1, column), attr)) != key(
                getattr(right.cell(1, column), attr)
            ):
                return False, left.title
    return True, ""


def compare_workbooks(template, output, data_sheet=DATA_SHEET):
    """Return (ok, lines). Each line is a Chinese pass or fail."""
    template = Path(template)
    output = Path(output)
    lines = []

    def check(ok, passed, failed):
        lines.append(("通过 · " if ok else "未通过 · ") + (passed if ok else failed))
        return ok

    if not template.is_file():
        lines.append("未通过 · 找不到模板：" + str(template))
        lines.append("结论：未通过（1 项）")
        return False, lines
    if not output.is_file():
        lines.append("未通过 · 找不到导出文件：" + str(output))
        lines.append("结论：未通过（1 项）")
        return False, lines

    from openpyxl import load_workbook

    source = load_workbook(template)
    result = load_workbook(output)
    ok = True
    ok &= check(
        source.sheetnames == result.sheetnames,
        "工作表名称和顺序一致",
        "工作表名称或顺序不一致：模板 "
        + "、".join(source.sheetnames)
        + "；导出 "
        + "、".join(result.sheetnames),
    )
    ok &= check(
        [ws.sheet_state for ws in source.worksheets]
        == [ws.sheet_state for ws in result.worksheets],
        "工作表隐藏状态一致",
        "工作表隐藏状态不一致",
    )
    header_ok = True
    header_detail = ""
    for left, right in zip(source.worksheets, result.worksheets):
        left_header = [cell.value for cell in left[1]]
        right_header = [cell.value for cell in right[1]]
        if left_header != right_header:
            header_ok = False
            header_detail = left.title
            break
    ok &= check(
        header_ok,
        "列名、顺序和表头文字一致",
        "列名、顺序或表头文字不一致：" + header_detail,
    )
    font_ok, font_detail = _same_header_style(source, result, "font")
    ok &= check(font_ok, "表头字体一致", "表头字体不一致：" + font_detail)
    border_ok, border_detail = _same_header_style(source, result, "border")
    ok &= check(border_ok, "表头边框一致", "表头边框不一致：" + border_detail)
    merge_ok = True
    merge_detail = ""
    for left, right in zip(source.worksheets, result.worksheets):
        left_merges = sorted(str(item) for item in left.merged_cells.ranges)
        right_merges = sorted(str(item) for item in right.merged_cells.ranges)
        if left_merges != right_merges:
            merge_ok = False
            merge_detail = left.title
            break
    ok &= check(merge_ok, "合并单元格一致", "合并单元格不一致：" + merge_detail)
    width_ok = True
    width_detail = ""
    for left, right in zip(source.worksheets, result.worksheets):
        left_widths = {key: item.width for key, item in left.column_dimensions.items()}
        right_widths = {
            key: item.width for key, item in right.column_dimensions.items()
        }
        if left_widths != right_widths:
            width_ok = False
            width_detail = left.title
            break
    ok &= check(width_ok, "列宽一致", "列宽不一致：" + width_detail)
    dv_ok = True
    dv_detail = ""
    for left, right in zip(source.worksheets, result.worksheets):
        if str(left.data_validations) != str(right.data_validations):
            dv_ok = False
            dv_detail = left.title
            break
    ok &= check(dv_ok, "数据有效性一致", "数据有效性不一致：" + dv_detail)
    left_names = {name: item.attr_text for name, item in source.defined_names.items()}
    right_names = {name: item.attr_text for name, item in result.defined_names.items()}
    ok &= check(
        left_names == right_names,
        "定义名称一致",
        "定义名称不一致",
    )
    empty_ok = True
    empty_detail = ""
    for title in EMPTY_SHEETS:
        if title not in result.sheetnames:
            empty_ok = False
            empty_detail = "缺少「" + title + "」"
            break
        sheet = result[title]
        for row in sheet.iter_rows(
            min_row=2, max_row=sheet.max_row or 1, max_col=sheet.max_column or 1
        ):
            if any(cell.value is not None for cell in row):
                empty_ok = False
                empty_detail = "「" + title + "」写进了数据"
                break
        if not empty_ok:
            break
    ok &= check(
        empty_ok, "管理类_卷和管理类_卷内件保持为空", empty_detail or "卷册工作表不为空"
    )

    with zipfile.ZipFile(template) as src, zipfile.ZipFile(output) as out:
        src_names = src.namelist()
        out_names = out.namelist()
        ok &= check(
            src_names == out_names,
            "压缩包内的部件和顺序一致",
            "压缩包部件不一致",
        )
        member = (
            _sheet_member(src, data_sheet) if data_sheet in source.sheetnames else None
        )
        changed = [
            name
            for name in src_names
            if name in out_names and src.read(name) != out.read(name)
        ]
        if member is None:
            ok &= check(False, "", "导出结果里没有「" + data_sheet + "」")
        else:
            unexpected = [name for name in changed if name != member]
            ok &= check(
                not unexpected,
                "除「" + data_sheet + "」外，没有其他部件被修改",
                "不应修改的部件被改动：" + "、".join(unexpected),
            )
            if member in src_names and member in out_names:
                left_xml = _strip_data_rows(src.read(member).decode("utf-8"))
                right_xml = _strip_data_rows(out.read(member).decode("utf-8"))
                ok &= check(
                    left_xml == right_xml,
                    "「" + data_sheet + "」除第2行及以后的数据单元格外，结构一致",
                    "「"
                    + data_sheet
                    + "」除数据单元格外还有结构差异（表头、列宽、有效性或样式）",
                )
    source.close()
    result.close()
    failed = sum(1 for line in lines if line.startswith("未通过"))
    lines.append("结论：通过" if ok and failed == 0 else f"结论：未通过（{failed} 项）")
    return ok and failed == 0, lines


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("用法：python tools/compare_template.py <模板> <导出文件>")
        return 2
    ok, lines = compare_workbooks(argv[0], argv[1])
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
