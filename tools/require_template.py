"""Stop a package build when the private standard template is not on this machine."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = Path("templates") / "standard_template.xlsx"
MESSAGE = (
    "无法打包：缺少标准模板 templates/standard_template.xlsx。\n"
    "请把本机的标准模板放到该路径后再执行打包。此文件只保存在本机，不会提交到仓库。"
)


def require_standard_template(root=None):
    path = (Path(root) if root is not None else ROOT) / RELATIVE
    if path.is_file():
        return path
    raise FileNotFoundError(MESSAGE)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = argv[0] if argv else None
    try:
        require_standard_template(root)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    print("已找到标准模板，可以继续打包。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
