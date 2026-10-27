#!/bin/sh
# 在 Linux 上用 wine 调用 Inno Setup 的 ISCC.exe，把基础包打成 setup.exe。
# 用法：tools/build_installer_local.sh <解压后的基础包目录> <标准模板.xlsx>
# 基础包目录里要有 ArchiveDesk.exe。模板会复制为该目录下的
# templates/standard_template.xlsx，然后打进这一份本地安装包。
# 没有模板就退出。标准模板不要放进仓库或 CI。
# CI 另用代码生成的假模板编译安装包，只为验证静默安装、启动和卸载。

set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
BASE=${1:-}
TEMPLATE=${2:-}
ISS="$ROOT/packaging/ArchiveDesk.iss"

if [ -z "$BASE" ] || [ -z "$TEMPLATE" ]; then
  echo "用法：tools/build_installer_local.sh <解压后的基础包目录> <标准模板.xlsx>" >&2
  echo "没有模板，已停止。请把本机标准模板的路径作为第二个参数。" >&2
  exit 1
fi

BASE=$(CDPATH= cd -- "$BASE" && pwd)
if [ ! -f "$BASE/ArchiveDesk.exe" ]; then
  echo "这个目录里没有 ArchiveDesk.exe：$BASE" >&2
  exit 1
fi
if [ ! -f "$TEMPLATE" ]; then
  echo "找不到标准模板：$TEMPLATE" >&2
  exit 1
fi

mkdir -p "$BASE/templates"
cp "$TEMPLATE" "$BASE/templates/standard_template.xlsx"

find_iscc() {
  if [ -n "${ISCC:-}" ] && [ -f "$ISCC" ]; then
    echo "$ISCC"
    return 0
  fi
  for candidate in \
    "$HOME/.wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
    "$HOME/.wine/drive_c/Program Files/Inno Setup 6/ISCC.exe" \
    "/opt/wine-staging/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe"
  do
    if [ -f "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if ! command -v wine >/dev/null 2>&1; then
  echo "本机没有 wine，无法调用 ISCC.exe。" >&2
  echo "请先安装 wine，并在 wine 里安装 Inno Setup 6。也可以设置 ISCC 指向 ISCC.exe。" >&2
  exit 1
fi

if ! ISCC_PATH=$(find_iscc); then
  echo "wine 里没有找到 Inno Setup 的 ISCC.exe。" >&2
  echo "请安装 Inno Setup 6，或把 ISCC 环境变量指到 ISCC.exe 的完整路径。" >&2
  exit 1
fi

OUT="$ROOT/dist"
mkdir -p "$OUT"
WIN_ISS=$(winepath -w "$ISS")
WIN_BASE=$(winepath -w "$BASE")
WIN_OUT=$(winepath -w "$OUT")

echo "正在编译安装包。模板已放入基础包目录，这一份 setup.exe 会带上模板。"
WINEDEBUG=-all wine "$ISCC_PATH" "$WIN_ISS" "/DDistDir=$WIN_BASE" "/DOutputDir=$WIN_OUT"
echo "完成。请查看 $OUT/ArchiveDesk-setup.exe"
