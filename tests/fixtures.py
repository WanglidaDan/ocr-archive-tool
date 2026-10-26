"""Public stand-ins for the private template and scan that are not in the repo.

The example workbook is built with openpyxl. The scan is drawn with Pillow and a
CJK font installed on the machine (CI installs fonts-wqy-microhei). Neither file
contains real archive material.
"""

import tempfile
from pathlib import Path

# Column letters are part of the export tests: D 题名, F 文件日期, K 密级,
# S 页数, T 正本数量. 保管期限 must offer 永久. 责任单位 is a dropdown the
# linkage and UI code look up by header name.
CATALOG_HEADERS = [
    "序号",
    "档号",
    "文件编号",
    "题名",
    "责任者",
    "文件日期",
    "年度",
    "保管期限",
    "分类号",
    "机构或问题",
    "密级",
    "归档单位",
    "责任单位",
    "载体类型",
    "稿本",
    "附件说明",
    "备注",
    "盒号",
    "页数",
    "正本数量",
    "副本数量",
    "电子文件数量",
    "电子文件大小",
    "存放位置",
    "参见号",
    "互见号",
    "著录人",
    "著录日期",
    "检查人",
    "全宗号",
]

# 2000-01-01 and 2050-12-31 in the Windows workbook epoch. 2026-10-26 is inside
# this range; 2099-01-01 is not.
DATE_MIN = "36526"
DATE_MAX = "55153"

CJK_FONTS = [
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyh.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
]

_DIR = None
_TEMPLATE = None
_SCAN = None


def _fixture_dir():
    global _DIR
    if _DIR is None:
        _DIR = Path(tempfile.mkdtemp(prefix="archivedesk-fixtures-"))
    return _DIR


def cjk_font_path():
    found = next((path for path in CJK_FONTS if path.is_file()), None)
    if found is None:
        searched = ", ".join(str(path) for path in CJK_FONTS)
        raise FileNotFoundError(
            "绘制测试扫描件需要中文字体。请安装 fonts-wqy-microhei，"
            "或提供 Noto Sans CJK / 微软雅黑。已查找：" + searched
        )
    return found


def _style_blank_row(ws, width):
    """Put an empty, styled row 2 in the xlsx so export can patch existing cells."""
    from openpyxl.styles import Font

    for col in range(1, width + 1):
        cell = ws.cell(2, col, None)
        cell.font = Font(name="Calibri", size=11)


def _add_list(ws, cell_range, options):
    from openpyxl.worksheet.datavalidation import DataValidation

    dv = DataValidation(
        type="list", formula1='"' + ",".join(options) + '"', allow_blank=True
    )
    dv.add(cell_range)
    ws.add_data_validation(dv)


def _write_template(path):
    from openpyxl import Workbook
    from openpyxl.worksheet.datavalidation import DataValidation

    if len(CATALOG_HEADERS) != 30 or len(set(CATALOG_HEADERS)) != 30:
        raise RuntimeError("示例模板表头必须是 30 个互不相同的字段")
    wb = Workbook()
    ws = wb.active
    ws.title = "管理类_件"
    for col, header in enumerate(CATALOG_HEADERS, 1):
        ws.cell(1, col, header)
    _style_blank_row(ws, len(CATALOG_HEADERS))
    _add_list(ws, "H2:H500", ["永久", "30年", "10年"])
    _add_list(
        ws,
        "K2:K500",
        ["非涉密", "无密级", "内部", "内部资料", "普通商密", "秘密", "机密", "绝密"],
    )
    _add_list(ws, "L2:L500", ["公司-机关-档案馆", "公司-办公室"])
    _add_list(ws, "M2:M500", ["档案馆", "办公室"])
    dates = DataValidation(
        type="date",
        operator="between",
        formula1=DATE_MIN,
        formula2=DATE_MAX,
        allow_blank=True,
    )
    dates.add("F2:F500")
    ws.add_data_validation(dates)
    volume = wb.create_sheet("管理类_卷")
    for col in range(1, 29):
        volume.cell(1, col, f"卷字段{col:02d}")
    inner = wb.create_sheet("管理类_卷内件")
    for col in range(1, 25):
        inner.cell(1, col, f"卷内字段{col:02d}")
    wb.save(path)


def example_template():
    global _TEMPLATE
    if _TEMPLATE is None:
        path = _fixture_dir() / "standard_template.xlsx"
        _write_template(path)
        _TEMPLATE = path
    return _TEMPLATE


def example_scan():
    """Draw a synthetic scan whose OCR text includes 责任单位：档案馆."""
    global _SCAN
    if _SCAN is None:
        from PIL import Image, ImageDraw, ImageFont

        # Large, spaced lines. RapidOCR with WenQuanYi Micro Hei reads 责任单位 as 档案馆.
        font = ImageFont.truetype(str(cjk_font_path()), 72)
        lines = [
            "文件名称：档案归档通知",
            "文号：档发〔2026〕12号",
            "日期：2026年10月26日",
            "责任单位：档案馆",
        ]
        image = Image.new("RGB", (1800, 900), "white")
        draw = ImageDraw.Draw(image)
        y = 80
        for line in lines:
            draw.text((80, y), line, fill="black", font=font)
            y += 140
        path = _fixture_dir() / "sample_scan.png"
        image.save(path)
        _SCAN = path
    return _SCAN
