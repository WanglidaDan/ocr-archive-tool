"""Before/after accuracy of the app code path on one corpus.

Runs ``Processor.recognize(..., enhanced_rules=False)`` once per document
(current OCR and current rules), then ``assemble_fields(..., enhanced_rules=True)``
on the same text and rows. That second call is the post-step ``recognize``
uses when the setting is on. No second OCR pass.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EVAL))

from core import Processor, assemble_fields
from ocr_common import CORPUS_DIR, FIELDS
from run_eval import score, slim_score

RESULTS = EVAL / "results"


def main():
    truth_doc = json.loads((CORPUS_DIR / "truth.json").read_text(encoding="utf-8"))
    truth = truth_doc["documents"]
    processor = Processor()
    before, after = {}, {}
    engine_seconds = []
    documents = []
    wall_start = time.perf_counter()
    for spec in truth:
        path = CORPUS_DIR / spec["file"]
        started = time.perf_counter()
        result = processor.recognize(path, FIELDS, enhanced_rules=False)
        elapsed = time.perf_counter() - started
        engine_seconds.append(elapsed)
        improved, _evidence, _warnings = assemble_fields(
            result["text"], FIELDS, result["pages"], result.get("ocr_rows"), True,
        )
        before[spec["id"]] = result["values"]
        after[spec["id"]] = improved
        documents.append({
            "id": spec["id"],
            "file": spec["file"],
            "pages": result["pages"],
            "recognize_s": round(elapsed, 4),
            "before": result["values"],
            "after": improved,
        })
        print(f"{spec['id']} {spec['file']} {elapsed:.2f}s", flush=True)
    payload = {
        "note": "同一套 OCR 行。before 是 Processor.recognize(enhanced_rules=False) 的字段。after 是 assemble_fields(enhanced_rules=True)，与设置打开时 recognize 在规则阶段写入的字段相同。耗时含本进程里的 PDF 栅格化和识别，线程为应用内的 2。",
        "documents_n": len(truth),
        "page_images": sum(spec["pages"] for spec in truth),
        "wall_s": round(time.perf_counter() - wall_start, 4),
        "recognize_s_mean": round(sum(engine_seconds) / len(engine_seconds), 4),
        "before": slim_score(score(before, truth)),
        "after": slim_score(score(after, truth)),
        "documents": documents,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "before_after.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("before", payload["before"]["exact"], "/", payload["before"]["n"], payload["before"]["fields"])
    print("after", payload["after"]["exact"], "/", payload["after"]["n"], payload["after"]["fields"])
    print("wrote", out)


if __name__ == "__main__":
    main()
