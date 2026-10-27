"""Dump recognized fields for a folder of documents. Used to compare two builds."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalog_defaults import DEFAULT_SHEET
from core import SUPPORTED, Processor
from template_io import inspect_template


def documents(folder):
    folder = Path(folder)
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED
    )


def field_map(folder, template):
    meta = inspect_template(template, DEFAULT_SHEET)
    processor = Processor()
    found = {}
    for path in documents(folder):
        result = processor.recognize(path, meta["headers"])
        found[path.name] = result.get("values") or {}
    return found


def compare_fields(actual, expected):
    names = sorted(set(actual) | set(expected))
    return [name for name in names if actual.get(name) != expected.get(name)]


def main(argv=None):
    parser = argparse.ArgumentParser(description="导出识别字段，供精简前后对照")
    parser.add_argument("--input", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    found = field_map(args.input, args.template)
    Path(args.output).write_text(
        json.dumps(found, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"fields={len(found)}")
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
