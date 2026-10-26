"""Headless smoke: 10 synthetic PDFs through OCR and export. No window."""

import argparse
import io
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image, ImageDraw, ImageFont
import fitz
from batch_export import export_mapped_separate
from catalog_defaults import DEFAULT_SHEET
from core import Processor
from fixtures import cjk_font_path, example_template
from template_io import inspect_template


def peak_memory_bytes():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        if not ok:
            return 0
        return int(counters.PeakWorkingSetSize)
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _page(lines, font):
    image = Image.new("RGB", (1800, 900), "white")
    draw = ImageDraw.Draw(image)
    y = 80
    for line in lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 140
    return image


def _pdf(path, images):
    document = fitz.open()
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page = document.new_page(width=image.width, height=image.height)
        page.insert_image(page.rect, stream=buffer.getvalue())
    document.save(path)
    document.close()


def write_pdfs(folder):
    font = ImageFont.truetype(str(cjk_font_path()), 72)
    paths = []
    for number, count in enumerate([1, 2, 3, 4, 5, 1, 2, 3, 4, 5], 1):
        pages = [
            _page(
                [
                    f"文件名称：归档通知{number:02d}",
                    "文号：档发〔2026〕12号",
                    "日期：2026年10月26日",
                    "责任单位：示例单位A",
                ],
                font,
            )
            for _ in range(count)
        ]
        path = folder / f"file-{number:02d}.pdf"
        _pdf(path, pages)
        paths.append(path)
    return paths


def run(report_path, zip_path=None):
    peaks = []
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            peaks.append(peak_memory_bytes())
            stop.wait(0.2)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            template = example_template()
            meta = inspect_template(template, DEFAULT_SHEET)
            pdfs = write_pdfs(folder / "pdfs")
            processor = Processor()
            records = []
            pages = 0
            ocr_started = time.perf_counter()
            for path in pdfs:
                result = processor.recognize(path, meta["headers"])
                result["path"] = str(path)
                pages += int(result.get("pages") or 0)
                records.append(result)
            ocr_seconds = time.perf_counter() - ocr_started
            exported = export_mapped_separate(
                records, folder / "out", template, DEFAULT_SHEET
            )
    finally:
        stop.set()
        thread.join(timeout=1)
    succeeded = sum(
        1 for item in exported if item.get("output") and not item.get("error")
    )
    failed = len(exported) - succeeded
    elapsed = time.perf_counter() - started
    peak = max([peak_memory_bytes(), *peaks] or [0])
    zip_bytes = (
        Path(zip_path).stat().st_size if zip_path and Path(zip_path).is_file() else None
    )
    report = {
        "files": len(records),
        "pages": pages,
        "succeeded": succeeded,
        "failed": failed,
        "ocr_seconds": round(ocr_seconds, 2),
        "seconds_per_page": round(ocr_seconds / pages, 3) if pages else None,
        "elapsed_seconds": round(elapsed, 2),
        "peak_memory_bytes": peak,
        "zip_bytes": zip_bytes,
    }
    Path(report_path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    if succeeded != len(records) or failed:
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--zip")
    args = parser.parse_args(argv)
    return run(args.report, args.zip)


if __name__ == "__main__":
    sys.exit(main())
