"""Build a headless M1 batch: scanned, skewed, blurred, and multi-page PDFs.

The two extra files are an encrypted PDF and a corrupt PDF. Ground truth is the
text drawn on the page, after the same date normalization the app applies.
Nothing here is a real archive document.
"""

import io
import json
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from fixtures import cjk_font_path


CONTENT = [
    (
        "扫描001.pdf",
        ["扫描"],
        {"noise": 10, "jpeg": 70},
        1,
        "关于开展档案整理工作的通知",
        "档发〔2024〕15号",
        "2024年3月18日",
        "示例单位A",
        "非涉密",
        "1",
    ),
    (
        "扫描002.pdf",
        ["扫描"],
        {"noise": 12, "jpeg": 65},
        1,
        "关于调整档案保管期限的函",
        "档函〔2023〕8号",
        "2023年11月2日",
        "示例单位B",
        "普通商密",
        "1",
    ),
    (
        "倾斜001.pdf",
        ["扫描", "倾斜"],
        {"skew": 2.2, "noise": 8, "jpeg": 70},
        1,
        "关于印发档案整理办法的通知",
        "档发〔2022〕3号",
        "2022年1月9日",
        "示例单位A",
        "无密级",
        "1",
    ),
    (
        "倾斜002.pdf",
        ["扫描", "倾斜"],
        {"skew": -2.6, "noise": 8, "jpeg": 72},
        1,
        "关于报送档案目录的报告",
        "档发〔2025〕21号",
        "2025年6月30日",
        "示例单位B",
        "内部资料",
        "2",
    ),
    (
        "模糊001.pdf",
        ["扫描", "模糊"],
        {"blur": 0.9, "noise": 6, "jpeg": 60},
        1,
        "关于补充归档材料的函",
        "档函〔2021〕46号",
        "2021年12月1日",
        "示例单位A",
        "非涉密",
        "1",
    ),
    (
        "模糊002.pdf",
        ["扫描", "模糊"],
        {"blur": 1.4, "noise": 8, "jpeg": 55},
        1,
        "关于启用新档号的通知",
        "档发〔2020〕7号",
        "2020年5月16日",
        "示例单位B",
        "石油内部",
        "2",
    ),
    (
        "多页001.pdf",
        ["扫描", "多页"],
        {"noise": 8, "jpeg": 70},
        2,
        "关于年度归档工作的通知",
        "档发〔2019〕12号",
        "2019年8月8日",
        "示例单位A",
        "普通商密",
        "1",
    ),
    (
        "多页002.pdf",
        ["扫描", "多页"],
        {"noise": 8, "jpeg": 68},
        3,
        "关于移交档案的报告",
        "档函〔2018〕19号",
        "2018年4月23日",
        "示例单位B",
        "无密级",
        "1",
    ),
    (
        "倾斜多页001.pdf",
        ["扫描", "倾斜", "多页"],
        {"skew": 1.8, "noise": 8, "jpeg": 70},
        2,
        "关于核对归档清单的函",
        "档发〔2017〕5号",
        "2017年9月14日",
        "示例单位A",
        "非涉密",
        "1",
    ),
    (
        "模糊倾斜001.pdf",
        ["扫描", "模糊", "倾斜", "多页"],
        {"skew": 1.6, "blur": 0.8, "noise": 10, "jpeg": 58},
        2,
        "关于修订档案制度的通知",
        "档发〔2016〕28号",
        "2016年2月29日",
        "示例单位B",
        "内部资料",
        "2",
    ),
]


def _iso_date(text):
    year = int(text[:4])
    month = int(text.split("年", 1)[1].split("月", 1)[0])
    day = int(text.split("月", 1)[1].split("日", 1)[0])
    return f"{year:04d}-{month:02d}-{day:02d}"


def _page_lines(case, page_number):
    title, number, printed_date, unit, classification, copies = case[4:]
    if page_number == 1:
        return [
            classification,
            f"文件名称：{title}",
            f"文号：{number}",
            f"日期：{printed_date}",
            f"责任单位：{unit}",
            f"正本数量：{copies}",
        ]
    return [
        "续页说明材料",
        "此页没有新的著录字段",
        f"页码{page_number}",
    ]


