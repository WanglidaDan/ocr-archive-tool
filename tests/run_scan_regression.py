"""Optional full raster scan regression, 12 images, without any network."""

import sys, json, socket
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Processor


def blocked(*args, **kwargs):
    raise RuntimeError("Network blocked during scan regression")


socket.socket.connect = blocked
socket.create_connection = blocked
folder = Path(__file__).parent / "scan_corpus"
processor = Processor()
failures = 0
for sample in json.loads((folder / "expected.json").read_text(encoding="utf-8")):
    expected = sample["expected"]
    r = processor.recognize(folder / sample["file"], list(expected))
    errors = {
        k: {"expected": v, "actual": r["values"].get(k, "")}
        for k, v in expected.items()
        if r["values"].get(k, "") != v
    }
    if errors:
        failures += 1
    print(
        ("FAIL " if errors else "PASS ") + sample["file"],
        json.dumps(errors, ensure_ascii=False),
        flush=True,
    )
print("Failed scans:", failures)
sys.exit(1 if failures else 0)
