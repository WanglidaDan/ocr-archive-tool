"""Measure portable-build disk use from real files. No estimates."""
from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ocr_common import MODEL_DIR, V4_CLS, V4_DET, V4_REC, ensure_v5_models

CACHE = Path("/tmp/archivedesk-bundle")
# Packages actually imported when RapidOCR runs a page. Declared-but-unused
# extras such as tqdm, six, sympy and coloredlogs are not included.
WIN_BINARY = [
    "onnxruntime==1.20.1",
    "numpy==1.26.4",
    "opencv-python==4.10.0.84",
    "Pillow==11.1.0",
    "shapely",
    "pyclipper",
    "PyYAML",
]
WIN_PURE = [
    "rapidocr_onnxruntime==1.4.4",
]
EMBED_URLS = [
    "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip",
    "https://www.python.org/ftp/python/3.11.11/python-3.11.11-embed-amd64.zip",
]


def tree_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def zip_bytes(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        files = archive.infolist()
        onnx = {Path(info.filename).name: info.file_size for info in files if info.filename.endswith(".onnx")}
        return {
            "zip_bytes": path.stat().st_size,
            "uncompressed_bytes": sum(info.file_size for info in files),
            "onnx_uncompressed_bytes": onnx,
        }


def linux_runtime() -> dict:
    import cv2
    import numpy
    import onnxruntime
    import rapidocr_onnxruntime
    from PIL import Image

    modules = {
        "onnxruntime": Path(onnxruntime.__file__).resolve().parent,
        "cv2": Path(cv2.__file__).resolve().parent,
        "numpy": Path(numpy.__file__).resolve().parent,
        "PIL": Path(Image.__file__).resolve().parent,
        "rapidocr_onnxruntime": Path(rapidocr_onnxruntime.__file__).resolve().parent,
    }
    sizes = {name: tree_bytes(path) for name, path in modules.items()}
    extra = {}
    site = Path(onnxruntime.__file__).resolve().parents[1]
    for name in ("pillow.libs", "numpy.libs", "opencv_python.libs", "cv2.libs"):
        candidate = site / name
        if candidate.exists():
            extra[name] = tree_bytes(candidate)
    return {
        "note": "本机 import 到的目录字节数（Linux）。OpenCV 是当前解释器实际加载的版本，不一定等于 requirements 里钉的 Windows wheel。",
        "versions": {
            "onnxruntime": onnxruntime.__version__,
            "cv2": cv2.__version__,
            "numpy": numpy.__version__,
            "rapidocr_onnxruntime": getattr(rapidocr_onnxruntime, "__version__", "1.4.4"),
        },
        "directories": sizes,
        "sibling_libs": extra,
        "sum_bytes": sum(sizes.values()) + sum(extra.values()),
    }


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def _pip_download(wheel_dir: Path, package: str, platform_args: list[str]) -> str:
    import subprocess
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "download", "-d", str(wheel_dir), "--no-deps", "--only-binary=:all:",
         *platform_args, package],
        check=False, text=True, capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-1500:])
    return completed.stdout[-500:]


def windows_artifacts() -> dict:
    import shutil
    wheel_dir = CACHE / "wheels"
    if wheel_dir.exists():
        shutil.rmtree(wheel_dir)
    wheel_dir.mkdir(parents=True)
    errors = []
    binary_args = ["--platform", "win_amd64", "--python-version", "311", "--implementation", "cp", "--abi", "cp311"]
    abi3_args = ["--platform", "win_amd64", "--python-version", "311", "--implementation", "cp", "--abi", "abi3"]
    for package in WIN_BINARY:
        try:
            _pip_download(wheel_dir, package, binary_args)
        except RuntimeError as exc:
            try:
                _pip_download(wheel_dir, package, abi3_args)
            except RuntimeError as second:
                errors.append(f"{package}: {exc} | abi3 retry: {second}")
    for package in WIN_PURE:
        try:
            _pip_download(wheel_dir, package, [])
        except RuntimeError as exc:
            errors.append(f"{package}: {exc}")
    wheels = {wheel.name: zip_bytes(wheel) for wheel in sorted(wheel_dir.glob("*.whl"))}
    embed = {"error": "not downloaded"}
    for url in EMBED_URLS:
        dest = CACHE / Path(url).name
        try:
            download(url, dest)
        except Exception as exc:
            embed = {"error": f"{url}: {exc}"}
            continue
        embed = {"url": url, "file": dest.name, **zip_bytes(dest)}
        break
    return {
        "note": "每个 wheel 用 pip download --no-deps 单独取 Windows amd64 / CPython 3.11 文件（纯 Python 包不限平台）。解压字节是 zip 内 file_size 之和。",
        "errors": errors,
        "wheels": wheels,
        "python_embed_amd64": embed,
    }


