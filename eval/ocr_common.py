"""Shared OCR helpers for the offline evaluation.

This module is not imported by the application. Image loading and the
RapidOCR call mirror ``core.Processor.recognize`` (thumbnail, BGR, two
threads) so the baseline is the current product path.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = Path(__file__).resolve().parent
MODEL_DIR = EVAL_DIR / "models"
CORPUS_DIR = EVAL_DIR / "corpus"
FIELDS = ["题名", "责任者", "文件日期", "文号", "密级", "页数"]

# rapidocr_onnxruntime 1.4.4 ships these PP-OCRv4 mobile weights.
BUNDLED_DIR = Path(__import__("rapidocr_onnxruntime").__file__).resolve().parent / "models"
V4_DET = BUNDLED_DIR / "ch_PP-OCRv4_det_infer.onnx"
V4_REC = BUNDLED_DIR / "ch_PP-OCRv4_rec_infer.onnx"
V4_CLS = BUNDLED_DIR / "ch_ppocr_mobile_v2.0_cls_infer.onnx"

V5_FILES = {
    "ch_PP-OCRv5_det_mobile.onnx": (
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.0/onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx",
        "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae",
    ),
    "ch_PP-OCRv5_rec_mobile.onnx": (
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.0/onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx",
        "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5",
    ),
    "ch_PP-OCRv5_det_server.onnx": (
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.0/onnx/PP-OCRv5/det/ch_PP-OCRv5_det_server.onnx",
        "0f8846b1d4bba223a2a2f9d9b44022fbc22cc019051a602b41a7fda9667e4cad",
    ),
    "ch_PP-OCRv5_rec_server.onnx": (
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.0/onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_server.onnx",
        "e09385400eaaaef34ceff54aeb7c4f0f1fe014c27fa8b9905d4709b65746562a",
    ),
    "ppocrv5_dict.txt": (
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.0/paddle/PP-OCRv5/rec/ch_PP-OCRv5_rec_server/ppocrv5_dict.txt",
        "d1979e9f794c464c0d2e0b70a7fe14dd978e9dc644c0e71f14158cdf8342af1b",
    ),
}

# Same thread cap as core.Processor.
THREADS = 2


def ensure_v5_models() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in V5_FILES.items():
        path = MODEL_DIR / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        tmp = path.with_suffix(path.suffix + ".partial")
        urllib.request.urlretrieve(url, tmp)
        got = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if got != digest:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"{name} sha256 {got} != {digest}")
        tmp.replace(path)


def model_paths(kind: str) -> dict:
    """kind: v4 | v5-mobile | v5-server. Classification stays the bundled v4 cls."""
    if kind == "v4":
        return {"det": V4_DET, "rec": V4_REC, "cls": V4_CLS}
    ensure_v5_models()
    if kind == "v5-mobile":
        return {
            "det": MODEL_DIR / "ch_PP-OCRv5_det_mobile.onnx",
            "rec": MODEL_DIR / "ch_PP-OCRv5_rec_mobile.onnx",
            "cls": V4_CLS,
        }
    if kind == "v5-server":
        return {
            "det": MODEL_DIR / "ch_PP-OCRv5_det_server.onnx",
            "rec": MODEL_DIR / "ch_PP-OCRv5_rec_server.onnx",
            "cls": V4_CLS,
        }
    raise KeyError(kind)


def make_engine(kind: str, threads: int = THREADS):
    from rapidocr_onnxruntime import RapidOCR

    paths = model_paths(kind)
    # PP-OCRv5 recognition ONNX embeds its dictionary and expects height 48,
    # which is already RapidOCR 1.4.4's rec_img_shape. No separate dict file.
    return RapidOCR(
        det_model_path=str(paths["det"]),
        rec_model_path=str(paths["rec"]),
        cls_model_path=str(paths["cls"]),
        intra_op_num_threads=threads,
        inter_op_num_threads=threads,
    )


def load_pages(path: Path) -> list[Image.Image]:
    pages = []
    if path.suffix.lower() == ".pdf":
        import fitz

        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise ValueError("encrypted")
            for page in doc:
                scale = min(2.5, 2600 / max(page.rect.width, page.rect.height))
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB)
                pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        return pages
    with Image.open(path) as image:
        n = getattr(image, "n_frames", 1)
        for i in range(n):
            image.seek(i)
            pages.append(ImageOps.exif_transpose(image.copy()).convert("RGB"))
    return pages


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()


def bgr_to_pil(array: np.ndarray) -> Image.Image:
    return Image.fromarray(array[:, :, ::-1])


def thumbnail(image: Image.Image) -> Image.Image:
    image = image.copy()
    if image.width * image.height > 45_000_000:
        raise ValueError("page too large")
    image.thumbnail((2600, 3600))
    return image


def rows_from_result(result, page_no: int, width: int, height: int):
    from extraction import reading_rows

    items = [
        {
            "box": [[float(x), float(y)] for x, y in item[0]],
            "text": item[1],
            "confidence": float(item[2]),
            "page": page_no,
        }
        for item in (result or [])
    ]
    rows = []
    for row in reading_rows(items):
        rows.append({**row, "page_width": width, "page_height": height})
    return rows


def dump_rows(rows) -> list:
    out = []
    for row in rows:
        item = {
            "text": row["text"],
            "page": row["page"],
            "confidence": row["confidence"],
            "boxes": row["boxes"],
            "page_width": row.get("page_width"),
            "page_height": row.get("page_height"),
            "cells": [
                {
                    "text": cell["text"],
                    "confidence": cell["confidence"],
                    "box": cell["box"],
                    "page": cell["page"],
                }
                for cell in row.get("cells", [])
            ],
        }
        out.append(item)
    return out


def peak_rss_bytes() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) * 1024
    return 0


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
