"""Full headless M1 batch over the generated scan set."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.run_m1_verification import run


class M1VerificationTests(unittest.TestCase):
    def test_full_batch_flow(self):
        report = run()
        print("\n" + report["text"] + "\n", flush=True)
        self.assertTrue(report["ok"], "\n".join(report["problems"]))


if __name__ == "__main__":
    unittest.main()