def render_page(lines, seed, skew=0, blur=0, noise=0, jpeg=None):
    """Draw a paper page, then optionally add noise, blur, skew, and JPEG."""
    font = ImageFont.truetype(str(cjk_font_path()), 64)
    image = Image.new("RGB", (1800, 1100), (244, 240, 232))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 1783, 1083), outline=(186, 180, 166), width=3)
    y = 70
    for line in lines:
        draw.text((90, y), line, fill=(25, 25, 25), font=font)
        y += 120
    if noise:
        rng = np.random.default_rng(seed)
        pixels = np.asarray(image).astype(np.int16)
        pixels += rng.integers(-noise, noise + 1, size=pixels.shape, dtype=np.int16)
        image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB")
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(radius=blur))
    if skew:
        image = image.rotate(
            skew,
            expand=True,
            fillcolor=(244, 240, 232),
            resample=Image.Resampling.BICUBIC,
        )
    if jpeg:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=jpeg)
        image = Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")
    return image


def _write_pdf(path, images):
    document = fitz.open()
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page = document.new_page(width=image.width, height=image.height)
        page.insert_image(page.rect, stream=buffer.getvalue())
    document.save(path)
    document.close()


def _write_encrypted(path):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "encrypted")
    document.save(
        path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    document.close()


def case_records():
    """Return the batch description in import order, without writing files."""
    records = []
    for index, case in enumerate(CONTENT, 1):
        (
            filename,
            traits,
            _style,
            pages,
            title,
            number,
            printed,
            unit,
            classification,
            copies,
        ) = case
        iso = _iso_date(printed)
        records.append(
            {
                "filename": filename,
                "traits": list(traits),
                "pages": pages,
                "expect_failure": "",
                "fields": {
                    "题名": title,
                    "责任者": unit,
                    "文件日期": iso,
                    "文件编号": number,
                    "页数": str(pages),
                    "密级": classification,
                    "正本数量": copies,
                    "年度": iso[:4],
                    "归档单位": unit,
                    "归档单位(系统生成)": unit,
                    "保管期限": "30年",
                    "载体类型": "纸质",
                    "电子文件数量": "1",
                    "电子文件关联项": filename,
                    "临时序号": str(index),
                },
            }
        )
    # A corrupt file sits in the middle so a failure does not end the batch.
    records.insert(
        2,
        {
            "filename": "损坏.pdf",
            "traits": ["损坏"],
            "pages": 0,
            "expect_failure": "PDF无法读取",
            "fields": {},
        },
    )
    records.append(
        {
            "filename": "加密.pdf",
            "traits": ["加密"],
            "pages": 1,
            "expect_failure": "PDF已加密",
            "fields": {},
        }
    )
    for index, record in enumerate(records, 1):
        if record["fields"]:
            record["fields"]["临时序号"] = str(index)
    return records


def generate(folder):
    """Write the PDFs and ground_truth.json. Return the case records."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    records = case_records()
    by_name = {record["filename"]: record for record in records}
    for case in CONTENT:
        filename, _traits, style, pages, *_rest = case
        images = [
            render_page(
                _page_lines(case, page_number),
                seed=zlib.adler32(f"{filename}:{page_number}".encode("utf-8")),
                skew=style.get("skew", 0),
                blur=style.get("blur", 0),
                noise=style.get("noise", 0),
                jpeg=style.get("jpeg"),
            )
            for page_number in range(1, pages + 1)
        ]
        _write_pdf(folder / filename, images)
        by_name[filename]["bytes"] = (folder / filename).stat().st_size
        by_name[filename]["fields"]["电子文件大小"] = str(by_name[filename]["bytes"])
    _write_encrypted(folder / "加密.pdf")
    (folder / "损坏.pdf").write_bytes(b"this is not a pdf")
    payload = []
    for record in records:
        item = dict(record)
        item.pop("bytes", None)
        payload.append(item)
    (folder / "ground_truth.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return records


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "scan-set")
    written = generate(target)
    print(f"{len(written)} {target}")
