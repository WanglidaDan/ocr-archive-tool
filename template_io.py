"""Windows application XLSX template adapter, preserving the original schema."""

from datetime import datetime
import math
from pathlib import Path
from copy import copy
from extraction import canonical, normalize_date

NUMERIC = {
    "临时序号",
    "序号",
    "页数",
    "正本数量",
    "数量",
    "年度",
    "件数",
    "电子文件大小",
    "电子文件数量",
}
DATES = {"文件日期", "日期", "成文日期", "形成日期", "发文日期", "起日期", "止日期"}


def _numeric_bound(formula):
    """Return a plain numeric limit, or None when the bound is not a number.

    Data validations sometimes store formula1/formula2 as a formula or a cell
    reference (TODAY(), $A$1). Those cannot be compared with float(); skip the
    bound instead of failing the export.
    """
    if not formula:
        return None
    try:
        return float(formula)
    except (TypeError, ValueError):
        return None


def _outside_bounds(value, formula1, formula2):
    low = _numeric_bound(formula1)
    high = _numeric_bound(formula2)
    return (low is not None and value < low) or (high is not None and value > high)


def standard_value(field, value, choices):
    # Preserve the provided dictionary: do not invent a new classification item.
    if (
        field == "密级"
        and value == "内部"
        and value not in choices
        and "内部资料" in choices
    ):
        return "内部资料"
    return value


def inspect_template(path, sheet=None):
    from openpyxl import load_workbook

    book = load_workbook(path)
    names = [s.title for s in book if s.max_column > 1 and s.cell(1, 1).value]
    selected = sheet if sheet in names else names[0] if names else None
    if selected is None:
        raise ValueError("没有找到包含表头的目录工作表")
    ws = book[selected]
    headers = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    if any(not h for h in headers) or len(set(headers)) != len(headers):
        raise ValueError("目录表头不能为空或重复")
    choices = {}
    for dv in ws.data_validations.dataValidation:
        if dv.type != "list":
            continue
        cols = [c.column for c in ws[2] if c.coordinate in dv.sqref]
        if not cols:
            continue
        formula = (dv.formula1 or "").lstrip("=")
        options = []
        if formula.startswith('"') and formula.endswith('"'):
            options = formula[1:-1].split(",")
        elif formula in book.defined_names:
            for title, cell_range in book.defined_names[formula].destinations:
                options.extend(
                    str(c.value)
                    for row in book[title][cell_range]
                    for c in row
                    if c.value is not None
                )
        for col in cols:
            if options:
                choices[headers[col - 1]] = options
    result = {
        "sheets": names,
        "sheet": selected,
        "headers": headers,
        "choices": choices,
        "all_sheets": book.sheetnames,
    }
    book.close()
    return result


