import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import assemble_fields
from extraction import extract_details

FIELDS = ["题名", "责任者", "文件日期", "文号", "密级", "页数"]
TEXT = "\n".join([
    "--- 第 1 页 ---",
    "示例市档案局文件",
    "示档局发〔2019〕12号",
    "开展档案数字化工作要点",
    "各有关单位：",
    "请于2023年5月6日前报送。",
    "示例市档案局",
    "二〇一九年三月十八日",
])


class EnhancedRulesTests(unittest.TestCase):
    def test_off_matches_current_extractor(self):
        current = extract_details(TEXT, FIELDS, 1)
        gated = assemble_fields(TEXT, FIELDS, 1, None, False)
        self.assertEqual(gated[0], current[0])
        self.assertEqual(gated[1], current[1])
        self.assertEqual(gated[2], current[2])

    def test_on_fills_org_title_and_signature_date(self):
        before = assemble_fields(TEXT, FIELDS, 1, None, False)[0]
        after, evidence, warnings = assemble_fields(TEXT, FIELDS, 1, None, True)
        self.assertEqual(before["责任者"], "")
        self.assertEqual(before["题名"], "")
        self.assertEqual(after["题名"], "开展档案数字化工作要点")
        self.assertEqual(after["责任者"], "示例市档案局")
        self.assertEqual(after["文件日期"], "2019-03-18")
        self.assertEqual(after["文号"], "示档局发〔2019〕12号")
        self.assertEqual(after["页数"], "1")
        self.assertEqual(evidence["题名"]["candidates"][0]["source"], "公文规则增强")
        self.assertTrue(any("公文规则增强" in item for item in warnings))

    def test_page_count_stays_file_frames(self):
        after = assemble_fields(TEXT, FIELDS, 2, None, True)[0]
        self.assertEqual(after["页数"], "2")


if __name__ == "__main__":
    unittest.main()
