"""Bootstrap native Qt desktop with local startup diagnostics."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if sys.platform == "win32":
    _dll_handles = []
    for p in [ROOT / "runtime", ROOT / "runtime/Lib/site-packages/PySide6"]:
        if p.is_dir():
            _dll_handles.append(os.add_dll_directory(str(p)))
try:
    from app import main

    main()
except Exception:
    import traceback

    target = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchiveDesk"
    target.mkdir(parents=True, exist_ok=True)
    log = target / "startup-error.txt"
    log.write_text(traceback.format_exc(), encoding="utf-8")
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, "启动失败，诊断信息已保存至：\n" + str(log), "档序 ArchiveDesk", 16
        )
    else:
        raise