def scenarios(windows: dict) -> dict:
    ensure_v5_models()
    v5 = {
        "mobile_det": (MODEL_DIR / "ch_PP-OCRv5_det_mobile.onnx").stat().st_size,
        "mobile_rec": (MODEL_DIR / "ch_PP-OCRv5_rec_mobile.onnx").stat().st_size,
        "server_det": (MODEL_DIR / "ch_PP-OCRv5_det_server.onnx").stat().st_size,
        "server_rec": (MODEL_DIR / "ch_PP-OCRv5_rec_server.onnx").stat().st_size,
        "dict_not_used": (MODEL_DIR / "ppocrv5_dict.txt").stat().st_size,
    }
    installed_v4 = {"det": V4_DET.stat().st_size, "rec": V4_REC.stat().st_size, "cls": V4_CLS.stat().st_size}
    if windows.get("errors") or windows.get("error") or not isinstance(windows.get("wheels"), dict):
        return {
            "v5_model_bytes": v5,
            "installed_v4_bytes": installed_v4,
            "error": windows.get("error") or windows.get("errors") or "windows wheels unavailable",
        }
    wheel_sum = 0
    v4_in_wheel = {}
    counted = []
    skipped = []
    for name, info in windows["wheels"].items():
        if "uncompressed_bytes" not in info:
            return {"v5_model_bytes": v5, "installed_v4_bytes": installed_v4, "error": "incomplete wheels"}
        portable = ("win_amd64" in name) or ("none-any" in name)
        if not portable:
            skipped.append(name)
            continue
        counted.append(name)
        wheel_sum += info["uncompressed_bytes"]
        v4_in_wheel.update(info.get("onnx_uncompressed_bytes") or {})
    if skipped:
        return {
            "v5_model_bytes": v5,
            "installed_v4_bytes": installed_v4,
            "error": "refusing to add non-Windows wheels: " + ", ".join(skipped),
            "counted_wheels": counted,
        }
    embed = windows.get("python_embed_amd64") or {}
    embed_bytes = embed.get("uncompressed_bytes")
    base_deps = wheel_sum
    base = None if embed_bytes is None else embed_bytes + wheel_sum

    def pack(extra_models: int, drop_v4_rec_det: bool) -> dict:
        dropped = 0
        if drop_v4_rec_det:
            dropped = v4_in_wheel.get("ch_PP-OCRv4_det_infer.onnx", 0) + v4_in_wheel.get("ch_PP-OCRv4_rec_infer.onnx", 0)
        total_deps = base_deps - dropped + extra_models
        total = None if embed_bytes is None else embed_bytes + total_deps
        return {"deps_plus_models_bytes": total_deps, "with_python_embed_bytes": total, "dropped_v4_det_rec_bytes": dropped, "added_model_bytes": extra_models}

    mobile = v5["mobile_det"] + v5["mobile_rec"]
    server = v5["server_det"] + v5["server_rec"]
    return {
        "note": "相加的每一项都是本机 stat 或 zip 解压后 file_size，不是估算。cls 模型留在 rapidocr 包内，三种方案共用。v5 字典已嵌在 ONNX 里，ppocrv5_dict.txt 不计入捆绑体积。",
        "v5_model_bytes": v5,
        "installed_v4_bytes": installed_v4,
        "v4_onnx_inside_win_wheel": v4_in_wheel,
        "counted_wheels": counted,
        "python_embed_uncompressed_bytes": embed_bytes,
        "win_wheels_uncompressed_bytes": wheel_sum,
        "bundles": {
            "v4_current": pack(0, False),
            "v5_mobile_replacing_v4_det_rec": pack(mobile, True),
            "v5_server_replacing_v4_det_rec": pack(server, True),
            "v4_plus_optional_v5_mobile": pack(mobile, False),
            "v4_plus_optional_v5_server": pack(server, False),
            "v4_plus_both_v5": pack(mobile + server, False),
        },
    }


def measure() -> dict:
    windows = windows_artifacts()
    payload = {"linux_runtime_loaded_on_vm": linux_runtime(), "windows_portable_files": windows, "bundles": scenarios(windows)}
    return payload


if __name__ == "__main__":
    print(json.dumps(measure(), ensure_ascii=False, indent=2))
