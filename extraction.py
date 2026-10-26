"""Conservative structured extraction with per-field evidence and validation.

Normalization never changes the preserved OCR text. Ambiguous candidates are
returned as evidence, never resolved by taking the first match.
"""

import re
import unicodedata
from datetime import date

ALIASES = {
    "文件名称": ["文件名称", "文件题名", "档案题名", "题名", "标题"],
    "文号": ["发文字号", "文件编号", "文号"],
    "日期": ["成文日期", "形成日期", "发文日期", "文件日期", "日期"],
    "责任单位": ["责任单位", "发文单位", "形成单位", "责任者", "单位"],
    "页数": ["页数"],
    "备注": ["备注"],
}
NUMBER = re.compile(
    r"(?<![\u4e00-\u9fffA-Za-z0-9])([\u4e00-\u9fffA-Za-z]{1,20})\s*([〔\[【(])\s*(\d{4})\s*([〕\]】)])\s*(第?\s*\d{1,8}\s*号)"
)
DATE = re.compile(
    r"(?<!\d)(\d{4})\s*(?:年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日|[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2}))(?!\d)"
)
CN_DATE = re.compile(
    r"([〇零○ＯO一二三四五六七八九]{4})年([一二三四五六七八九十]{1,3})月([一二三四五六七八九十]{1,3})日"
)
ORG_SUFFIX = (
    r"档案馆|委员会|办公室|管理局|管理处|分公司|公司|研究院|中心|分局|分厂|"
    r"作业区|项目部|部门|大学|学校|报社|机关|集团|医院|学院"
)
ORG = re.compile(rf"^[\u4e00-\u9fffA-Za-z0-9·（）()]{{0,40}}(?:{ORG_SUFFIX})$")
TITLE_END = re.compile(
    r"(通知|通报|报告|请示|批复|函|决定|决议|意见|办法|规定|方案|计划|纪要|总结|细则|公告|公示|说明|申请书|合同|协议)$"
)


def clean(value):
    s = unicodedata.normalize("NFKC", str(value))
    # OCR often inserts spaces between Chinese characters and numeric glyphs.
    s = re.sub(r"(?<=\d)\s+(?=\d)", "", s)
    return s.strip()


def compact_cjk(value):
    """Drop spaces that OCR inserts between Chinese characters."""
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", clean(value))


def _is_date_line(value):
    text = clean(value)
    compact = re.sub(r"\s+", "", text)
    return bool(
        DATE.fullmatch(text)
        or DATE.fullmatch(compact)
        or CN_DATE.fullmatch(compact)
        or CN_DATE.fullmatch(text)
    )


def _is_org_line(value):
    text = compact_cjk(value)
    if not text or text.startswith("各"):
        return False
    if any(ch in text for ch in "，。；;、：:"):
        return False
    return bool(ORG.fullmatch(text))


def _header_org(rows):
    """文头「单位文件」on the first page, before the body."""
    for row in rows[:6]:
        match = re.fullmatch(
            r"([\u4e00-\u9fffA-Za-z0-9·（）()]{2,40})文件",
            compact_cjk(row["clean"]),
        )
        if match and _is_org_line(match[1]):
            return match[1], row
    return None, None


def _signature_org(lines):
    """落款：an organization line followed by a date, on any page."""
    for index, row in enumerate(lines[:-1]):
        nxt = lines[index + 1]
        if nxt.get("page") != row.get("page"):
            continue
        text = compact_cjk(row["clean"])
        if _is_org_line(text) and _is_date_line(nxt["clean"]):
            return text, row, nxt
    return None, None, None


def canonical(field):
    return next((k for k, aliases in ALIASES.items() if field in aliases), field)


def cn_number(s):
    digits = {v: k for k, v in enumerate("零一二三四五六七八九")}
    if "十" in s:
        a, b = s.split("十")
        return (digits.get(a, 1) if a else 1) * 10 + (digits.get(b, 0) if b else 0)
    return digits.get(s, -1)


def normalize_date(value):
    s = clean(value)
    m = DATE.fullmatch(s)
    if m:
        y = int(m[1])
        month = int(m[2] or m[4])
        day = int(m[3] or m[5])
    else:
        m = CN_DATE.fullmatch(re.sub(r"\s+", "", s))
        if not m:
            return "", "日期格式不能可靠解析"
        digits = {v: str(k) for k, v in enumerate("零一二三四五六七八九")}
        digits.update({"〇": "0", "○": "0", "O": "0"})
        y = int("".join(digits.get(ch, "0") for ch in m[1]))
        month = cn_number(m[2])
        day = cn_number(m[3])
    try:
        return date(y, month, day).isoformat(), ""
    except ValueError:
        return "", "无效日期，已留空"


