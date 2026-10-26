"""Public stand-ins for the private template and scan that are not in the repo.

The example workbook is built with openpyxl. The scan is drawn with Pillow and a
CJK font installed on the machine (CI installs fonts-wqy-microhei). Neither file
contains real archive material.
"""

import tempfile
from pathlib import Path

# Public stand-in for the private templates/standard_template.xlsx.
# Dropdown units are fake. Column letters used by older export tests:
# D 题名, F 文件日期, K 密级, S 页数, T 正本数量.
PIECE_HEADERS = [
    "电子文件关联项",
    "归档单位(系统生成)",
    "临时序号",
    "题名",
    "责任者",
    "文件日期",
    "归档单位",
    "保管期限",
    "载体类型",
    "互见号",
    "密级",
    "保密期限",
    "提要",
    "主题词",
    "履行阶段",
    "报审序号",
    "历史档号",
    "框架代码",
    "页数",
    "正本数量",
    "数量",
    "年度",
    "文件编号",
    "备注",
    "电子文件大小",
    "电子文件数量",
    "专题标签",
    "来源",
    "模版类型",
    "职能标签",
]
VOLUME_HEADERS = [
    "电子文件关联项",
    "序号",
    "归档单位(系统生成)",
    "临时序号",
    "题名",
    "归档单位",
    "保管期限",
    "载体类型",
    "密级",
    "保密期限",
    "起日期",
    "提要",
    "止日期",
    "件数",
    "立卷单位",
    "履行阶段",
    "报审序号",
    "历史档号",
    "框架代码",
    "页数",
    "正本数量",
    "数量",
    "年度",
    "备注",
    "电子文件大小",
    "电子文件数量",
    "专题标签",
    "来源",
]
INNER_HEADERS = [
    "电子文件关联项",
    "卷序号",
    "归档单位(系统生成)",
    "临时序号",
    "题名",
    "责任者",
    "文件日期",
    "保管期限",
    "载体类型",
    "密级",
    "保密期限",
    "履行阶段",
    "报审序号",
    "历史档号",
    "框架代码",
    "数量",
    "年度",
    "文件编号",
    "页号",
    "备注",
    "电子文件大小",
    "电子文件数量",
    "来源",
    "职能标签",
]
CATALOG_HEADERS = PIECE_HEADERS

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


def fake_units():
    """Sixty placeholder units. These are not real organization names."""
    names = ["示例单位A", "示例单位B"]
    names.extend(f"示例单位{index:02d}" for index in range(3, 61))
    return names


def _write_template(path):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from openpyxl.workbook.defined_name import DefinedName
    from openpyxl.worksheet.datavalidation import DataValidation

    if (
        len(PIECE_HEADERS) != 30
        or len(VOLUME_HEADERS) != 28
        or len(INNER_HEADERS) != 24
    ):
        raise RuntimeError("示例模板表头数量与标准结构不一致")
    units = fake_units()
    lists = {
        "归档单位(系统生成)": ("OUID", "归档单位(系统生成)", units),
        "归档单位": ("FilingUnit", "归档单位", units),
        "保管期限": ("RetentionPeriod", "保管期限", ["永久", "30年", "10年"]),
        "载体类型": (
            "Media",
            "载体类型",
            [
                "纸质",
                "照片",
                "磁盘",
                "磁带",
                "光盘",
                "底图",
                "岩心",
                "岩屑",
                "其他",
                "电子",
                "胶片",
            ],
        ),
        "密级": (
            "SecurityClassification",
            "密级",
            [
                "无密级",
                "油商密★",
                "油商密★★",
                "普通商密",
                "内部资料",
                "石油内部",
                "石油商密",
                "非涉密",
            ],
        ),
        "保密期限": ("SecrecyTerm", "保密期限", ["示例期限A", "示例期限B"]),
        "专题标签": ("Property60", "专题标签", ["示例标签A", "示例标签B"]),
        "模版类型": ("Property49", "模版类型", ["收文", "发文"]),
    }
    decimals = {
        "临时序号",
        "页数",
        "正本数量",
        "数量",
        "电子文件大小",
        "电子文件数量",
        "件数",
    }
    dates = {"文件日期", "起日期", "止日期"}
    wb = Workbook()

    def add_catalog(ws, headers):
        header_font = Font(name="Calibri", bold=True, size=11)
        for col, header in enumerate(headers, 1):
            cell = ws.cell(1, col, header)
            cell.font = header_font
            letter = get_column_letter(col)
            ws.column_dimensions[letter].width = 18
            lock = DataValidation(
                type="list", formula1='"' + header + '"', allow_blank=True
            )
            lock.add(f"{letter}1")
            ws.add_data_validation(lock)
            span = f"{letter}2:{letter}100001"
            if header in lists:
                dv = DataValidation(
                    type="list", formula1="=" + lists[header][0], allow_blank=True
                )
            elif header in decimals:
                dv = DataValidation(type="decimal", allow_blank=True)
            elif header in dates:
                dv = DataValidation(type="date", allow_blank=True)
            elif header == "年度":
                dv = DataValidation(
                    type="whole",
                    operator="greaterThanOrEqual",
                    formula1="1900",
                    allow_blank=True,
                )
            else:
                continue
            dv.add(span)
            ws.add_data_validation(dv)
        _style_blank_row(ws, len(headers))

    piece = wb.active
    piece.title = "管理类_件"
    add_catalog(piece, PIECE_HEADERS)
    volume = wb.create_sheet("管理类_卷")
    add_catalog(volume, VOLUME_HEADERS)
    inner = wb.create_sheet("管理类_卷内件")
    add_catalog(inner, INNER_HEADERS)
    for defined_name, sheet_name, values in lists.values():
        sheet = wb.create_sheet(sheet_name)
        for index, value in enumerate(values, 1):
            sheet.cell(index, 1, value)
        end = len(values) if defined_name not in ("OUID", "FilingUnit") else 60
        wb.defined_names.add(
            DefinedName(name=defined_name, attr_text=f"'{sheet_name}'!$A$1:$A${end}")
        )
    for title, samples in (
        ("全宗号", ["示例全宗A", "示例全宗B"]),
        ("类别号", ["示例类别A", "示例类别B"]),
    ):
        sheet = wb.create_sheet(title)
        for index, value in enumerate(samples, 1):
            sheet.cell(index, 1, value)
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
