"""公文 field rules shared by the evaluation and the optional app setting.

Values come only from OCR text. Dates and 文号 pass through the product
normalizers. The rules do not read ground truth and do not invent characters.
"""
from __future__ import annotations

import re

from extraction import (
    CN_DATE,
    DATE,
    NUMBER,
    canonical,
    clean,
    normalize_date,
    normalize_number,
)

TITLE_END = re.compile(
    r"(通知|通报|报告|请示|批复|函|决定|决议|意见|办法|规定|方案|计划|纪要|总结|细则|公告|公示|说明|申请书|合同|协议|要点|安排|纲要)$"
)
ORG = re.compile(
    r"^[\u4e00-\u9fffA-Za-z0-9·（）()]{2,40}"
    r"(?:局|厅|部|委|政府|党委|党组|档案馆|委员会|办公室|管理局|管理处|公司|分公司|研究院|中心|分局|分厂|作业区|项目部|部门|大学|学校)$"
)
SECRET = re.compile(r"(非涉密|无密级|普通商密|内部资料|石油内部|石油商密|油商密|绝密|机密|秘密|内部|公开)")
SALUTATION = re.compile(r"^(各.{0,20}[:：]|一[、.]|第一|现将|根据|请各|为贯彻)")
TRACKED = ("文件名称", "文号", "日期", "责任单位", "密级")