def normalize_number(value):
    s = clean(value)
    # Spaces inside document identifiers are OCR segmentation artifacts.
    compact = re.sub(r"\s+", "", s)
    m = NUMBER.fullmatch(compact)
    if m:
        return f"{m[1]}〔{m[3]}〕{m[5]}", ""
    # Some archives use non-year serials: preserve an explicit labelled value,
    # but do not treat prose or malformed bracketed years as a valid identifier.
    if any(ch in compact for ch in "〔〕[]【】()"):
        return "", "文号结构异常，已留空"
    if 1 <= len(compact) <= 60 and re.fullmatch(
        r"[\u4e00-\u9fffA-Za-z0-9_./—\-号]+", compact
    ):
        return compact, ""
    return "", "文号包含无法确认的内容，已留空"


def reading_rows(items):
    """Group OCR boxes by baseline; join label/value cells left-to-right."""
    rows = []
    for item in sorted(
        items,
        key=lambda i: (sum(p[1] for p in i["box"]) / 4, min(p[0] for p in i["box"])),
    ):
        y = sum(p[1] for p in item["box"]) / 4
        h = max(p[1] for p in item["box"]) - min(p[1] for p in item["box"])
        match = next(
            (
                r
                for r in reversed(rows[-4:])
                if abs(r["y"] - y) <= 0.45 * min(r["height"], max(h, 1))
            ),
            None,
        )
        if match is None:
            rows.append({"y": y, "height": max(h, 1), "items": [item]})
        else:
            match["items"].append(item)
    result = []
    for row in rows:
        cells = sorted(row["items"], key=lambda i: min(p[0] for p in i["box"]))
        result.append(
            {
                "text": "  ".join(c["text"] for c in cells),
                "page": cells[0]["page"],
                "confidence": min(c["confidence"] for c in cells),
                "boxes": [c["box"] for c in cells],
                "cells": cells,
            }
        )
    return result


