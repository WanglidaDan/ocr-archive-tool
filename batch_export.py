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
                name = stem + "_目录" + ("" if number == 1 else f"_{number}") + ".xlsx"
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
