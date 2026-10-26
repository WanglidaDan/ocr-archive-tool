"""Synthetic 公文 images for the offline OCR benchmark.

Every organization name is fictional (示例…). This generator does not read or
embed real documents, templates, or personal data. Re-running it overwrites
``eval/corpus`` with the same pixels (fixed parameters, fixed noise seed).
"""
from __future__ import annotations

import datetime as dt
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ocr_common import CORPUS_DIR

FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
DPI = 180

ORGS = [
    "示例市档案管理局",
    "示例县人民政府办公室",
    "示例市卫生健康委员会",
    "示例区教育体育中心",
    "示例市档案局",
    "示例市人民政府",
]
PREFIX = {
    "示例市档案管理局": "示档发",
    "示例县人民政府办公室": "示政办发",
    "示例市卫生健康委员会": "示卫健发",
    "示例区教育体育中心": "示教体发",
    "示例市档案局": "示档局发",
    "示例市人民政府": "示政发",
}
TOPICS = [
    "开展档案数字化",
    "调整公文办理流程",
    "报送年度统计材料",
    "规范文件归档范围",
    "启用新的收文登记",
    "修订保密管理规定",
    "组织公文写作培训",
    "清理逾期未归档案",
    "公布值班安排",
    "实施电子文件移交",
    "核对案卷目录",
    "暂停纸质简报",
]
KINDS = ["通知", "通报", "报告", "请示", "批复", "函", "决定", "意见", "办法", "规定", "方案", "纪要", "总结", "公告"]
CONDITIONS = (
    ["clean"] * 5
    + ["red_header"] * 5
    + ["skew"] * 5
    + ["blur"] * 4
    + ["lowdpi"] * 4
    + ["red_seal"] * 5
    + ["photocopy"] * 4
    + ["hard"] * 4
)
SKEW = [2.0, -3.5, 5.0, -6.5, 8.0]
BLUR = [0.9, 1.3, 1.8, 2.4]
LOWDPI = [120, 100, 96, 72]
HARD = [
    {"skew": 5.0, "blur": 1.2, "photocopy": True, "seal": True, "dpi": None},
    {"skew": -7.0, "blur": 0.8, "photocopy": False, "seal": True, "dpi": None},
    {"skew": 3.0, "blur": 0.0, "photocopy": False, "seal": True, "dpi": 110},
    {"skew": 8.0, "blur": 1.6, "photocopy": True, "seal": True, "dpi": None},
]
MULTI_PAGE = {4, 9, 14, 27, 31, 35}
PRINTED_MISMATCH = {2, 16, 22, 33}
CN = "〇一二三四五六七八九"


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size, index=0)


def _page_size(dpi: int = DPI) -> tuple[int, int]:
    return int(round(210 / 25.4 * dpi)), int(round(297 / 25.4 * dpi))


def _cn_month(value: int) -> str:
    if value == 10:
        return "十"
    if value < 10:
        return CN[value]
    return "十" + CN[value - 10]


def _cn_day(value: int) -> str:
    if value < 10:
        return CN[value]
    if value == 10:
        return "十"
    if value < 20:
        return "十" + CN[value - 10]
    if value == 20:
        return "二十"
    if value == 30:
        return "三十"
    tens, ones = divmod(value, 10)
    return CN[tens] + "十" + (CN[ones] if ones else "")


def _date_of(index: int) -> dt.date:
    return dt.date(2018, 3, 1) + dt.timedelta(days=17 * index + (index % 3))


