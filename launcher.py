"""Bootstrap native Qt desktop with local startup diagnostics."""

import os
import sys
from pathlib import Path


def _write_startup_error(text):
    targets = []
    if getattr(sys, "frozen", False):
        targets.append(Path(sys.executable).resolve().parent / "startup-error.txt")
    targets.append(
        Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        / "ArchiveDesk"
        / "startup-error.txt"
    )
    written = []
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            written.append(target)
        except OSError:
            continue
    return written


def _check_models():
    """Load the bundled RapidOCR models and exit. No window, no network."""
    from rapidocr_onnxruntime import RapidOCR

    RapidOCR()
    print("models-ok")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--check" in argv:
        return _check_models()
    from app import main as app_main

    app_main()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback

        text = traceback.format_exc()
        if "--check" in sys.argv:
            print(text, file=sys.stderr)
            sys.exit(1)
        written = _write_startup_error(text)
        if sys.platform == "win32":
            import ctypes

            where = "\n".join(str(path) for path in written) or "（未能写入诊断文件）"
            ctypes.windll.user32.MessageBoxW(
                None,
                "启动失败。若杀毒软件拦截了程序，请恢复 ArchiveDesk.exe 并把所在文件夹加入白名单。\n诊断信息：\n"
                + where,
                "档序 ArchiveDesk",
                16,
            )
        else:
            raise
