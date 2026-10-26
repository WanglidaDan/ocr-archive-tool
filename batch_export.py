"""One input file -> one byte-preserved template copy; isolate failures."""

import os, re, tempfile
from pathlib import Path
from errors import chinese_message
from template_io import export_template


def excel_stem(path):
    stem = (
        re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(path).stem).strip(" .")[:80]
        or "文件"
    )
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", stem):
        stem = "_" + stem
    return stem


def describe_excel_name(source, excel_name):
    """Explain a reserved-name, sanitized, truncated, or numbered workbook name."""
    original = Path(source).stem
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original).strip(" .")
    notes = []
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", cleaned or original):
        notes.append(
            f"源文件名“{original}”是 Windows 保留名，已改为“_{cleaned or original}”"
        )
    elif cleaned != original:
        notes.append("文件名含有不能用于 Excel 的字符或首尾空格，已调整")
    if len(cleaned) > 80:
        notes.append("文件名超过 80 个字符，已截断")
    stem = excel_stem(source)
    if excel_name and excel_name != f"{stem}.xlsx":
        notes.append("输出目录中已有同名文件，已在文件名后加序号")
    return "；".join(notes)


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


def _failed_item(record, message):
    return {
        "source": record.get("path", ""),
        "output": "",
        "excel_name": "",
        "name_note": "",
        "error": message,
    }


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
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception as error:
        message = chinese_message(error)
        return [_failed_item(record, message) for record in records]
    results = []
    if taken is None:
        taken = set()
    for index, record in enumerate(records):
        if cancelled():
            break
        item = {
            "source": record.get("path", ""),
            "output": "",
            "excel_name": "",
            "name_note": "",
            "error": "",
        }
        reserved = None
        temporary = None
        placeholder = False
        try:
            if record.get("_map_error"):
                raise ValueError(record["_map_error"])
            if record.get("status") in ("待识别", "处理失败"):
                raise ValueError(record.get("warning") or "文件尚未识别，未导出")
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
            item["name_note"] = describe_excel_name(record["path"], reserved.name)
        except Exception as error:
            item["error"] = chinese_message(error)
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
        source = record.get("path", "")
        if item is None:
            if (
                stopped
                and record.get("text")
                and record.get("status") not in ("待识别", "处理失败")
            ):
                reason = "已停止，未导出"
            elif record.get("warning"):
                reason = record["warning"]
            elif record.get("status") == "处理失败":
                reason = record.get("warning") or "识别失败，未导出"
            else:
                reason = "尚未识别，未导出"
            rows.append(_manifest_row(name, source, "", "失败", reason, ""))
            continue
        if item.get("error"):
            rows.append(_manifest_row(name, source, "", "失败", item["error"], ""))
            continue
        excel = item.get("excel_name") or Path(item.get("output", "")).name
        note = item.get("name_note") or ""
        rows.append(_manifest_row(name, source, excel, "成功", "", note))
    return rows


def _manifest_row(name, source, excel, status, reason, note):
    shown = excel
    if excel and note:
        shown = f"{excel}（{note}）"
    return {
        "文件名": name,
        "状态": status,
        "原因": reason,
        "对应Excel名": excel,
        "源文件路径": source,
        "导出文件名": shown,
        "结果": status,
        "建议操作": suggest_action(reason, status == "成功", note),
    }