def export_template(path, records, template_path, sheet):
    """Patch data cells only; copy every other OOXML member byte-for-byte."""
    import re, zipfile, posixpath, xml.etree.ElementTree as ET
    from xml.sax.saxutils import escape
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter, column_index_from_string
    from openpyxl.utils.datetime import to_excel

    if len(records) != 1:
        raise ValueError("原模板模式每个Excel仅对应一份文件，请使用批量分开导出")
    if Path(path).resolve() == Path(template_path).resolve():
        raise ValueError("不能覆盖原模板")
    meta = inspect_template(template_path, sheet)
    book = load_workbook(template_path)
    ws = book[meta["sheet"]]
    row = 2
    while row <= ws.max_row and any(
        ws.cell(row, c).value is not None for c in range(1, len(meta["headers"]) + 1)
    ):
        row += 1
    if row > ws.max_row:
        book.close()
        raise ValueError("模板无可用空白数据行，未添加或修改行格式")
    fields = records[0].get("values", {})
    patches = {}
    for col, field in enumerate(meta["headers"], 1):
        value = fields.get(field, "")
        if value is None or not str(value).strip():
            continue
        value = standard_value(
            field, str(value).strip(), meta["choices"].get(field, [])
        )
        address = f"{get_column_letter(col)}{row}"
        if field in meta["choices"] and value not in meta["choices"][field]:
            raise ValueError(field + "不在原模板字典内，请核对；未改动字典")
        if field in DATES:
            value, error = normalize_date(value)
            if error:
                raise ValueError(field + "：" + error)
            serial = to_excel(datetime.fromisoformat(value), book.epoch)
            for dv in ws.data_validations.dataValidation:
                if dv.type == "date" and address in dv.sqref:
                    if _outside_bounds(serial, dv.formula1, dv.formula2):
                        raise ValueError(field + "超出原模板日期范围")
            # The uploaded template has General date cells. ISO text preserves
            # their original style instead of adding a date format to styles.xml.
            patches[address] = ("inlineStr", value)
        elif field in NUMERIC:
            try:
                number = float(value)
            except ValueError:
                raise ValueError(field + "必须是数字")
            if (
                not math.isfinite(number)
                or number < 0
                or (field != "电子文件大小" and not number.is_integer())
            ):
                raise ValueError(field + "必须是有效非负数值")
            for dv in ws.data_validations.dataValidation:
                if dv.type in ("whole", "decimal") and address in dv.sqref:
                    if _outside_bounds(number, dv.formula1, dv.formula2):
                        raise ValueError(field + "超出原模板范围")
            patches[address] = (
                "n",
                str(int(number)) if number.is_integer() else str(number),
            )
        else:
            patches[address] = ("inlineStr", value)
    book.close()
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ridns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(template_path) as source:
        workbook = ET.fromstring(source.read("xl/workbook.xml"))
        node = next(
            n
            for n in workbook.find("s:sheets", ns)
            if n.attrib["name"] == meta["sheet"]
        )
        rels = ET.fromstring(source.read("xl/_rels/workbook.xml.rels"))
        target = next(
            n.attrib["Target"] for n in rels if n.attrib["Id"] == node.attrib[ridns]
        )
        member = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath("xl/" + target)
        )
        xml = source.read(member).decode("utf-8")
        rowpattern = re.compile(
            r'<row\b[^>]*\br="' + str(row) + r'"[^>]*>.*?</row>', re.S
        )
        rowmatch = rowpattern.search(xml)
        if not rowmatch:
            raise ValueError("模板数据行结构不受支持；未重新构建工作表")
        rowxml = rowmatch[0]
        for address, (kind, value) in patches.items():
            if len(value) > 32767 or re.search(
                r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", value
            ):
                raise ValueError("字段含非法字符或超过Excel单元格长度")
            body = (
                ('<is><t xml:space="preserve">' + escape(value) + "</t></is>")
                if kind == "inlineStr"
                else "<v>" + value + "</v>"
            )
            cellpattern = re.compile(
                r'<c\b(?P<attrs>[^>]*\br="'
                + address
                + r'"[^>]*?)(?:\s*/>|>(?P<body>.*?)</c>)',
                re.S,
            )
            found = cellpattern.search(rowxml)
            if found:
                attrs = re.sub(r'\s+t="[^"]*"', "", found["attrs"]).rstrip()
                cell = "<c" + attrs + ' t="' + kind + '">' + body + "</c>"
                rowxml = rowxml[: found.start()] + cell + rowxml[found.end() :]
            else:
                cell = '<c r="' + address + '" t="' + kind + '">' + body + "</c>"
                colnum = column_index_from_string(re.match(r"[A-Z]+", address)[0])
                later = next(
                    (
                        m
                        for m in re.finditer(r'<c\b[^>]*\br="([A-Z]+)\d+"', rowxml)
                        if column_index_from_string(m[1]) > colnum
                    ),
                    None,
                )
                offset = later.start() if later else rowxml.rfind("</row>")
                rowxml = rowxml[:offset] + cell + rowxml[offset:]
        xml = xml[: rowmatch.start()] + rowxml + xml[rowmatch.end() :]
        with zipfile.ZipFile(path, "w") as output:
            for info in source.infolist():
                output.writestr(
                    info,
                    xml.encode("utf-8")
                    if info.filename == member
                    else source.read(info.filename),
                )
