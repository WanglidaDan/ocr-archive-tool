"""Recognition status, kept apart from export success or failure.

已识别 requires every required field, including 责任者, to be non-empty, and
every numeric field confidence to be at least 0.85. 页数 is a page count, so
it has no OCR confidence. 待核对 is any finished read that misses that bar.
已核对 is set only by the user. 失败 means the file could not be read.
"""

from extraction import canonical

RECOGNIZED = "已识别"
NEEDS_REVIEW = "待核对"
REVIEWED = "已核对"
FAILED = "失败"
LEGACY_FAILED = "处理失败"
STOPPED = "已停止，可重新识别"
PENDING = "待识别"
CONFIDENCE_MIN = 0.85
REQUIRED = {"文件名称", "文号", "日期", "责任单位", "页数"}
OCR_QUEUE = {PENDING, FAILED, LEGACY_FAILED, STOPPED}


def _numeric_confidence(evidence):
    candidates = (evidence or {}).get("candidates") or []
    usable = [item for item in candidates if not item.get("issue")]
    scores = []
    for item in usable or candidates:
        score = item.get("confidence")
        if score is None:
            continue
        scores.append(float(score))
    if not scores:
        return None
    return min(scores)


def classify_recognition(fields, values, evidence=None, confidence=None):
    """Return 已识别 or 待核对 from the finished values and evidence."""
    values = values or {}
    evidence = evidence or {}
    fields = list(fields or [])
    if not REQUIRED <= {canonical(field) for field in fields}:
        return NEEDS_REVIEW
    for field in fields:
        if canonical(field) in REQUIRED and not str(values.get(field, "")).strip():
            return NEEDS_REVIEW
    saw_required_score = False
    for field in fields:
        kind = canonical(field)
        score = _numeric_confidence(evidence.get(field))
        if score is None:
            if kind in REQUIRED and kind != "页数":
                return NEEDS_REVIEW
            continue
        if kind in REQUIRED and kind != "页数":
            saw_required_score = True
        if score < CONFIDENCE_MIN:
            return NEEDS_REVIEW
    if confidence is not None and not saw_required_score:
        try:
            if float(confidence) < CONFIDENCE_MIN:
                return NEEDS_REVIEW
        except (TypeError, ValueError):
            return NEEDS_REVIEW
    return RECOGNIZED


def needs_ocr(record):
    """True when 开始识别 or a failed-export retry should read the file again."""
    if record.get("status") in OCR_QUEUE:
        return True
    return not str(record.get("text") or "").strip()


def not_exportable(record):
    return record.get("status") in OCR_QUEUE


def recognition_block_reason(record):
    """Why a record cannot be written into the template yet."""
    status = record.get("status")
    warning = str(record.get("warning") or "").strip()
    if status == STOPPED:
        return warning or STOPPED
    if status in (FAILED, LEGACY_FAILED):
        return warning or "识别失败，未导出"
    if warning:
        return warning
    return "尚未识别，未导出"
