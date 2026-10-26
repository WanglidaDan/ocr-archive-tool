"""Turn a PyInstaller onedir folder into the template-free base zip."""

import argparse
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
REQUIRED_DLLS = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
TEMPLATE_NOTE = "请将标准模板放在这里.txt"


def _dll_sources():
    found = []
    prefixes = [Path(sys.base_prefix), Path(sys.executable).resolve().parent]
    windir = os.environ.get("WINDIR")
    if windir:
        prefixes.append(Path(windir) / "System32")
    for prefix in prefixes:
        if prefix.is_dir():
            found.append(prefix)
    return found


def _copy_runtime_dlls(dist):
    copied = []
    missing = []
    for name in REQUIRED_DLLS:
        target = dist / name
        internal = dist / "_internal" / name
        if target.is_file() or internal.is_file():
            if target.is_file() and not internal.is_file():
                internal.parent.mkdir(parents=True, exist_ok=True)
                internal.write_bytes(target.read_bytes())
            if internal.is_file() and not target.is_file():
                target.write_bytes(internal.read_bytes())
            copied.append(name)
            continue
        source = next(
            (folder / name for folder in _dll_sources() if (folder / name).is_file()),
            None,
        )
        if source is None:
            missing.append(name)
            continue
        data = source.read_bytes()
        target.write_bytes(data)
        internal.parent.mkdir(parents=True, exist_ok=True)
        internal.write_bytes(data)
        copied.append(name)
    return copied, missing


def prepare_dist(dist, copy_dlls=True):
    dist = Path(dist)
    if not (dist / "ArchiveDesk.exe").is_file():
        raise SystemExit("打包目录里没有 ArchiveDesk.exe：" + str(dist))
    (dist / "Start.bat").write_bytes((PACKAGING / "Start.bat").read_bytes())
    (dist / "使用说明.txt").write_bytes((PACKAGING / "使用说明.txt").read_bytes())
    templates = dist / "templates"
    templates.mkdir(parents=True, exist_ok=True)
    note = templates / TEMPLATE_NOTE
    note.write_bytes((PACKAGING / "template-readme.txt").read_bytes())
    removed = []
    for path in dist.rglob("*.xlsx"):
        path.unlink()
        removed.append(str(path))
    if any(dist.rglob("*.xlsx")):
        raise SystemExit("基础包里仍有 xlsx，已停止。")
    dlls = []
    if copy_dlls:
        dlls, missing = _copy_runtime_dlls(dist)
        if missing:
            raise SystemExit("基础包缺少 VC++ 运行库 DLL：" + "、".join(missing))
    onnx = [path for path in dist.rglob("*.onnx")]
    if not onnx:
        raise SystemExit("基础包里没有识别模型（*.onnx）。")
    return {
        "dlls": dlls,
        "onnx": len(onnx),
        "removed_xlsx": removed,
        "template_note": str(note.relative_to(dist)),
    }


def make_zip(dist, zip_path):
    dist = Path(dist)
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(dist.rglob("*")):
            if path.is_file():
                archive.write(
                    path, (Path(dist.name) / path.relative_to(dist)).as_posix()
                )
    if any(name.lower().endswith(".xlsx") for name in archive_names(zip_path)):
        zip_path.unlink()
        raise SystemExit("基础包 zip 里出现了 xlsx，已删除该 zip。")
    return zip_path.stat().st_size


def archive_names(zip_path):
    with zipfile.ZipFile(zip_path) as archive:
        return archive.namelist()


def directory_size(dist):
    return sum(path.stat().st_size for path in Path(dist).rglob("*") if path.is_file())


def main(argv=None):
    parser = argparse.ArgumentParser(description="整理不含模板的 Windows 基础包")
    parser.add_argument("--dist", required=True)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--skip-dll-check", action="store_true")
    args = parser.parse_args(argv)
    dist = Path(args.dist)
    info = prepare_dist(dist, copy_dlls=not args.skip_dll_check)
    zip_path = Path(args.zip)
    zip_bytes = make_zip(dist, zip_path)
    unpacked = directory_size(dist)
    report = zip_path.with_name("package-report.txt")
    lines = [
        f"zip_bytes={zip_bytes}",
        f"unpacked_bytes={unpacked}",
        f"onnx={info['onnx']}",
        f"dlls={','.join(info['dlls'])}",
        f"template_note={info['template_note']}",
        "template_xlsx=0",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
