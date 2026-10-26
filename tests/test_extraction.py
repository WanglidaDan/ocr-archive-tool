import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extraction import extract, extract_details, reading_rows, normalize_date
from core import DEFAULT_FIELDS


class ExtractionTests(unittest.TestCase):
    def test_inline_and_split_labels(self):
        out = extract(
            "文号：档发〔2026〕12号 日期：2026/1/2\n责任单位\n档案馆", DEFAULT_FIELDS, 1
        )
        self.assertEqual(out["文号"], "档发〔2026〕12号")
        self.assertEqual(out["日期"], "2026-01-02")
        self.assertEqual(out["责任单位"], "档案馆")

    def test_conflict_is_not_bypassed(self):
        for text in [
            "文号：档发〔2026〕12号\n文号：档发〔2026〕13号",
            "档发〔2026〕12号\n档发〔2026〕13号",
        ]:
            v, e, w = extract_details(text, ["文号"], 1)
            self.assertEqual(v["文号"], "")
            self.assertEqual(e["文号"]["status"], "候选冲突")

    def test_date_validity_and_equivalence(self):
        for text in ["2026年13月40日", "2025年2月29日", "2026-02-30"]:
            self.assertEqual(normalize_date(text)[0], "")
        self.assertEqual(normalize_date("2024年2月29日")[0], "2024-02-29")
        self.assertEqual(normalize_date("二〇二六年十月二十六日")[0], "2026-10-26")
        self.assertEqual(
            extract("2026/1/2\n2026年1月2日", ["日期"], 1)["日期"], "2026-01-02"
        )

    def test_width_and_brackets(self):
        v, e, w = extract_details("文号：档发〔2０26］１2号", ["文件编号"], 1)
        self.assertEqual(v["文件编号"], "档发〔2026〕12号")
        self.assertTrue(w)
        self.assertEqual(
            e["文件编号"]["candidates"][0]["line_raw"], "文号：档发〔2０26］１2号"
        )

    def test_title_and_signature_not_body_examples(self):
        text = "--- 第 1 页 ---\n档案馆文件\n档发〔2025〕12号\n关于开展年度\n归档工作的通知\n根据有关规定：\n--- 第 2 页 ---\n标题：方正小标宋简体二号\n文号：其他发〔2015〕3号\n参考日期2020年1月1日\n档案馆\n2026年10月26日"
        v, e, w = extract_details(
            text, ["题名", "责任者", "文件编号", "文件日期", "年度"], 2
        )
        self.assertEqual(
            v,
            {
                "题名": "关于开展年度归档工作的通知",
                "责任者": "档案馆",
                "文件编号": "档发〔2025〕12号",
                "文件日期": "2026-10-26",
                "年度": "2026",
            },
        )
        self.assertTrue(any("年份不一致" in s for s in w))

    def test_low_confidence_and_evidence(self):
        rows = [
            {"text": "日期：2026年10月26日", "page": 2, "confidence": 0.6, "boxes": []}
        ]
        v, e, w = extract_details("", ["日期"], 2, rows)
        self.assertEqual(e["日期"]["candidates"][0]["page"], 2)
        self.assertTrue(any("置信度" in s for s in w))

    def test_model_cannot_hide_conflict_or_invalid(self):
        self.assertEqual(
            extract_details(
                "文号：档发〔2026〕1号\n文号：档发〔2026〕2号",
                ["文号"],
                1,
                additional={"文号": "档发〔2026〕1号"},
            )[0]["文号"],
            "",
        )
        self.assertEqual(
            extract_details(
                "日期：2026年13月1日", ["日期"], 1, additional={"日期": "2026年1月1日"}
            )[0]["日期"],
            "",
        )

    def test_reading_order_from_boxes(self):
        items = [
            {
                "box": [[100, 10], [200, 10], [200, 30], [100, 30]],
                "text": "档案馆",
                "confidence": 0.9,
                "page": 1,
            },
            {
                "box": [[10, 11], [90, 11], [90, 31], [10, 31]],
                "text": "责任者：",
                "confidence": 0.95,
                "page": 1,
            },
        ]
        rows = reading_rows(items)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            extract_details("", ["责任者"], 1, rows)[0]["责任者"], "档案馆"
        )

    def test_missing_label_does_not_steal_another_field(self):
        v = extract("文件名称：\n日期：2026年10月26日", DEFAULT_FIELDS, 1)
        self.assertEqual(v["文件名称"], "")
        self.assertEqual(v["日期"], "2026-10-26")

    def test_owner_from_header_and_any_page_signature(self):
        text = (
            "--- 第 1 页 ---\n"
            "密级：无密级\n"
            "示例报社文件\n"
            "庆油档发〔2026〕12号\n"
            "关于加强档案数字化管理工作的通知\n"
            "各单位：\n"
            "为进一步做好相关工作，现将有关事项通知如下。\n"
            "示例报社\n"
            "2026年2月4日\n"
            "--- 第 2 页 ---\n"
            "附件：工作安排表\n"
            "（此页为附件）\n"
        )
        values, _evidence, warnings = extract_details(
            text, ["题名", "责任者", "文件编号", "文件日期", "页数", "密级"], 2
        )
        self.assertEqual(values["责任者"], "示例报社")
        self.assertEqual(values["题名"], "关于加强档案数字化管理工作的通知")
        self.assertEqual(values["文件编号"], "庆油档发〔2026〕12号")
        self.assertEqual(values["文件日期"], "2026-02-04")
        self.assertEqual(values["页数"], "2")
        self.assertEqual(values["密级"], "无密级")
        self.assertFalse(any("责任者未识别" in item for item in warnings))
        spaced = (
            "--- 第 1 页 ---\n"
            "示 例 机 关文件\n"
            "档发〔2026〕8号\n"
            "关于调整机构设置的决定\n"
            "示 例 机 关\n"
            "2026年5月6日\n"
            "--- 第 2 页 ---\n"
            "（此页为附件）\n"
        )
        owner = extract_details(spaced, ["责任者"], 2)[0]["责任者"]
        self.assertEqual(owner, "示例机关")
        missing, _evidence, warnings = extract_details("正文没有落款", ["责任者"], 1)
        self.assertEqual(missing["责任者"], "")
        self.assertTrue(any("责任者未识别" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
