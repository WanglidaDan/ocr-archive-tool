"""One input file -> one byte-preserved template copy; isolate failures."""

import os, re, tempfile
from pathlib import Path
from template_io import export_template


def excel_stem(path):
    stem = (
        re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(path).stem).strip(" .")[:80]
        or "文件"
    )
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", stem):
        stem = "_" + stem
    return stem


def choose_excel_name(stem, folder, overwrite, taken):
    """发文001.pdf -> 发文001.xlsx, then 发文001(1).xlsx. Never reuse a name in this batch."""
    number = 0
    while number < 10000:
        name = stem + ".xlsx" if number == 0 else f"{stem}({number}).xlsx"
        number += 1
        if name in taken:
            continue
        if not overwrite and (Path(folder) / name).exists():
            continue
        return name
    raise ValueError("无法生成不重复的 Excel 文件名")


def export_separate(
    records,
    folder,
    template,
    sheet,
    cancelled=lambda: False,
    progress=lambda i, r: None,
    overwrite=False,
    taken=None,
):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    if taken is None:
        taken = set()
    for index, record in enumerate(records):
        if cancelled():
            break
        item = {
            "source": record["path"],
            "output": "",
            "excel_name": "",
            "error": "",
        }
        reserved = None
        temporary = None
        placeholder = False
        try:
            if record.get("status") in ("待识别", "处理失败"):
                raise ValueError(record.get("warning") or "文件尚未识别成功")
            stem = excel_stem(record["path"])
            while True:
                name = choose_excel_name(stem, folder, overwrite, taken)
                reserved = folder / name
                if reserved.exists() and overwrite:
                    taken.add(name)
                    break
                try:
                    fd = os.open(reserved, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                    placeholder = True
                    taken.add(name)
                    break
                except FileExistsError:
                    taken.add(name)
                    if not overwrite:
                        continue
                    break
            fd, tmp = tempfile.mkstemp(prefix=".archive-", suffix=".xlsx", dir=folder)
            os.close(fd)
            temporary = Path(tmp)
            export_template(temporary, [record], template, sheet)
            try:
                os.replace(temporary, reserved)
            except OSError:
                raise ValueError("无法写入 Excel，文件可能正被占用：" + reserved.name)
            temporary = None
            placeholder = False
            item["output"] = str(reserved)
            item["excel_name"] = reserved.name
        except Exception as error:
            item["error"] = str(error)
            if (
                placeholder
                and reserved is not None
                and reserved.exists()
                and reserved.stat().st_size == 0
            ):
                reserved.unlink()
                taken.discard(reserved.name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        results.append(item)
        progress(index, item)
    return results


MANIFEST_COLUMNS = ("文件名", "状态", "原因", "对应Excel名")


def manifest_rows(records, results, stopped=False):
    """One row per input. Success plus failure equals the batch size."""
    produced = {}
    for item in results or []:
        produced.setdefault(os.path.normcase(item.get("source", "")), item)
    rows = []
    for record in records or []:
        name = Path(record.get("path", "")).name or "未命名"
        item = produced.get(os.path.normcase(record.get("path", "")))
        if item is None:
            reason = (
                "已停止，未导出"
                if stopped
                and record.get("text")
                and record.get("status") not in ("待识别", "处理失败")
                else (record.get("warning") or "尚未识别成功，未导出")
            )
            rows.append(
                {"文件名": name, "状态": "失败", "原因": reason, "对应Excel名": ""}
            )
            continue
        if item.get("error"):
            rows.append(
                {
                    "文件名": name,
                    "状态": "失败",
                    "原因": item["error"],
                    "对应Excel名": "",
                }
            )
            continue
        rows.append(
            {
                "文件名": name,
                "状态": "成功",
                "原因": "",
                "对应Excel名": item.get("excel_name")
                or Path(item.get("output", "")).name,
            }
        )
    return rows


def describe_batch(records, results, stopped=False):
    """Chinese success and failure counts. The two counts add up to the batch."""
    rows = manifest_rows(records, results, stopped=stopped)
    success = sum(row["状态"] == "成功" for row in rows)
    failure = sum(row["状态"] == "失败" for row in rows)
    lines = [f"成功 {success} 份，失败 {failure} 份。"]
    lines.append("每个 PDF 对应一个 Excel，文件名与源文件相同。")
    failed = [row for row in rows if row["状态"] == "失败"]
    if failed:
        lines.append("失败：")
        lines.extend(row["文件名"] + "：" + row["原因"] for row in failed)
    return "\n".join(lines)


def write_manifest(folder, records, results, stopped=False):
    """Write 处理清单.csv beside the exported workbooks."""
    import csv

    path = Path(folder) / "处理清单.csv"
    rows = manifest_rows(records, results, stopped=stopped)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


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
    overwrite=False,
    taken=None,
):
    """One workbook per scan, with 管理类_件 values filled from the mapping rules."""
    return export_separate(
        _with_mapping(records, template, sheet, defaults),
        folder,
        template,
        sheet,
        cancelled,
        progress,
        overwrite,
        taken,
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
