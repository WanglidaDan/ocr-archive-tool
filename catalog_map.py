"""Map one recognized scan onto a 管理类_件 row."""

from pathlib import Path

from catalog_defaults import effective_defaults
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


def _chosen(value, field, choices):
    """Keep free text. A dropdown field must match one entry or stay blank."""
    text = _text(value)
    options = choices.get(field) or []
    if not text:
        return ""
    if options:
        return exact_option(text, options)
    return text


def format_file_size(nbytes, unit="KB"):
    """Convert a byte size for the 电子文件大小 cell.

    The standard template rejects values above 9999999, so bytes overflow once
    a file is about 9.5MB. KB is the default until the owner confirms the unit.
    A non-empty file never becomes 0 when the unit is coarser than a byte.
    """
    chosen = str(unit or "KB").upper()
    if chosen not in {"B", "KB", "MB"}:
        chosen = "KB"
    size = int(nbytes)
    if chosen == "B":
        return str(size)
    scale = 1024 if chosen == "KB" else 1024 * 1024
    value = round(size / scale)
    if size > 0 and value < 1:
        value = 1
    return str(value)


def map_piece(record, choices, order, defaults=None, size_unit="KB"):
    """Build cell values for one 管理类_件 row.

    Blank fields are omitted so the template cell stays empty. A value already
    on the record wins over the default. Dropdown defaults that are not in the
    template are omitted. 归档单位 uses the responsibility match, then a
    manually chosen dropdown value; otherwise it stays blank.
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
        put("电子文件大小", format_file_size(Path(path).stat().st_size, size_unit))
    put("题名", values.get("题名") or values.get("文件名称"))
    put("责任者", responsible)
    put("页数", values.get("页数"))
    put("正本数量", values.get("正本数量"))
    put("文件编号", values.get("文件编号") or values.get("文号"))
    put("密级", exact_option(values.get("密级"), choices.get("密级", [])))
    put(
        "归档单位",
        _chosen(responsible, "归档单位", choices)
        or _chosen(values.get("归档单位"), "归档单位", choices),
    )
    put(
        "归档单位(系统生成)",
        _chosen(responsible, "归档单位(系统生成)", choices),
    )
    put("电子文件数量", "1")
    put("临时序号", order)
    if path:
        put("电子文件关联项", Path(path).name)
    for field, value in effective_defaults(defaults).items():
        put(
            field,
            _chosen(values.get(field), field, choices)
            or _chosen(value, field, choices),
        )
    return mapped
