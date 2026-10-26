"""把本机标准模板放进基础包，再重新打成 zip。没有模板就报错退出。"""

import sys
import tempfile
import zipfile
from pathlib import Path

MESSAGE = (
    "没有找到标准模板，已停止。\n"
    "请准备本机的 standard_template.xlsx，然后执行：\n"
    "  python tools/inject_template.py <基础包.zip> <标准模板.xlsx> [输出.zip]\n"
    "模板只放在你的电脑上，不会写入仓库。"
)


def inject(package, template, output):
    package = Path(package)
    template = Path(template)
    output = Path(output)
    if not template.is_file():
        raise FileNotFoundError(MESSAGE)
    if not zipfile.is_zipfile(template):
        raise FileNotFoundError("模板不是有效的 xlsx：" + str(template))
    if not package.is_file() or not zipfile.is_zipfile(package):
        raise FileNotFoundError("找不到基础包 zip：" + str(package))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(package) as archive:
            archive.extractall(root)
        exe = next(root.rglob("ArchiveDesk.exe"), None)
        if exe is None:
            raise FileNotFoundError("基础包里没有 ArchiveDesk.exe。")
        destination = exe.parent / "templates" / "standard_template.xlsx"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(template.read_bytes())
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
    return output


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(MESSAGE, file=sys.stderr)
        return 1
    package, template = argv[0], argv[1]
    output = (
        argv[2] if len(argv) > 2 else str(Path(package).with_name("ArchiveDesk.zip"))
    )
    try:
        written = inject(package, template, output)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    print("已写入模板并重新打包：" + str(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