def content_for(index: int) -> dict:
    """Title, issuer and identifiers. Depends only on the document index."""
    org = ORGS[index % len(ORGS)]
    topic = TOPICS[index % len(TOPICS)]
    kind = KINDS[index % len(KINDS)]
    when = _date_of(index)
    if index % 13 == 0:
        title_mode = "points"
        title = f"{topic}工作要点"
        title_lines = [title]
    elif index % 11 == 0:
        title_mode = "no_about"
        title = f"{topic}的{kind}"
        title_lines = [title]
    elif index % 9 == 0:
        title_mode = "two_line"
        title_lines = [f"关于{topic}的", kind]
        title = "".join(title_lines)
    elif index % 4 == 0:
        title_mode = "about_org"
        title = f"{org}关于{topic}的{kind}"
        title_lines = [title]
    else:
        title_mode = "about"
        title = f"关于{topic}的{kind}"
        title_lines = [title]
    secrets = ["机密", "秘密", "内部", "公开", "", "绝密", "机密★10年", "秘密★5年", "内部资料"]
    secret_raw = secrets[index % len(secrets)]
    if index % 17 == 0 and secret_raw:
        secret_draw = secret_raw.split("★")[0] + "★10年  特急" if "★" not in secret_raw else secret_raw + "  特急"
        secret_value = secret_raw.split("★")[0]
        secret_style = "with_extra"
    else:
        secret_draw = secret_raw
        secret_value = secret_raw.split("★")[0] if secret_raw else ""
        # 内部资料 stays intact; split would yield 内部. Keep the full label.
        if secret_raw in {"内部资料", "石油内部", "石油商密", "普通商密", "油商密", "非涉密", "无密级"}:
            secret_value = secret_raw
        secret_style = "mark" if secret_raw else "none"
    if "★" in secret_raw and secret_style != "with_extra":
        secret_value = secret_raw.split("★")[0]
    return {
        "org": org,
        "title": title,
        "title_lines": title_lines,
        "title_mode": title_mode,
        "number": f"{PREFIX[org]}〔{when.year}〕{11 + index}号",
        "date": when.isoformat(),
        "date_cn": index % 2 == 0,
        "secret": secret_value,
        "secret_draw": secret_draw,
        "secret_style": secret_style,
        "decoy_date": "2023年5月6日",
    }


# Extra documents written as PDF. Indices continue after the 36 images so
# those pixels stay put. pdf_multi is a multi-page image PDF. pdf_scan is a
# multi-page or single-page PDF whose pages are JPEG scans (noise, skew).
PDF_PLAN = [
    {"index": 36, "condition": "pdf_multi", "pages": 2, "skew": 0, "blur": 0, "photocopy": False, "seal": False, "seal_target": "", "red": True, "dpi": None, "jpeg": False},
    {"index": 37, "condition": "pdf_multi", "pages": 2, "skew": 0, "blur": 0, "photocopy": False, "seal": False, "seal_target": "", "red": True, "dpi": None, "jpeg": False},
    {"index": 38, "condition": "pdf_multi", "pages": 2, "skew": 4.0, "blur": 0, "photocopy": False, "seal": False, "seal_target": "", "red": True, "dpi": None, "jpeg": False},
    {"index": 39, "condition": "pdf_multi", "pages": 2, "skew": 0, "blur": 0, "photocopy": False, "seal": False, "seal_target": "", "red": False, "dpi": None, "jpeg": False},
    {"index": 40, "condition": "pdf_scan", "pages": 1, "skew": 3.0, "blur": 0.8, "photocopy": True, "seal": False, "seal_target": "", "red": True, "dpi": None, "jpeg": True},
    {"index": 41, "condition": "pdf_scan", "pages": 1, "skew": -2.5, "blur": 1.2, "photocopy": True, "seal": True, "seal_target": "signature", "red": True, "dpi": None, "jpeg": True},
    {"index": 42, "condition": "pdf_scan", "pages": 2, "skew": 6.0, "blur": 0.6, "photocopy": True, "seal": True, "seal_target": "docno", "red": True, "dpi": None, "jpeg": True},
    {"index": 43, "condition": "pdf_scan", "pages": 2, "skew": 0, "blur": 1.5, "photocopy": True, "seal": False, "seal_target": "", "red": True, "dpi": 96, "jpeg": True},
    {"index": 44, "condition": "pdf_scan", "pages": 1, "skew": 8.0, "blur": 0.4, "photocopy": True, "seal": True, "seal_target": "signature", "red": True, "dpi": None, "jpeg": True},
    {"index": 45, "condition": "pdf_scan", "pages": 2, "skew": -5.0, "blur": 0.9, "photocopy": True, "seal": False, "seal_target": "", "red": True, "dpi": None, "jpeg": True},
    {"index": 46, "condition": "pdf_scan", "pages": 1, "skew": 2.0, "blur": 2.0, "photocopy": True, "seal": True, "seal_target": "docno", "red": True, "dpi": 110, "jpeg": True},
    {"index": 47, "condition": "pdf_scan", "pages": 2, "skew": 5.5, "blur": 1.1, "photocopy": True, "seal": True, "seal_target": "signature", "red": True, "dpi": None, "jpeg": True},
]


