"""User-approved responsibility-to-filing-unit linkage, without fuzzy guesses."""

import re
import unicodedata


def unit_key(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def match_unit(responsible, options):
    key = unit_key(responsible)
    if not key:
        return "", ""
    if not options:
        return str(responsible).strip(), ""
    exact = [value for value in options if unit_key(value) == key]
    candidates = exact or [
        value for value in options if unit_key(value.rsplit("-", 1)[-1]) == key
    ]
    if len(candidates) == 1:
        return candidates[0], ""
    return "", "归档单位未找到唯一字典项，已留空，请人工核对。可关闭自动关联后手动选择"


def link_record(record, options, enabled=True):
    values = record.setdefault("values", {})
    if not enabled:
        return False
    if "归档单位" not in values and not options:
        return False
    values.setdefault("归档单位", "")
    responsible = values.get("责任者", values.get("责任单位", ""))
    unit, warning = match_unit(responsible, options)
    changed = values.get("归档单位", "") != unit
    values["归档单位"] = unit
    record.setdefault("evidence", {})["归档单位"] = {
        "status": "自动关联待核对" if unit else "未匹配",
        "candidates": [
            {
                "raw": responsible,
                "value": unit,
                "page": None,
                "source": "责任者关联（模板字典精确匹配）",
                "confidence": None,
                "issue": warning,
            }
        ],
    }
    old = [
        s
        for s in record.get("warning", "").split("；")
        if s and not s.startswith("归档单位未找到唯一字典项")
    ]
    if warning:
        old.append(warning)
    record["warning"] = "；".join(old)
    previous = record.get("status")
    if record.get("text") and (changed or warning):
        record["status"] = "待核对"
    return changed or record.get("status") != previous
