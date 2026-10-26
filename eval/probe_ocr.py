"""One OCR variant in a fresh process, so peak RSS is not mixed with other models.

Prints nothing but progress on stderr. Writes a JSON result for run_eval.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from extraction import extract_details
from ocr_common import FIELDS, bgr_to_pil, dump_rows, load_pages, make_engine, peak_rss_bytes, pil_to_bgr, rows_from_result, thumbnail, write_json
from preprocess import apply_variant


def recognize(engine, path: Path, preprocess: str):
    pages = load_pages(path)
    texts, scores, rows = [], [], []
    page_times = []
    for number, image in enumerate(pages, 1):
        array = pil_to_bgr(image)
        started = time.perf_counter()
        if preprocess != "none":
            array = apply_variant(array, preprocess)
        pre_s = time.perf_counter() - started
        prepared = thumbnail(bgr_to_pil(array))
        started = time.perf_counter()
        result, _ = engine(pil_to_bgr(prepared))
        engine_s = time.perf_counter() - started
        lines = [item[1] for item in (result or [])]
        texts.append(f"--- 第 {number} 页 ---\n" + "\n".join(lines))
        scores.extend(float(item[2]) for item in (result or []))
        rows.extend(rows_from_result(result, number, prepared.width, prepared.height))
        page_times.append({
            "page": number,
            "preprocess_s": round(pre_s, 4),
            "engine_s": round(engine_s, 4),
            "width": prepared.width,
            "height": prepared.height,
            "lines": len(lines),
        })
    text = "\n\n".join(texts)
    if not scores:
        values = {field: "" for field in FIELDS}
        warning = "未识别到文字"
    else:
        values, _evidence, warnings = extract_details(text, FIELDS, len(texts), rows=rows)
        warning = "；".join(dict.fromkeys(warnings))
    return {
        "values": values,
        "text": text,
        "rows": dump_rows(rows),
        "warning": warning,
        "page_times": page_times,
        "min_confidence": round(min(scores), 4) if scores else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=["v4", "v5-mobile", "v5-server"])
    parser.add_argument("--preprocess", default="none")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    truth = json.loads((args.corpus / "truth.json").read_text(encoding="utf-8"))
    documents = truth["documents"][: args.limit or None]
    started = time.perf_counter()
    engine = make_engine(args.model, threads=args.threads)
    load_s = time.perf_counter() - started
    rss_after_load = peak_rss_bytes()
    docs = []
    for spec in documents:
        print(f"{args.model}/{args.preprocess} {spec['file']}", file=sys.stderr, flush=True)
        try:
            recognized = recognize(engine, args.corpus / spec["file"], args.preprocess)
            recognized["error"] = ""
        except Exception as exc:
            recognized = {
                "values": {field: "" for field in FIELDS},
                "text": "",
                "rows": [],
                "warning": "",
                "page_times": [],
                "min_confidence": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
        recognized["id"] = spec["id"]
        recognized["file"] = spec["file"]
        docs.append(recognized)
    payload = {
        "model": args.model,
        "preprocess": args.preprocess,
        "threads": args.threads,
        "load_s": round(load_s, 4),
        "rss_after_load_bytes": rss_after_load,
        "peak_rss_bytes": peak_rss_bytes(),
        "documents": docs,
    }
    write_json(args.out, payload)
    print(json.dumps({"model": args.model, "preprocess": args.preprocess, "peak_rss_bytes": payload["peak_rss_bytes"], "docs": len(docs)}), flush=True)


if __name__ == "__main__":
    main()