def build_specs() -> list[dict]:
    if len(CONDITIONS) != 36:
        raise RuntimeError(f"expected 36 documents, got {len(CONDITIONS)}")
    skew_i = blur_i = dpi_i = hard_i = 0
    specs = []
    for index, condition in enumerate(CONDITIONS):
        body = content_for(index)
        pages = 2 if index in MULTI_PAGE else 1
        printed = pages + 2 if index in PRINTED_MISMATCH else pages
        skew = blur = 0.0
        dpi = None
        photocopy = False
        seal = condition in {"red_seal"} or condition == "hard"
        red = condition in {"red_header", "red_seal", "hard"}
        if condition == "skew":
            skew = SKEW[skew_i]
            skew_i += 1
        elif condition == "blur":
            blur = BLUR[blur_i]
            blur_i += 1
        elif condition == "lowdpi":
            dpi = LOWDPI[dpi_i]
            dpi_i += 1
        elif condition == "photocopy":
            photocopy = True
        elif condition == "hard":
            item = HARD[hard_i]
            hard_i += 1
            skew = item["skew"]
            blur = item["blur"]
            photocopy = item["photocopy"]
            seal = item["seal"]
            dpi = item["dpi"]
            red = True
        seal_target = "docno" if seal and (condition == "red_seal" and index % 2 == 0 or condition == "hard" and hard_i == 4) else "signature"
        if not seal:
            seal_target = ""
        specs.append({
            "id": f"{index + 1:02d}",
            "condition": condition,
            **body,
            "pages": pages,
            "printed_pages": printed,
            "skew": skew,
            "blur": blur,
            "dpi": dpi,
            "photocopy": photocopy,
            "red_header": red,
            "seal": seal,
            "seal_target": seal_target,
            "jpeg": False,
        })
    return specs


def build_pdf_specs() -> list[dict]:
    specs = []
    for plan in PDF_PLAN:
        index = plan["index"]
        pages = plan["pages"]
        specs.append({
            "id": f"{index + 1:02d}",
            "condition": plan["condition"],
            **content_for(index),
            "pages": pages,
            "printed_pages": pages,
            "skew": plan["skew"],
            "blur": plan["blur"],
            "dpi": plan["dpi"],
            "photocopy": plan["photocopy"],
            "red_header": plan["red"],
            "seal": plan["seal"],
            "seal_target": plan["seal_target"] if plan["seal"] else "",
            "jpeg": plan["jpeg"],
        })
    return specs


def _star(cx, cy, radius) -> list[tuple[float, float]]:
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        arm = radius if i % 2 == 0 else radius * 0.4
        points.append((cx + arm * math.cos(angle), cy + arm * math.sin(angle)))
    return points


