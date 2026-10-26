"""Run the synthetic benchmark. Does not change application behavior.

Accuracy, seconds per page and peak RSS come only from this run. Disk figures
come from measure_bundle.py (file sizes on this machine).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EVAL))

from extraction import extract_details
from generate_corpus import generate
from llm_adapter import (
    FieldRequest,
    LLMConfig,
    apply_grounding,
    default_registry,
    merge_fill_empty,
    normalize_accepted,
)
from measure_bundle import measure
from mock_openai_server import start
from ocr_common import CORPUS_DIR, FIELDS, load_pages
from rules_plus import extract_rules_plus

RESULTS = EVAL / "results"
RAW = RESULTS / "raw"
PROBES = [
    ("v4", "none"),
    ("v4", "deskew"),
    ("v4", "denoise"),
    ("v4", "binarize"),
    ("v4", "upscale"),
    ("v4", "red_channel"),
    ("v4", "red_seal"),
    ("v4", "combo"),
    ("v5-mobile", "none"),
    ("v5-server", "none"),
]


def environment() -> dict:
    cpu = Path("/proc/cpuinfo").read_text().splitlines()
    wanted = {}
    for line in cpu:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key in {"model name", "cpu family", "model", "stepping", "cpu cores"} and key not in wanted:
            wanted[key] = value
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith(("MemTotal", "MemAvailable")):
            mem[line.split(":")[0]] = line.split(":", 1)[1].strip()
    balloon = {}
    for line in Path("/proc/vmstat").read_text().splitlines():
        if line.startswith("balloon_"):
            key, value = line.split()
            balloon[key] = int(value)
    import cv2
    import numpy
    import onnxruntime
    return {
        "uname": os.uname().sysname + " " + os.uname().release + " " + os.uname().machine,
        "cpu": wanted,
        "logical_cpus": os.cpu_count(),
        "meminfo": mem,
        "balloon_pages_4k": balloon,
        "onnx_providers": onnxruntime.get_available_providers(),
        "versions": {
            "python": sys.version.split()[0],
            "onnxruntime": onnxruntime.__version__,
            "cv2": cv2.__version__,
            "numpy": numpy.__version__,
            "rapidocr_onnxruntime": "1.4.4",
        },
        "product_thread_cap": 2,
        "note": "计时在本虚拟机上串行进行，ONNX Runtime 只用 CPUExecutionProvider，intra/inter 线程数与 core.Processor 一样为 2。没有在 Windows 办公电脑上复测，因此不把秒数换算到办公电脑。",
    }


def run_probe(model: str, preprocess: str, threads: int = 2, limit: int = 0) -> dict:
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"{model}__{preprocess}__t{threads}__n{limit or 'all'}.json"
    cmd = [
        sys.executable, str(EVAL / "probe_ocr.py"),
        "--model", model, "--preprocess", preprocess,
        "--corpus", str(CORPUS_DIR), "--out", str(out), "--threads", str(threads),
    ]
    if limit:
        cmd.extend(["--limit", str(limit)])
    print("RUN", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd)
    if completed.returncode != 0 or not out.exists():
        return {"model": model, "preprocess": preprocess, "threads": threads, "error": f"probe exit {completed.returncode}"}
    return json.loads(out.read_text(encoding="utf-8"))


def page_times(payload: dict) -> dict:
    engines, pres = [], []
    for doc in payload.get("documents") or []:
        for page in doc.get("page_times") or []:
            engines.append(page["engine_s"])
            pres.append(page["preprocess_s"])

    def mean(values):
        return None if not values else round(sum(values) / len(values), 4)

    paired = [a + b for a, b in zip(engines, pres)]
    return {
        "pages_timed": len(engines),
        "engine_s_mean": mean(engines),
        "engine_s_first": None if not engines else round(engines[0], 4),
        "engine_s_mean_after_first": mean(engines[1:]),
        "engine_s_max": None if not engines else round(max(engines), 4),
        "preprocess_s_mean": mean(pres),
        "end_to_end_s_mean": mean(paired),
        "load_s": payload.get("load_s"),
        "rss_after_load_bytes": payload.get("rss_after_load_bytes"),
        "peak_rss_bytes": payload.get("peak_rss_bytes"),
        "errors": [f"{doc['id']}: {doc['error']}" for doc in payload.get("documents") or [] if doc.get("error")],
    }


def score(predictions: dict, truth: list) -> dict:
    correct = {field: 0 for field in FIELDS}
    by = {}
    exact = 0
    misses = []
    for spec in truth:
        pred = predictions.get(spec["id"]) or {field: "" for field in FIELDS}
        bucket = by.setdefault(spec["condition"], {"n": 0, "exact": 0, "fields": {field: 0 for field in FIELDS}})
        bucket["n"] += 1
        bad = []
        for field in FIELDS:
            if pred.get(field, "") == spec["fields"][field]:
                correct[field] += 1
                bucket["fields"][field] += 1
            else:
                bad.append(field)
        if not bad:
            exact += 1
            bucket["exact"] += 1
        else:
            misses.append({
                "id": spec["id"], "condition": spec["condition"], "miss": bad,
                "pred": {field: pred.get(field, "") for field in bad},
                "gt": {field: spec["fields"][field] for field in bad},
            })
    return {"n": len(truth), "exact": exact, "fields": correct, "by_condition": by, "misses": misses}


def values_of(payload: dict) -> dict:
    return {doc["id"]: doc.get("values") or {field: "" for field in FIELDS} for doc in payload.get("documents") or []}


def layout_values(spec: dict, rows: list) -> dict:
    from preprocess import seal_circles_pil_space
    from extraction import reading_rows
    from ocr_common import pil_to_bgr, thumbnail

    pages = load_pages(CORPUS_DIR / spec["file"])
    circles, sizes = {}, {}
    for number, page in enumerate(pages, 1):
        thumb = thumbnail(page)
        circles[number] = seal_circles_pil_space(pil_to_bgr(thumb))
        sizes[number] = (thumb.width, thumb.height)
    kept = []
    for row in rows:
        for cell in row.get("cells") or []:
            box = cell["box"]
            cx = sum(point[0] for point in box) / 4
            cy = sum(point[1] for point in box) / 4
            if any((cx - x) ** 2 + (cy - y) ** 2 <= radius * radius for x, y, radius in circles.get(cell["page"], [])):
                continue
            kept.append(cell)
    if not kept:
        return {field: "" for field in FIELDS}
    rebuilt = []
    for number in range(1, spec["pages"] + 1):
        width, height = sizes[number]
        for row in reading_rows([cell for cell in kept if cell["page"] == number]):
            rebuilt.append({**row, "page_width": width, "page_height": height})
    if not rebuilt:
        return {field: "" for field in FIELDS}
    values, _evidence, _warnings = extract_details("", FIELDS, spec["pages"], rows=rebuilt)
    return values


def png_pages(path: Path) -> list[bytes]:
    blobs = []
    for page in load_pages(path):
        buffer = io.BytesIO()
        page.save(buffer, format="PNG")
        blobs.append(buffer.getvalue())
    return blobs


def llm_benchmark(truth: list, baseline: dict) -> dict:
    """OpenAI-compatible mock. Not Qwen, not 昆仑, and it does not read truth.json."""
    key = "bench-key-not-a-secret"
    grounded, base_url = start("grounded", expect_key=key)
    try:
        provider = default_registry().create(LLMConfig(
            provider="openai_compatible", base_url=base_url, model="mock-stand-in",
            api_key=key, vision=True, timeout_s=60,
        ))
        fill, checked, additional = {}, {}, {}
        rejected_total = 0
        proposed_nonempty = 0
        kept = 0
        for spec in truth:
            doc = next(item for item in baseline["documents"] if item["id"] == spec["id"])
            result = provider.complete(FieldRequest(
                fields=FIELDS, ocr_text=doc.get("text") or "",
                page_images=png_pages(CORPUS_DIR / spec["file"]),
            ))
            accepted, rejected = apply_grounding(result.values, doc.get("text") or "", FIELDS)
            rejected_total += len(rejected)
            for name, raw in result.values.items():
                if isinstance(raw, str) and raw:
                    proposed_nonempty += 1
                    if raw in (doc.get("text") or ""):
                        kept += 1
            normalized = normalize_accepted(accepted)
            rules = doc.get("values") or {}
            fill[spec["id"]], _ = merge_fill_empty(rules, normalized, doc.get("text") or "", checked=False)
            checked[spec["id"]], _ = merge_fill_empty(rules, normalized, doc.get("text") or "", checked=True)
            extra = {name: value for name, value in accepted.items() if value}
            if doc.get("text"):
                merged, _evidence, _warnings = extract_details(
                    doc["text"], FIELDS, spec["pages"], rows=doc.get("rows") or None, additional=extra,
                )
            else:
                merged = {field: "" for field in FIELDS}
            additional[spec["id"]] = merged
        stats = dict(grounded.stats)
    finally:
        grounded.shutdown()
    halluc, hall_url = start("hallucinate", expect_key=key)
    try:
        provider = default_registry().create(LLMConfig(
            provider="openai_compatible", base_url=hall_url, model="mock-stand-in",
            api_key=key, vision=False, timeout_s=60,
        ))
        planted = 0
        planted_rejected = 0
        for spec in truth:
            doc = next(item for item in baseline["documents"] if item["id"] == spec["id"])
            text = doc.get("text") or ""
            result = provider.complete(FieldRequest(fields=FIELDS, ocr_text=text))
            _accepted, rejected = apply_grounding(result.values, text, FIELDS)
            for name in ("题名", "文件日期"):
                raw = result.values.get(name, "")
                if raw and raw not in text:
                    planted += 1
                    if name in rejected:
                        planted_rejected += 1
        hall_stats = dict(halluc.stats)
    finally:
        halluc.shutdown()
    kunlun_error = ""
    try:
        default_registry().create(LLMConfig(provider="kunlun")).complete(FieldRequest(fields=FIELDS, ocr_text="x"))
    except Exception as exc:
        kunlun_error = str(exc)
    return {
        "what_was_mocked": "本机 OpenAI 兼容 HTTP 替身（eval/mock_openai_server.py）。它只从请求里的 OCR 原文抄子串，不读标准答案，不是视觉大模型，也不是昆仑大模型。vision=true 时客户端会把原页 PNG 放进 image_url，替身解码图片只为了证明收到的是图像。",
        "mock_grounded_stats": stats,
        "mock_hallucinate_stats": hall_stats,
        "grounded_nonempty_proposals": proposed_nonempty,
        "grounded_proposals_literal_in_ocr": kept,
        "hallucinated_planted_values": planted,
        "hallucinated_planted_rejected": planted_rejected,
        "kunlun_call": kunlun_error,
        "scores": {
            "llm_mock_fill_empty": score(fill, truth),
            "llm_mock_fill_empty_checked": score(checked, truth),
            "llm_mock_as_current_additional": score(additional, truth),
        },
    }


def printed_page_diagnostic(truth: list, baseline: dict) -> dict:
    differ = 0
    found = 0
    for spec in truth:
        printed = spec["render"]["printed_pages"]
        if printed == spec["pages"]:
            continue
        differ += 1
        doc = next(item for item in baseline["documents"] if item["id"] == spec["id"])
        if f"共{printed}页" in (doc.get("text") or "").replace(" ", ""):
            found += 1
    return {
        "documents_whose_printed_count_differs_from_file_pages": differ,
        "of_those_ocr_text_contains_the_printed_共N页": found,
        "note": "产品的页数等于图像帧数，不读文内「共N页」。上面只统计 OCR 是否把印出来的页数读进了原文。",
    }


def ratio(correct: int, total: int):
    return None if not total else round(correct / total, 4)


def slim_score(block: dict) -> dict:
    total = block["n"]
    return {
        "n": total,
        "exact": block["exact"],
        "exact_rate": ratio(block["exact"], total),
        "fields": block["fields"],
        "field_rate": {field: ratio(block["fields"][field], total) for field in FIELDS},
        "by_condition": {
            name: {
                "n": item["n"],
                "exact": item["exact"],
                "exact_rate": ratio(item["exact"], item["n"]),
                "field_rate": {field: ratio(item["fields"][field], item["n"]) for field in FIELDS},
            }
            for name, item in block["by_condition"].items()
        },
        "misses": block["misses"],
    }


def markdown_table(rows: list[dict]) -> str:
    header = ["方案", "题名", "责任者", "文件日期", "文号", "密级", "页数", "整份全对", "引擎秒/页", "端到端秒/页", "峰值RSS"]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row[key]) for key in [
            "name", "题名", "责任者", "文件日期", "文号", "密级", "页数", "exact", "engine_s", "e2e_s", "rss",
        ]) + " |")
    return "\n".join(lines)


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    print("bundle measurement first, so it does not run during timed OCR", flush=True)
    try:
        bundle = measure()
    except Exception as exc:
        bundle = {"error": f"{type(exc).__name__}: {exc}"}
    (RESULTS / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    generate(CORPUS_DIR)
    truth_doc = json.loads((CORPUS_DIR / "truth.json").read_text(encoding="utf-8"))
    truth = truth_doc["documents"]
    probes = {}
    for model, preprocess in PROBES:
        probes[f"{model}/{preprocess}"] = run_probe(model, preprocess, threads=2)
    thread_sample = {}
    for model in ("v4", "v5-mobile", "v5-server"):
        thread_sample[model] = page_times(run_probe(model, "none", threads=4, limit=4))
    baseline = probes["v4/none"]
    scored = {}
    table_rows = []
    for name, payload in probes.items():
        if payload.get("error") and "documents" not in payload:
            scored[name] = {"error": payload["error"]}
            continue
        block = slim_score(score(values_of(payload), truth))
        timing = page_times(payload)
        scored[name] = {"score": block, "timing": timing}
        rates = block["field_rate"]
        rss = timing["peak_rss_bytes"]
        table_rows.append({
            "name": name,
            "题名": f"{block['fields']['题名']}/{block['n']}",
            "责任者": f"{block['fields']['责任者']}/{block['n']}",
            "文件日期": f"{block['fields']['文件日期']}/{block['n']}",
            "文号": f"{block['fields']['文号']}/{block['n']}",
            "密级": f"{block['fields']['密级']}/{block['n']}",
            "页数": f"{block['fields']['页数']}/{block['n']}",
            "exact": f"{block['exact']}/{block['n']}",
            "engine_s": timing["engine_s_mean"],
            "e2e_s": timing["end_to_end_s_mean"],
            "rss": None if rss is None else round(rss / (1024 * 1024), 1),
        })
    for model in ("v4", "v5-mobile", "v5-server"):
        payload = probes[f"{model}/none"]
        if "documents" not in payload:
            scored[f"{model}/rules_plus"] = {"error": payload.get("error", "missing probe")}
            continue
        preds = {}
        for spec in truth:
            doc = next(item for item in payload["documents"] if item["id"] == spec["id"])
            preds[spec["id"]] = extract_rules_plus(doc.get("text") or "", FIELDS, spec["pages"], rows=doc.get("rows"))
        block = slim_score(score(preds, truth))
        scored[f"{model}/rules_plus"] = {"score": block, "timing": {"note": "不再跑识别，只在该模型已经合并好的阅读行上重跑规则。"}}
        table_rows.append({
            "name": f"{model}/rules_plus",
            "题名": f"{block['fields']['题名']}/{block['n']}",
            "责任者": f"{block['fields']['责任者']}/{block['n']}",
            "文件日期": f"{block['fields']['文件日期']}/{block['n']}",
            "文号": f"{block['fields']['文号']}/{block['n']}",
            "密级": f"{block['fields']['密级']}/{block['n']}",
            "页数": f"{block['fields']['页数']}/{block['n']}",
            "exact": f"{block['exact']}/{block['n']}",
            "engine_s": "同模型",
            "e2e_s": "同模型",
            "rss": "同模型",
        })
        preds = {}
        for spec in truth:
            doc = next(item for item in payload["documents"] if item["id"] == spec["id"])
            preds[spec["id"]] = extract_rules_plus(
                doc.get("text") or "", FIELDS, spec["pages"], rows=doc.get("rows"), from_cells=True,
            )
        block = slim_score(score(preds, truth))
        scored[f"{model}/rules_plus_cells"] = {"score": block, "timing": {"note": "不再跑识别。规则按每个检测框单独成行，避免倾斜时标题和称呼被并进同一行。"}}
        table_rows.append({
            "name": f"{model}/rules_plus_cells",
            "题名": f"{block['fields']['题名']}/{block['n']}",
            "责任者": f"{block['fields']['责任者']}/{block['n']}",
            "文件日期": f"{block['fields']['文件日期']}/{block['n']}",
            "文号": f"{block['fields']['文号']}/{block['n']}",
            "密级": f"{block['fields']['密级']}/{block['n']}",
            "页数": f"{block['fields']['页数']}/{block['n']}",
            "exact": f"{block['exact']}/{block['n']}",
            "engine_s": "同模型",
            "e2e_s": "同模型",
            "rss": "同模型",
        })
    layout_preds = {}
    for spec in truth:
        doc = next(item for item in baseline["documents"] if item["id"] == spec["id"])
        layout_preds[spec["id"]] = layout_values(spec, doc.get("rows") or [])
    layout_block = slim_score(score(layout_preds, truth))
    scored["v4/layout_drop_seal"] = {"score": layout_block, "timing": {"note": "用 v4 的框，在缩略图上找红色圆章并丢掉落在圆内的框，再走现行规则。没有第二遍 OCR。"}}
    table_rows.append({
        "name": "v4/layout_drop_seal",
        "题名": f"{layout_block['fields']['题名']}/{layout_block['n']}",
        "责任者": f"{layout_block['fields']['责任者']}/{layout_block['n']}",
        "文件日期": f"{layout_block['fields']['文件日期']}/{layout_block['n']}",
        "文号": f"{layout_block['fields']['文号']}/{layout_block['n']}",
        "密级": f"{layout_block['fields']['密级']}/{layout_block['n']}",
        "页数": f"{layout_block['fields']['页数']}/{layout_block['n']}",
        "exact": f"{layout_block['exact']}/{layout_block['n']}",
        "engine_s": "同 v4/none",
        "e2e_s": "同 v4/none",
        "rss": "同 v4/none",
    })
    (RESULTS / "summary.partial.json").write_text(json.dumps({"environment": environment(), "variants": scored}, ensure_ascii=False), encoding="utf-8")
    print("llm mock", flush=True)
    try:
        llm = llm_benchmark(truth, baseline)
    except Exception as exc:
        llm = {"error": f"{type(exc).__name__}: {exc}"}
    for name, block in (llm.get("scores") or {}).items():
        slim = slim_score(block)
        llm["scores"][name] = slim
        table_rows.append({
            "name": name + "（模拟）",
            "题名": f"{slim['fields']['题名']}/{slim['n']}",
            "责任者": f"{slim['fields']['责任者']}/{slim['n']}",
            "文件日期": f"{slim['fields']['文件日期']}/{slim['n']}",
            "文号": f"{slim['fields']['文号']}/{slim['n']}",
            "密级": f"{slim['fields']['密级']}/{slim['n']}",
            "页数": f"{slim['fields']['页数']}/{slim['n']}",
            "exact": f"{slim['exact']}/{slim['n']}",
            "engine_s": "不跑大模型",
            "e2e_s": "不跑大模型",
            "rss": "不跑大模型",
        })
    summary = {
        "environment": environment(),
        "corpus": {
            "documents": len(truth),
            "page_images": sum(spec["pages"] for spec in truth),
            "conditions": {name: sum(1 for spec in truth if spec["condition"] == name) for name in dict.fromkeys(spec["condition"] for spec in truth)},
            "note": truth_doc["note"],
        },
        "variants": scored,
        "printed_page_diagnostic": printed_page_diagnostic(truth, baseline),
        "llm": llm,
        "threads_4_first_4_documents_only": {
            "note": "只跑语料前 4 份，用来看线程从 2 调到 4 的耗时。精度仍以线程 2 的全量结果为准。",
            "timing": thread_sample,
        },
        "bundle": bundle,
        "table_markdown": markdown_table(table_rows),
    }
    (RESULTS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "table.md").write_text(summary["table_markdown"] + "\n", encoding="utf-8")
    print(summary["table_markdown"])
    print("wrote", RESULTS / "summary.json")


if __name__ == "__main__":
    main()
