"""Map one recognized scan onto a 管理类_件 row."""

from pathlib import Path

from catalog_defaults import DEFAULTS
from extraction import normalize_date
from unit_link import unit_key


def exact_option(value, options):
    """Return the dropdown entry that matches exactly, otherwise blank."""
    key = unit_key(value)
    if not key or not options:
        return ""
    found = [item for item in options if unit_key(item) == key]
    if len(found) == 1:
        return found[0]
    return ""


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def map_piece(record, choices, order):
    """Build cell values for one 管理类_件 row.

    Blank fields are omitted so the template cell stays empty. DEFAULTS is
    applied last; an empty default does not write the column.
    """
    values = record.get("values") or {}
    mapped = {}

    def put(field, value):
        text = _text(value)
        if text:
            mapped[field] = text

    responsible = _text(values.get("责任者") or values.get("责任单位"))
    raw_date = _text(values.get("文件日期") or values.get("日期"))
    if raw_date:
        normal, error = normalize_date(raw_date)
        if normal and not error:
            put("文件日期", normal)
            put("年度", normal[:4])
    path = record.get("path") or ""
    if path and Path(path).is_file():
        put("电子文件大小", Path(path).stat().st_size)
    put("题名", values.get("题名") or values.get("文件名称"))
    put("责任者", responsible)
    put("页数", values.get("页数"))
    put("正本数量", values.get("正本数量"))
    put("文件编号", values.get("文件编号") or values.get("文号"))
    put("密级", exact_option(values.get("密级"), choices.get("密级", [])))
    put("归档单位", exact_option(responsible, choices.get("归档单位", [])))
    put(
        "归档单位(系统生成)",
        exact_option(responsible, choices.get("归档单位(系统生成)", [])),
    )
    put("电子文件数量", "1")
    put("临时序号", order)
    if path:
        put("电子文件关联项", Path(path).name)
    for field, value in DEFAULTS.items():
        put(field, value)
    return mapped
