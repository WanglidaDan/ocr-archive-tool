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

from batch_export import export_mapped_separate
from catalog_defaults import DEFAULT_SHEET
from core import Processor
from template_io import inspect_template


def peak_memory_bytes():
    if sys.platform != "win32":
        import resource

        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
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
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    get_info = psapi.GetProcessMemoryInfo
    get_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    get_info.restype = wintypes.BOOL
    if not get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError("GetProcessMemoryInfo failed: " + str(ctypes.get_last_error()))
    return int(counters.PeakWorkingSetSize)


def _drawing():
    import fitz
    from fixtures import cjk_font_path
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont, fitz, cjk_font_path


def _page(lines, font):
    Image, ImageDraw, _ImageFont, _fitz, _font = _drawing()
    image = Image.new("RGB", (1800, 900), "white")
    draw = ImageDraw.Draw(image)
    y = 80
    for line in lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 140
    return image


def _pdf(path, images):
    _Image, _ImageDraw, _ImageFont, fitz, _font = _drawing()
    document = fitz.open()
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page = document.new_page(width=image.width, height=image.height)
        page.insert_image(page.rect, stream=buffer.getvalue())
    document.save(path)
    document.close()


def write_pdfs(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _Image, _ImageDraw, ImageFont, _fitz, cjk_font_path = _drawing()
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
            from fixtures import example_template

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


def _emit(text):
    """Print UTF-8. A windowed executable has no console, so stdout may be missing."""
    stream = sys.stdout
    if stream is None:
        return
    payload = (text + "\n").encode("utf-8", "replace")
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text + "\n")
        return
    buffer.write(payload)
    buffer.flush()


def windows_product_name():
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        ) as key:
            return str(winreg.QueryValueEx(key, "ProductName")[0])
    except OSError:
        return ""


def is_elevated():
    if sys.platform != "win32":
        return False
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def run_packaged(argv):
    """OCR and export inside the unpacked program. No window."""
    import getpass
    import platform
    import traceback

    from tools.offline_guard import install, remote_attempts

    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--context")
    args = parser.parse_args(argv)
    install()
    context = {}
    if args.context and Path(args.context).is_file():
        context = json.loads(Path(args.context).read_text(encoding="utf-8-sig"))
    template = Path(args.template)
    pdfs = sorted(Path(args.pdf_dir).glob("*.pdf"))
    code = 0
    error = ""
    records = []
    pages = 0
    ocr_seconds = 0.0
    exported = []
    peaks = []
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            try:
                peaks.append(peak_memory_bytes())
            except OSError:
                pass
            stop.wait(0.2)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        if not template.is_file():
            code = 2
            error = "模板不存在：" + str(template)
        elif not pdfs:
            code = 2
            error = "没有 PDF：" + str(args.pdf_dir)
        else:
            meta = inspect_template(template, DEFAULT_SHEET)
            processor = Processor()
            ocr_started = time.perf_counter()
            for path in pdfs:
                result = processor.recognize(path, meta["headers"])
                result["path"] = str(path)
                pages += int(result.get("pages") or 0)
                records.append(result)
            ocr_seconds = time.perf_counter() - ocr_started
            exported = export_mapped_separate(
                records, args.out_dir, template, DEFAULT_SHEET
            )
    except Exception:
        error = traceback.format_exc()
        code = 1
    finally:
        stop.set()
        thread.join(timeout=1)
    succeeded = sum(
        1 for item in exported if item.get("output") and not item.get("error")
    )
    failed = len(records) - succeeded
    try:
        peak = max([peak_memory_bytes(), *peaks])
    except OSError:
        peak = max(peaks) if peaks else 0
    product = windows_product_name()
    report = {
        "files": len(records),
        "pages": pages,
        "succeeded": succeeded,
        "failed": failed,
        "ocr_seconds": round(ocr_seconds, 2),
        "seconds_per_page": round(ocr_seconds / pages, 3) if pages else None,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "peak_memory_bytes": peak,
        "user": getpass.getuser(),
        "elevated": is_elevated(),
        "remote_socket_attempts": len(remote_attempts),
        "os_platform": platform.platform(),
        "windows_product_name": product,
        "runner_is_windows_server": "server" in product.lower(),
        "runner_note": (
            "GitHub windows-latest 是 Windows Server，不是干净的 Win10/11。"
            "这台机器自己带 VC++ 运行库，所以下面的 DLL 路径必须来自 zip 内部。"
        ),
    }
    if error:
        report["error"] = error
    for key, value in context.items():
        current = report.get(key)
        if key not in report or current in ("", None, [], {}):
            report[key] = value
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _emit(json.dumps(report, ensure_ascii=False))
    if report["elevated"]:
        return 4
    if report["remote_socket_attempts"]:
        return 5
    if code:
        return code
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
