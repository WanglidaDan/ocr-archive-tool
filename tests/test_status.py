import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from status_model import (
    FAILED,
    NEEDS_REVIEW,
    RECOGNIZED,
    STOPPED,
    classify_recognition,
    needs_ocr,
    not_exportable,
    recognition_block_reason,
)

FIELDS = ["文件名称", "文号", "日期", "责任单位", "页数", "备注"]
VALUES = {
    "文件名称": "关于启用的通知",
    "文号": "档发〔2026〕12号",
    "日期": "2026-10-26",
    "责任单位": "示例单位A",
    "页数": "1",
    "备注": "",
}


def evidence(scores):
    found = {}
    for field, score in scores.items():
        found[field] = {
            "candidates": [
                {"value": VALUES.get(field, ""), "confidence": score, "issue": ""}
            ]
        }
    return found


class StatusModelTests(unittest.TestCase):
    def test_complete_high_confidence_is_recognized(self):
        scores = {
            "文件名称": 0.91,
            "文号": 0.9,
            "日期": 0.99,
            "责任单位": 0.85,
            "页数": None,
        }
        self.assertEqual(
            classify_recognition(FIELDS, VALUES, evidence(scores), 0.85),
            RECOGNIZED,
        )

    def test_owner_alias_counts_as_required(self):
        fields = ["题名", "文件编号", "文件日期", "责任者", "页数"]
        values = {
            "题名": "通知",
            "文件编号": "档发〔2026〕1号",
            "文件日期": "2026-10-26",
            "责任者": "",
            "页数": "2",
        }
        scores = evidence(
            {
                "题名": 0.95,
                "文件编号": 0.95,
                "文件日期": 0.95,
                "责任者": None,
                "页数": None,
            }
        )
        self.assertEqual(classify_recognition(fields, values, scores), NEEDS_REVIEW)
        values["责任者"] = "示例机关"
        scores["责任者"] = {"candidates": [{"confidence": 0.93, "issue": ""}]}
        self.assertEqual(
            classify_recognition(fields, values, scores),
            RECOGNIZED,
        )

    def test_low_field_confidence_needs_review(self):
        scores = {
            "文件名称": 0.99,
            "文号": 0.84,
            "日期": 0.99,
            "责任单位": 0.99,
            "页数": None,
        }
        self.assertEqual(
            classify_recognition(FIELDS, VALUES, evidence(scores), 0.99),
            NEEDS_REVIEW,
        )

    def test_optional_low_confidence_needs_review(self):
        scores = {
            "文件名称": 0.99,
            "文号": 0.99,
            "日期": 0.99,
            "责任单位": 0.99,
            "页数": None,
            "备注": 0.5,
        }
        values = {**VALUES, "备注": "附注"}
        self.assertEqual(
            classify_recognition(FIELDS, values, evidence(scores)),
            NEEDS_REVIEW,
        )

    def test_missing_owner_confidence_needs_review(self):
        scores = {
            "文件名称": 0.99,
            "文号": 0.99,
            "日期": 0.99,
            "责任单位": None,
            "页数": None,
        }
        self.assertEqual(
            classify_recognition(FIELDS, VALUES, evidence(scores), 0.99),
            NEEDS_REVIEW,
        )

    def test_failure_and_stop_are_not_exportable_and_keep_their_reason(self):
        failed = {
            "status": FAILED,
            "warning": "文件已损坏，不是有效的 PDF。",
            "text": "",
        }
        stopped = {"status": STOPPED, "warning": STOPPED, "text": "已完成的原文"}
        recognized = {
            "status": RECOGNIZED,
            "text": "原文",
            "export_status": "失败",
            "export_error": "磁盘空间不足",
        }
        self.assertTrue(not_exportable(failed))
        self.assertTrue(needs_ocr(failed))
        self.assertEqual(recognition_block_reason(failed), failed["warning"])
        self.assertTrue(not_exportable(stopped))
        self.assertEqual(recognition_block_reason(stopped), STOPPED)
        self.assertFalse(not_exportable(recognized))
        self.assertFalse(needs_ocr(recognized))
        self.assertEqual(recognized["export_status"], "失败")


if __name__ == "__main__":
    unittest.main()