def extract_details(text, fields, pages, rows=None, additional=None):
    warnings = []
    values = {}
    evidence = {}
    if rows is None:
        rows = []
        page = 1
        for line in text.splitlines():
            m = re.match(r"--- 第 (\d+) 页 ---", line)
            if m:
                page = int(m[1])
                continue
            if line.strip():
                rows.append(
                    {
                        "text": line.strip(),
                        "page": page,
                        "confidence": None,
                        "boxes": [],
                    }
                )
    lines = [{**r, "clean": clean(r["text"])} for r in rows if str(r["text"]).strip()]
    alias_to_kind = {
        alias: kind for kind, aliases in ALIASES.items() for alias in aliases
    }
    for field in fields:
        if canonical(field) not in ALIASES:
            alias_to_kind[field] = field
    # "编号" alone is only a template field, not an alias for an official document number.
    aliases = sorted(alias_to_kind, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![\u4e00-\u9fffA-Za-z0-9])("
        + "|".join(re.escape(a) for a in aliases)
        + r")\s*:"
    )
    # A document header plus its identifier establishes official-document mode.
    # Body paragraphs can themselves discuss '标题' / '日期' and are not metadata.
    first = [r for r in lines if r["page"] == 1]
    official = any(
        re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9（）() ]{2,60}文件", r["clean"])
        for r in first[:6]
    ) and any(NUMBER.search(re.sub(r"\s+", "", r["clean"])) for r in first[:8])
    header = []
    for row in lines:
        if row["page"] != 1 or len(header) >= 12:
            break
        s = row["clean"]
        if re.match(r"^(各.{0,20}[:：]|一[、.]|第一|现将|根据|请各|为贯彻)", s):
            break
        header.append(row)
    header_ids = {id(r) for r in header}
    by_kind = {}
    labelled = set()

    def add(kind, value, row, source):
        by_kind.setdefault(kind, []).append(
            {
                "raw": value.strip(),
                "page": row.get("page"),
                "line_raw": row.get("text", value),
                "confidence": row.get("confidence"),
                "boxes": row.get("boxes", []),
                "source": source,
            }
        )

    for i, row in enumerate(lines):
        s = row["clean"]
        matches = list(pattern.finditer(s))
        if matches:
            for n, m in enumerate(matches):
                kind = alias_to_kind[m[1]]
                if (
                    official
                    and kind in ("文件名称", "文号", "日期", "责任单位")
                    and id(row) not in header_ids
                ):
                    continue
                labelled.add(kind)
                end = matches[n + 1].start() if n + 1 < len(matches) else len(s)
                content = s[m.end() : end].strip(" \t|;；")
                if not content and i + 1 < len(lines):
                    nxt = lines[i + 1]
                    if (
                        nxt["page"] == row["page"]
                        and not pattern.search(nxt["clean"])
                        and nxt["clean"].strip(":") not in alias_to_kind
                    ):
                        add(kind, nxt["text"], nxt, "标签下一行")
                        continue
                if content:
                    add(kind, content, row, "字段标签")
        elif s.strip(":") in alias_to_kind:
            kind = alias_to_kind[s.strip(":")]
            if (
                official
                and kind in ("文件名称", "文号", "日期", "责任单位")
                and id(row) not in header_ids
            ):
                continue
            labelled.add(kind)
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                if (
                    nxt["page"] == row["page"]
                    and not pattern.search(nxt["clean"])
                    and nxt["clean"].strip(":") not in alias_to_kind
                ):
                    add(kind, nxt["text"], nxt, "独立标签下一行")
    # Unlabelled fallback only for kinds without explicit labels. Explicit
    # contradictions or empty labels must not be bypassed by a later regex.
    for row in lines:
        s = row["clean"]
        if "文号" not in labelled and (not official or id(row) in header_ids):
            # Compact whitespace in a line; numeric OCR tokens may be separated.
            for m in NUMBER.finditer(re.sub(r"\s+", "", s)):
                add("文号", m[0], row, "文号结构")
        if "日期" not in labelled:
            for m in DATE.finditer(s):
                add("日期", m[0], row, "日期候选")
            for m in CN_DATE.finditer(s):
                add("日期", m[0], row, "中文日期候选")
    # Common official titles: only in the first-page header before the salutation/body.
    # A clear semantic prefix and ending are required; no generic "first line" guess.
    if "文件名称" not in labelled:
        for i, row in enumerate(header):
            s = row["clean"]
            if re.match(r"^(?:[\u4e00-\u9fff]{2,20})?关于", s) and not pattern.search(
                s
            ):
                title = s
                used = [row]
                if not TITLE_END.search(title):
                    for nxt in header[i + 1 : i + 3]:
                        if pattern.search(nxt["clean"]) or NUMBER.search(nxt["clean"]):
                            break
                        title += nxt["clean"]
                        used.append(nxt)
                        if TITLE_END.search(title):
                            break
                if TITLE_END.search(title) and len(title) <= 150:
                    add("文件名称", title, row, "首页公文标题候选")
                    by_kind["文件名称"][-1]["raw"] = "\n".join(r["text"] for r in used)
                    by_kind["文件名称"][-1]["joined"] = title
    if "责任单位" not in labelled:
        # Signature on any page, then the first-page 文头. Attachment pages
        # often push the 落款 off the last page, so the last page alone is not
        # enough. A body mention without a following date is ignored.
        org, org_row, date_row = _signature_org(lines)
        source = "落款候选"
        if org is None:
            org, org_row = _header_org(first)
            date_row = None
            source = "文头单位候选"
        if org:
            add("责任单位", org, org_row, source)
            if date_row is not None and "日期" not in labelled:
                add("日期", date_row["text"], date_row, "落款日期候选")
    if official and "日期" not in labelled:
        signature_dates = [c for c in by_kind.get("日期", []) if "落款" in c["source"]]
        if signature_dates:
            by_kind["日期"] = signature_dates
    # Per-document classification: only explicit header marks, no default.
    if "密级" in fields:
        by_kind["密级"] = []
        mark = re.compile(
            r"^(?:密级[:：]?)?(非涉密|无密级|油商密★{1,2}|普通商密|内部资料|石油内部|石油商密|绝密|机密|秘密|内部|公开)(?:[★·]*\d{1,2}年)?$"
        )
        counts = {}
        for row in lines:
            page = row["page"]
            counts[page] = counts.get(page, 0) + 1
            if counts[page] > 4:
                continue
            boxes = row.get("boxes", [])
            width = row.get("page_width")
            height = row.get("page_height")
            if boxes and width and height:
                if min(p[1] for b in boxes for p in b) > height * 0.25:
                    continue
            compact = re.sub(r"\s+", "", row["clean"]).replace("*", "★")
            match = mark.fullmatch(compact)
            if match:
                add("密级", match[1], row, "本文件页眉密级标识")
            for cell in row.get("cells", []):
                found = mark.fullmatch(
                    re.sub(r"\s+", "", clean(cell["text"])).replace("*", "★")
                )
                if found:
                    add(
                        "密级",
                        found[1],
                        {
                            **row,
                            "text": cell["text"],
                            "boxes": [cell["box"]],
                            "confidence": cell["confidence"],
                        },
                        "本文件页眉密级单元",
                    )
        if not by_kind["密级"]:
            warnings.append("未发现明确密级标识，已留空待核对；未默认无密级")
    if (
        "正本数量" in fields
        and "正本数量" not in labelled
        and not by_kind.get("正本数量")
    ):
        add(
            "正本数量",
            "1",
            {"page": None, "text": "", "confidence": None, "boxes": []},
            "业务默认值（用户指定，非OCR）",
        )
    # Model candidates are additive: never overwrite or conceal rule conflicts.
    for kind, value in (additional or {}).items():
        kind = canonical(kind)
        if value and kind != "密级":
            row = next(
                (r for r in lines if value in r["text"]),
                {"page": None, "confidence": None, "boxes": []},
            )
            add(kind, value, row, "本地模型候选")
    if "年度" in fields and "年度" not in labelled:
        date_values = {normalize_date(c["raw"])[0] for c in by_kind.get("日期", [])}
        if len(date_values) == 1 and "" not in date_values:
            candidate = by_kind["日期"][0]
            add("年度", next(iter(date_values))[:4], candidate, "文件日期推导候选")
    for field in fields:
        kind = canonical(field)
        if kind == "页数":
            values[field] = str(pages)
            evidence[field] = {
                "status": "页数统计",
                "candidates": [
                    {
                        "raw": str(pages),
                        "value": str(pages),
                        "page": None,
                        "confidence": None,
                        "source": "文件页数",
                    }
                ],
            }
            continue
        candidates = by_kind.get(kind, [])
        valid = []
        invalid = []
        for candidate in candidates:
            raw = candidate.get("joined", candidate["raw"])
            normal = clean(raw)
            reason = ""
            if kind == "日期":
                normal, reason = normalize_date(raw)
            elif kind == "文号":
                normal, reason = normalize_number(raw)
            item = {**candidate, "value": normal, "issue": reason}
            if normal != candidate["raw"] and normal:
                item["normalized"] = True
            if reason:
                invalid.append(item)
            elif normal:
                valid.append(item)
        distinct = {c["value"] for c in valid}
        if len(distinct) > 1:
            value = ""
            status = "候选冲突"
            warnings.append(field + "存在多个不同候选，已留空")
        elif invalid:
            value = ""
            status = "格式异常"
            warnings.append(field + "存在不能确认的格式，已留空")
        elif len(distinct) == 1:
            value = next(iter(distinct))
            status = "待核对"
            if any(c.get("normalized") for c in valid):
                warnings.append(field + "已规范化，请对照原文核对")
            if any(
                c.get("confidence") is not None and c["confidence"] < 0.85
                for c in valid
            ):
                warnings.append(field + "对应文字置信度偏低")
            if any("候选" in c["source"] for c in valid):
                warnings.append(field + "由版式或模型推定，请核对")
        else:
            value = ""
            status = "未提取"
            if kind == "责任单位":
                warnings.append("责任者未识别，请人工核对")
        values[field] = value
        evidence[field] = {"status": status, "candidates": valid + invalid}
    number = next((values[f] for f in fields if canonical(f) == "文号"), "")
    dt = next((values[f] for f in fields if canonical(f) == "日期"), "")
    year = re.search(r"〔(\d{4})〕", number)
    if year and dt and year[1] != dt[:4]:
        warnings.append("文号年份与文件日期年份不一致，已分别保留，请核对原件")

    return values, evidence, list(dict.fromkeys(warnings))


def extract(text, fields, pages):
    return extract_details(text, fields, pages)[0]