def suggest_action(reason, success, note=""):
    if success:
        return "请核对导出文件名" if note else "无需处理"
    text = reason or ""
    rules = (
        ("加密", "请先解密后再导入"),
        ("空文件", "请检查源文件是否为空"),
        ("是空的", "请检查源文件是否为空"),
        ("模板", "请在设置中重新选择有效模板"),
        ("工作表", "请检查模板是否包含「管理类_件」"),
        ("磁盘", "请清理磁盘空间后重试"),
        ("权限", "请检查文件夹是否只读或没有写入权限"),
        ("占用", "请关闭正在使用该文件的程序后重试"),
        ("超出原模板", "请调整电子文件大小单位或核对字段"),
        ("已停止", "可再次导出未完成的文件"),
        ("尚未识别", "请先完成识别"),
        ("识别失败", "请查看原因后重新识别"),
        ("损坏", "请更换文件或重新扫描"),
        ("不完整", "请更换文件或重新扫描"),
        ("清晰度", "请检查扫描清晰度、方向或重新扫描"),
        ("未识别", "请人工核对或重新识别"),
    )
    for key, action in rules:
        if key in text:
            return action
    return "请查看原因后重试"


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
        lines.extend(
            (row.get("源文件路径") or row["文件名"]) + "：" + row["原因"]
            for row in failed
        )
    return "\n".join(lines)


def write_manifest(folder, records, results, stopped=False):
    """Write 处理清单.csv beside the exported workbooks."""
    import csv

    path = Path(folder) / "处理清单.csv"
    rows = manifest_rows(records, results, stopped=stopped)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


LIST_COLUMNS = ("源文件路径", "导出文件名", "结果", "原因", "建议操作")


def write_export_list(folder, records, results, stopped=False):
    """Write 导出清单_<timestamp>.xlsx beside the exported workbooks."""
    from datetime import datetime
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = folder / f"导出清单_{stamp}.xlsx"
    suffix = 2
    while path.exists():
        path = folder / f"导出清单_{stamp}_{suffix}.xlsx"
        suffix += 1
    book = Workbook()
    sheet = book.active
    sheet.title = "导出清单"
    sheet.append(list(LIST_COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in manifest_rows(records, results, stopped=stopped):
        reason = row["原因"]
        if row["结果"] == "成功" and row["导出文件名"] != row["对应Excel名"]:
            reason = row["导出文件名"].split("（", 1)[-1].rstrip("）")
        sheet.append(
            [
                row["源文件路径"],
                row["导出文件名"],
                row["结果"],
                reason,
                row["建议操作"],
            ]
        )
    for cell in sheet["A"]:
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    for column, width in zip("ABCDE", (72, 48, 10, 36, 28)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    book.save(path)
    book.close()
    return path


def _with_mapping(records, template, sheet, defaults=None, size_unit="KB"):
    """Map each record on its own so a broken template does not stop the batch."""
    from catalog_map import map_piece
    from template_io import inspect_template

    prepared = []
    for fallback, record in enumerate(records, 1):
        item = dict(record)
        try:
            meta = inspect_template(template, sheet)
            item["values"] = map_piece(
                record,
                meta["choices"],
                record.get("export_order", fallback),
                defaults,
                size_unit,
            )
        except Exception as error:
            item["_map_error"] = chinese_message(error)
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
    size_unit="KB",
):
    """One workbook per scan, with 管理类_件 values filled from the mapping rules."""
    return export_separate(
        _with_mapping(records, template, sheet, defaults, size_unit),
        folder,
        template,
        sheet,
        cancelled,
        progress,
        overwrite,
        taken,
    )


def write_summary(
    path, records, template, sheet="管理类_件", defaults=None, size_unit="KB"
):
    """Write every scan into rows 2..N of one catalog sheet, defaulting to 管理类_件."""
    from catalog_defaults import DEFAULT_SHEET
    from template_io import export_rows

    sheet = sheet or DEFAULT_SHEET
    for record in records:
        if record.get("status") in ("待识别", "处理失败"):
            raise ValueError(
                record.get("warning")
                or "文件尚未识别，未导出：" + str(record.get("path", ""))
            )
    prepared = _with_mapping(records, template, sheet, defaults, size_unit)
    failed = next(
        (item.get("_map_error") for item in prepared if item.get("_map_error")), ""
    )
    if failed:
        raise ValueError(failed)
    export_rows(path, prepared, template, sheet, start_row=2)
