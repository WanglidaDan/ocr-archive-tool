"""Remove unused files from a PyInstaller folder without touching OCR models.

UPX is not used. Qt and onnxruntime DLLs stay uncompressed.
"""

from pathlib import Path

KEEP_ONNX = {
    "ch_pp-ocrv4_det_infer.onnx",
    "ch_pp-ocrv4_rec_infer.onnx",
    "ch_ppocr_mobile_v2.0_cls_infer.onnx",
}
QT_EXES = {
    "qmlls.exe",
    "qmlformat.exe",
    "assistant.exe",
    "linguist.exe",
    "designer.exe",
    "uic.exe",
    "lupdate.exe",
    "lrelease.exe",
    "qmltyperegistrar.exe",
    "qmlimportscanner.exe",
    "rcc.exe",
}
QT_PREFIXES = (
    "qt6quick",
    "qtquick",
    "qt6qml",
    "qtqml",
    "qt6designer",
    "qtdesigner",
    "qt6labs",
    "qt6help",
    "qthelp",
    "qt6uitools",
    "qtuitools",
    "qt6test",
    "qttest",
    "qt6dbus",
    "qtdbus",
    "qt6sql",
    "qtsql",
    "qt6printsupport",
    "qtprintsupport",
    "qt6xml",
    "qtxml",
    "qt63d",
    "qt3d",
    "qt6multimedia",
    "qtmultimedia",
    "qt6webengine",
    "qtwebengine",
    "qt6pdf",
    "qtpdf",
    "qt6charts",
    "qtcharts",
    "qtdatavisualization",
    "qt6datavis",
    "qtgraphs",
    "qt6virtualkeyboard",
    "qtvirtualkeyboard",
    "qt6openglwidgets",
    "qtopenglwidgets",
    "qtexampleicons",
)
KEEP_TRANSLATION = "qtbase_zh_cn.qm"


def _qt_unused(rel, base):
    if base in QT_EXES or base == "opengl32sw.dll":
        return True
    if base.startswith(QT_PREFIXES):
        return True
    if base.endswith(".pyi") and ("pyside6" in rel or "shiboken" in rel):
        return True
    markers = (
        "/qml/",
        "/metatypes/",
        "/include/",
        "/typesystems/",
        "/glue/",
        "/plugins/sqldrivers/",
        "/plugins/qmltooling/",
        "/plugins/designer/",
    )
    if any(marker in rel for marker in markers):
        return True
    if "/translations/" in rel or rel.startswith("translations/"):
        return base != KEEP_TRANSLATION
    return False


def category(relative):
    """Return which trim step should delete this file, or None to keep it."""
    relative = Path(relative)
    rel = relative.as_posix().lower()
    base = relative.name.lower()
    if base.endswith(".onnx") and base not in KEEP_ONNX:
        return "ocr-models"
    if (
        "opencv_videoio_ffmpeg" in base
        or "haarcascade" in base
        or "/cv2/data/" in rel
        or rel.startswith("cv2/data/")
    ):
        return "opencv-unused"
    if base.endswith(".pyi") and ("/cv2/" in rel or rel.startswith("cv2/")):
        return "opencv-unused"
    parts = {part.lower() for part in relative.parts}
    if parts.intersection({"scipy", "sympy", "pandas", "mpmath"}):
        return "numpy-scipy-extra"
    if "/numpy/tests/" in rel or "/numpy/f2py/tests/" in rel:
        return "numpy-scipy-extra"
    if base.endswith(".pyi") and ("/numpy/" in rel or rel.startswith("numpy/")):
        return "numpy-scipy-extra"
    if any(
        marker in rel
        for marker in (
            "/onnxruntime/transformers/",
            "/onnxruntime/tools/",
            "/onnxruntime/quantization/",
        )
    ):
        return "numpy-scipy-extra"
    if _qt_unused(rel, base):
        return "qt-unused"
    return None


def iter_trim(dist):
    """Delete unused files one group at a time. Yields (step, removed_bytes)."""
    dist = Path(dist)
    groups = (
        "qt-unused",
        "ocr-models",
        "opencv-unused",
        "numpy-scipy-extra",
    )
    files = [path for path in dist.rglob("*") if path.is_file()]
    for name in groups:
        removed = 0
        for path in files:
            if not path.is_file():
                continue
            if category(path.relative_to(dist)) != name:
                continue
            removed += path.stat().st_size
            path.unlink()
        yield name, removed