def _compact(text: str) -> str:
    text = clean(text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def _lines(text: str, rows, from_cells: bool = False):
    if from_cells and rows:
        # One line per detection box. The product's baseline merge can glue a
        # centered title onto a left-hand salutation after a small skew.
        raw_rows = []
        cells = []
        for row in rows:
            for cell in row.get("cells") or []:
                box = cell.get("box") or [[0, 0]]
                ys = [point[1] for point in box]
                xs = [point[0] for point in box]
                cells.append((
                    cell.get("page") or row.get("page") or 1,
                    sum(ys) / len(ys),
                    min(xs),
                    cell.get("text") or "",
                ))
        if not cells:
            raw_rows = list(rows)
        else:
            for page, _y, _x, cell_text in sorted(cells):
                raw_rows.append({"text": cell_text, "page": page})
    elif rows:
        raw_rows = rows
    else:
        raw_rows = []
        page = 1
        for line in text.splitlines():
            marker = re.match(r"--- 第 (\d+) 页 ---", line)
            if marker:
                page = int(marker[1])
                continue
            if line.strip():
                raw_rows.append({"text": line.strip(), "page": page})
    lines = []
    for row in raw_rows:
        raw = str(row.get("text", "")).strip()
        if not raw:
            continue
        lines.append({"raw": raw, "page": row.get("page") or 1, "compact": _compact(raw)})
    return lines


def _header(lines):
    header = []
    for line in lines:
        if line["page"] != 1 or len(header) >= 12:
            break
        if SALUTATION.match(line["compact"]):
            break
        header.append(line)
    return header


def _date_in(text: str):
    compact = _compact(text)
    matched = CN_DATE.fullmatch(compact) or DATE.fullmatch(compact)
    if not matched:
        return ""
    normal, reason = normalize_date(compact)
    return "" if reason else normal


def _pick_date(lines):
    if not lines:
        return ""
    last_page = max(line["page"] for line in lines)
    for index, line in enumerate(lines):
        if line["page"] != last_page:
            continue
        if not (ORG.fullmatch(line["compact"]) or line["compact"].endswith("文件")):
            continue
        for follow in lines[index + 1:index + 3]:
            if follow["page"] != last_page:
                break
            found = _date_in(follow["compact"])
            if found:
                return found
    # A body date alone does not establish the document date.
    return ""


def _pick_title(header):
    for index, line in enumerate(header):
        if "关于" not in line["compact"] and not TITLE_END.search(line["compact"]):
            continue
        if NUMBER.search(line["compact"]):
            continue
        title = line["compact"]
        if not TITLE_END.search(title):
            for follow in header[index + 1:index + 3]:
                if NUMBER.search(follow["compact"]) or SALUTATION.match(follow["compact"]):
                    break
                title += follow["compact"]
                if TITLE_END.search(title):
                    break
        if TITLE_END.search(title) and 4 <= len(title) <= 80:
            return title
    return ""


def _pick_number(lines, header):
    pool = header or lines[:8]
    for line in pool:
        matched = NUMBER.search(line["compact"])
        if not matched:
            continue
        normal, reason = normalize_number(matched[0])
        if normal and not reason:
            return normal
    return ""


def _pick_org(lines, header):
    if not lines:
        return ""
    last_page = max(line["page"] for line in lines)
    for index, line in enumerate(lines):
        if line["page"] != last_page or not ORG.fullmatch(line["compact"]):
            continue
        for follow in lines[index + 1:index + 3]:
            if follow["page"] != last_page:
                break
            if _date_in(follow["compact"]):
                return line["compact"]
    for line in header:
        matched = re.fullmatch(r"(.{2,40})文件", line["compact"])
        if matched and ORG.fullmatch(matched[1]):
            return matched[1]
    return ""


def _pick_secret(lines):
    counts = {}
    for line in lines:
        page = line["page"]
        counts[page] = counts.get(page, 0) + 1
        if counts[page] > 4:
            continue
        compact = line["compact"].replace("*", "★")
        matched = SECRET.search(compact)
        if not matched:
            continue
        if compact.startswith(matched[1]) and len(compact) <= 16:
            return matched[1]
    return ""


def extract_rules_plus(text: str, fields, pages: int, rows=None, from_cells: bool = False) -> dict:
    """Return product field names. Empty OCR yields empty 页数, matching the app."""
    lines = _lines(text, rows, from_cells=from_cells)
    if not any(line["compact"] for line in lines):
        return {field: "" for field in fields}
    header = _header(lines)
    kind_value = {
        "文件名称": _pick_title(header),
        "文号": _pick_number(lines, header),
        "日期": _pick_date(lines),
        "责任单位": _pick_org(lines, header),
        "密级": _pick_secret(lines),
        "页数": str(pages),
    }
    values = {}
    for field in fields:
        values[field] = kind_value.get(canonical(field), "")
    return values


def _trace(kind: str, value: str, lines) -> dict:
    empty = {"raw": "", "page": None, "line_raw": ""}
    if not value:
        return empty
    if kind == "日期":
        for line in lines:
            if _date_in(line["compact"]) == value:
                return {"raw": line["compact"], "page": line["page"], "line_raw": line["raw"]}
        for line in lines:
            for pattern in (CN_DATE, DATE):
                for match in pattern.finditer(line["compact"]):
                    normal, reason = normalize_date(match[0])
                    if normal == value and not reason:
                        return {"raw": match[0], "page": line["page"], "line_raw": line["raw"]}
    if kind == "文号":
        for line in lines:
            matched = NUMBER.search(line["compact"])
            if not matched:
                continue
            normal, reason = normalize_number(matched[0])
            if normal == value and not reason:
                return {"raw": matched[0], "page": line["page"], "line_raw": line["raw"]}
    for line in lines:
        if value == line["compact"] or value in line["compact"] or line["compact"] in value:
            return {"raw": line["compact"], "page": line["page"], "line_raw": line["raw"]}
    return {"raw": value, "page": None, "line_raw": value}


def apply_enhanced(values, evidence, warnings, text, fields, pages, rows):
    """Overwrite 题名/责任者/日期/文号/密级. 页数 stays the file frame count."""
    improved = extract_rules_plus(text, fields, pages, rows=rows, from_cells=True)
    lines = _lines(text, rows, from_cells=True)
    values = dict(values)
    evidence = {key: dict(item) if isinstance(item, dict) else item for key, item in evidence.items()}
    replaced = []
    for field in fields:
        kind = canonical(field)
        if kind not in TRACKED or kind == "密级":
            continue
        new = improved.get(field, "")
        trace = _trace(kind, new, lines)
        if new:
            evidence[field] = {
                "status": "待核对",
                "candidates": [{
                    "raw": trace["raw"] or new,
                    "value": new,
                    "page": trace["page"],
                    "line_raw": trace["line_raw"] or new,
                    "confidence": None,
                    "boxes": [],
                    "source": "公文规则增强",
                    "issue": "",
                }],
            }
        else:
            evidence[field] = {"status": "未提取", "candidates": []}
        values[field] = new
        replaced.append(field)
    kept = [warning for warning in warnings if not any(str(warning).startswith(field) for field in replaced)]
    kept.append("题名、责任者、日期、文号、密级已按公文规则增强重算，请对照原件核对")
    return values, evidence, kept
