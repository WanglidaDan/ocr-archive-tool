"""Confirm a base-package zip has the VC++ DLLs and no template workbook."""

import json
import sys
import zipfile
from pathlib import Path

REQUIRED_DLLS = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
RUNTIME_PREFIXES = ("vcruntime", "msvcp", "concrt", "vcomp")


def inspect_zip(path):
    path = Path(path)
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise FileNotFoundError("找不到基础包 zip：" + str(path))
    with zipfile.ZipFile(path) as archive:
        names = [item.filename.replace("\\", "/") for item in archive.infolist()]
        uncompressed = sum(item.file_size for item in archive.infolist())
    xlsx = [name for name in names if name.lower().endswith(".xlsx")]
    dlls = {}
    runtime = []
    for name in names:
        base = name.rsplit("/", 1)[-1].lower()
        if base in REQUIRED_DLLS and base not in dlls:
            dlls[base] = name
        if base.endswith(".dll") and base.startswith(RUNTIME_PREFIXES):
            runtime.append(name)
    missing = [name for name in REQUIRED_DLLS if name not in dlls]
    return {
        "zip_bytes": path.stat().st_size,
        "uncompressed_bytes": uncompressed,
        "xlsx": xlsx,
        "required_dlls": dlls,
        "missing_dlls": missing,
        "runtime_dlls": runtime,
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("用法：python tools/verify_base_zip.py <基础包.zip>", file=sys.stderr)
        return 1
    info = inspect_zip(argv[0])
    sys.stdout.buffer.write(
        (json.dumps(info, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    if info["xlsx"]:
        print("基础包里有 xlsx，不能作为 CI 产物。", file=sys.stderr)
        return 1
    if info["missing_dlls"]:
        print(
            "基础包 zip 里缺少 VC++ 运行库：" + "、".join(info["missing_dlls"]),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