def _paint_seal(image: Image.Image, center, label: str) -> Image.Image:
    cx, cy = center
    radius = 132
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    red = (185, 16, 16, 185)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=red, width=7)
    inner = radius - 12
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), outline=red, width=3)
    draw.polygon(_star(cx, cy - 16, 46), fill=(185, 16, 16, 160))
    font = _font(22)
    bbox = font.getbbox(label)
    width = bbox[2] - bbox[0]
    draw.text((cx - width / 2, cy + 36), label, font=font, fill=(175, 0, 0, 190))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _draw_page(spec: dict, page_no: int, fonts) -> tuple[Image.Image, dict]:
    width, height = _page_size()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    anchors = {}
    if spec["secret_draw"] and page_no == 1:
        draw.text((90, 48), spec["secret_draw"], font=fonts["small"], fill=(20, 20, 20))
    y = 130
    if page_no == 1:
        header = spec["org"] + "文件"
        color = (190, 16, 16) if spec["red_header"] else (10, 10, 10)
        bbox = fonts["header"].getbbox(header)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), header, font=fonts["header"], fill=color)
        y += 78
        if spec["red_header"]:
            draw.line((160, y, width - 160, y), fill=(190, 16, 16), width=4)
            draw.line((160, y + 8, width - 160, y + 8), fill=(190, 16, 16), width=1)
            y += 24
        number = spec["number"]
        bbox = fonts["body"].getbbox(number)
        x = (width - (bbox[2] - bbox[0])) // 2
        number_y = y
        draw.text((x, number_y), number, font=fonts["body"], fill=(10, 10, 10))
        anchors["docno"] = (width // 2, number_y + 18)
        y += 70
        for line in spec["title_lines"]:
            bbox = fonts["title"].getbbox(line)
            x = (width - (bbox[2] - bbox[0])) // 2
            draw.text((x, y), line, font=fonts["title"], fill=(10, 10, 10))
            y += 64
        y += 20
    else:
        y = 140
        draw.text((120, y), "（续页）", font=fonts["body"], fill=(10, 10, 10))
        y += 70
    draw.text((120, y), "各有关单位：", font=fonts["body"], fill=(10, 10, 10))
    y += 56
    paragraphs = [
        f"为落实{spec['title']}有关安排，现将事项通知如下。",
        f"请于{spec['decoy_date']}前将材料报示例市实验学校汇总。",
        "联系时请核对文号与题名，正文提及的日期不是成文日期。",
        "此件由发文机关负责解释，抄送范围以正式印发稿为准。",
    ]
    if page_no == 2:
        paragraphs = paragraphs[2:]
    for paragraph in paragraphs:
        draw.text((120, y), paragraph, font=fonts["body"], fill=(10, 10, 10))
        y += 52
    if page_no == spec["pages"]:
        when = dt.date.fromisoformat(spec["date"])
        if spec["date_cn"]:
            date_text = f"{''.join(CN[int(ch)] for ch in str(when.year))}年{_cn_month(when.month)}月{_cn_day(when.day)}日"
        else:
            date_text = f"{when.year}年{when.month}月{when.day}日"
        org_bbox = fonts["body"].getbbox(spec["org"])
        org_w = org_bbox[2] - org_bbox[0]
        org_x = width - 140 - org_w
        org_y = height - 340
        draw.text((org_x, org_y), spec["org"], font=fonts["body"], fill=(10, 10, 10))
        date_bbox = fonts["body"].getbbox(date_text)
        date_w = date_bbox[2] - date_bbox[0]
        date_x = width - 140 - date_w
        date_y = org_y + 58
        draw.text((date_x, date_y), date_text, font=fonts["body"], fill=(10, 10, 10))
        anchors["signature"] = ((org_x + width - 140) // 2, org_y + 40)
    footer = f"共{spec['printed_pages']}页  第{page_no}页"
    bbox = fonts["small"].getbbox(footer)
    draw.text(((width - (bbox[2] - bbox[0])) // 2, height - 80), footer, font=fonts["small"], fill=(30, 30, 30))
    if spec["seal"] and spec["seal_target"] in anchors and (page_no == spec["pages"] or spec["seal_target"] == "docno" and page_no == 1):
        image = _paint_seal(image, anchors[spec["seal_target"]], spec["org"])
    return image, anchors


def _degrade(image: Image.Image, spec: dict, index: int) -> Image.Image:
    if spec["skew"]:
        image = image.rotate(spec["skew"], expand=True, fillcolor="white", resample=Image.Resampling.BICUBIC)
    if spec["blur"]:
        image = image.filter(ImageFilter.GaussianBlur(radius=spec["blur"]))
    if spec["dpi"]:
        scale = spec["dpi"] / DPI
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)
    if spec["photocopy"]:
        rng = np.random.default_rng(20260326 + index)
        array = np.asarray(image).astype(np.float32)
        gray = array.mean(axis=2, keepdims=True)
        array = np.repeat(gray, 3, axis=2)
        height, width = array.shape[:2]
        light = np.linspace(0.82, 1.0, height)[:, None] * np.linspace(0.9, 1.0, width)[None, :]
        array *= light[..., None]
        array += rng.normal(0, 14, array.shape)
        array = np.clip(array, 0, 255).astype(np.uint8)
        image = Image.fromarray(array)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=36)
        buffer.seek(0)
        image = Image.open(buffer).convert("RGB")
    return image


def _fonts():
    return {"header": _font(54), "title": _font(42), "body": _font(32), "small": _font(26)}


def _frames(spec: dict, fonts, index: int) -> list[Image.Image]:
    frames = []
    for page_no in range(1, spec["pages"] + 1):
        frame, _ = _draw_page(spec, page_no, fonts)
        frames.append(_degrade(frame, spec, index))
    return frames


def _record(spec: dict, filename: str) -> dict:
    return {
        "id": spec["id"],
        "file": filename,
        "condition": spec["condition"],
        "pages": spec["pages"],
        "fields": {
            "题名": spec["title"],
            "责任者": spec["org"],
            "文件日期": spec["date"],
            "文号": spec["number"],
            "密级": spec["secret"],
            "页数": str(spec["pages"]),
        },
        "render": {
            "title_mode": spec["title_mode"],
            "date_cn": spec["date_cn"],
            "secret_draw": spec["secret_draw"],
            "secret_style": spec["secret_style"],
            "printed_pages": spec["printed_pages"],
            "skew": spec["skew"],
            "blur": spec["blur"],
            "dpi": spec["dpi"],
            "photocopy": spec["photocopy"],
            "red_header": spec["red_header"],
            "seal": spec["seal"],
            "seal_target": spec["seal_target"],
            "decoy_date": spec["decoy_date"],
            "container": "pdf" if filename.lower().endswith(".pdf") else "image",
            "jpeg_pages": bool(spec.get("jpeg")),
        },
    }


def _save_pdf(path: Path, frames: list[Image.Image], jpeg: bool) -> None:
    import fitz

    document = fitz.open()
    try:
        for frame in frames:
            buffer = io.BytesIO()
            if jpeg:
                frame.save(buffer, format="JPEG", quality=40)
            else:
                frame.save(buffer, format="PNG", optimize=True)
            page = document.new_page(width=frame.width * 72 / DPI, height=frame.height * 72 / DPI)
            page.insert_image(page.rect, stream=buffer.getvalue())
        document.save(path, deflate=True, garbage=4)
    finally:
        document.close()


def _pdf_documents(out_dir: Path, fonts) -> list[dict]:
    documents = []
    for spec in build_pdf_specs():
        frames = _frames(spec, fonts, int(spec["id"]) - 1)
        filename = f"{spec['id']}-{spec['condition']}.pdf"
        _save_pdf(out_dir / filename, frames, jpeg=bool(spec["jpeg"]))
        documents.append(_record(spec, filename))
    return documents


def _truth_payload(documents: list[dict]) -> dict:
    return {
        "note": "合成基准，机关名称均为虚构的「示例…」，不含真实公文、模板或个人信息。含图片、多页 TIFF、多页 PDF 和按扫描件制作的 PDF。",
        "font": FONT_PATH,
        "nominal_dpi": DPI,
        "documents": documents,
    }


def generate(out_dir: Path = CORPUS_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.iterdir():
        if stale.suffix.lower() in {".png", ".jpg", ".tif", ".tiff", ".pdf", ".json"}:
            stale.unlink()
    fonts = _fonts()
    documents = []
    for index, spec in enumerate(build_specs()):
        frames = _frames(spec, fonts, index)
        if spec["photocopy"] and spec["pages"] == 1:
            filename = f"{spec['id']}-{spec['condition']}.jpg"
            frames[0].save(out_dir / filename, format="JPEG", quality=36)
        elif spec["pages"] > 1:
            filename = f"{spec['id']}-{spec['condition']}.tif"
            frames[0].save(out_dir / filename, format="TIFF", save_all=True, append_images=frames[1:], compression="tiff_lzw")
        else:
            filename = f"{spec['id']}-{spec['condition']}.png"
            frames[0].save(out_dir / filename, format="PNG", optimize=True)
        documents.append(_record(spec, filename))
    documents.extend(_pdf_documents(out_dir, fonts))
    path = out_dir / "truth.json"
    path.write_text(json.dumps(_truth_payload(documents), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def append_pdfs(out_dir: Path = CORPUS_DIR) -> Path:
    """Add PDF documents without rewriting the existing image files."""
    import hashlib

    guard = out_dir / "01-clean.png"
    digest = hashlib.sha256(guard.read_bytes()).hexdigest()
    path = out_dir / "truth.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    kept = [doc for doc in payload["documents"] if not str(doc["file"]).lower().endswith(".pdf")]
    for stale in out_dir.glob("*.pdf"):
        stale.unlink()
    kept.extend(_pdf_documents(out_dir, _fonts()))
    path.write_text(json.dumps(_truth_payload(kept), ensure_ascii=False, indent=2), encoding="utf-8")
    if hashlib.sha256(guard.read_bytes()).hexdigest() != digest:
        raise RuntimeError("01-clean.png changed while writing PDFs")
    return path


if __name__ == "__main__":
    import sys

    target = append_pdfs() if len(sys.argv) > 1 and sys.argv[1] == "append-pdfs" else generate()
    data = json.loads(target.read_text(encoding="utf-8"))
    print(f"wrote {len(data['documents'])} documents to {target.parent}")
