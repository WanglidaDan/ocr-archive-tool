"""One input file -> one byte-preserved template copy; isolate failures."""

import os, re, tempfile
from pathlib import Path
from template_io import export_template


def export_separate(
    records,
    folder,
    template,
    sheet,
    cancelled=lambda: False,
    progress=lambda i, r: None,
):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for index, record in enumerate(records):
        if cancelled():
            break
        item = {"source": record["path"], "output": "", "error": ""}
        reserved = None
        temporary = None
        try:
            if record.get("status") in ("待识别", "处理失败"):
                raise ValueError("文件尚未识别成功")
            stem = (
                re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(record["path"]).stem).strip(
                    " ."
                )[:100]
                or "文件"
            )
            if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", stem):
                stem = "_" + stem
            number = 1
            while True:
                # abc.pdf -> abc.xlsx. A name already in the folder gets _2, _3, ...
                name = stem + ("" if number == 1 else f"_{number}") + ".xlsx"
                reserved = folder / name
                try:
                    fd = os.open(reserved, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                    break
                except FileExistsError:
                    number += 1
            fd, tmp = tempfile.mkstemp(prefix=".archive-", suffix=".xlsx", dir=folder)
            os.close(fd)
            temporary = Path(tmp)
            export_template(temporary, [record], template, sheet)
            os.replace(temporary, reserved)
            temporary = None
            item["output"] = str(reserved)
        except Exception as error:
            item["error"] = str(error)
            if (
                reserved is not None
                and reserved.exists()
                and reserved.stat().st_size == 0
            ):
                reserved.unlink()
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        results.append(item)
        progress(index, item)
    return results


def describe_batch(records, results, stopped=False):
    """Chinese end-of-batch counts: succeeded, failed, and still needing review.

    待核对 counts exported files whose record is not 已核对. A failure is not
    also counted as needing review. Files that never reached export are listed
    under 失败 so a partial batch is visible.
    """
    produced = {
        os.path.normcase(item.get("source", "")): item for item in results or []
    }
    succeeded = 0
    failed_lines = []
    review_names = []
    for record in records or []:
        name = Path(record.get("path", "")).name or "未命名"
        item = produced.get(os.path.normcase(record.get("path", "")))
        if item is None:
            if (
                stopped
                and record.get("text")
                and record.get("status")
                not in (
                    "待识别",
                    "处理失败",
                )
            ):
                failed_lines.append(name + "：已停止，未导出")
            else:
                failed_lines.append(name + "：尚未识别成功，未导出")
            continue
        if item.get("error"):
            failed_lines.append(name + "：" + item["error"])
            continue
        succeeded += 1
        if record.get("status") != "已核对":
            review_names.append(name)
    lines = [
        f"成功 {succeeded} 份，失败 {len(failed_lines)} 份，待核对 {len(review_names)} 份。",
        "每份文件对应一个 Excel，文件名与源文件相同，不覆盖已有文件。",
    ]
    if failed_lines:
        lines.append("失败：")
        lines.extend(failed_lines)
    if review_names:
        lines.append("待核对：" + "、".join(review_names))
    return "\n".join(lines)


def _with_mapping(records, template, sheet, defaults=None):
    from catalog_map import map_piece
    from template_io import inspect_template

    meta = inspect_template(template, sheet)
    prepared = []
    for fallback, record in enumerate(records, 1):
        item = dict(record)
        item["values"] = map_piece(
            record,
            meta["choices"],
            record.get("export_order", fallback),
            defaults,
        )
        prepared.append(item)
    return prepared


def export_mapped_separate(
    records,
    folder,
    template,
    sheet,
    cancelled=lambda: False,
    progress=lambda i, r: None,
    defaults=None,
):
    """One workbook per scan, with 管理类_件 values filled from the mapping rules."""
    return export_separate(
        _with_mapping(records, template, sheet, defaults),
        folder,
        template,
        sheet,
        cancelled,
        progress,
    )


def write_summary(path, records, template, sheet="管理类_件", defaults=None):
    """Write every scan into rows 2..N of one catalog sheet, defaulting to 管理类_件."""
    from catalog_defaults import DEFAULT_SHEET
    from template_io import export_rows

    sheet = sheet or DEFAULT_SHEET
    for record in records:
        if record.get("status") in ("待识别", "处理失败"):
            raise ValueError("文件尚未识别成功：" + str(record.get("path", "")))
    export_rows(
        path,
        _with_mapping(records, template, sheet, defaults),
        template,
        sheet,
        start_row=2,
    )
