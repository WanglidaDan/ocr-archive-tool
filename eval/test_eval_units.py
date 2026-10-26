"""Unit checks for the evaluation adapter. No OCR models and no ground-truth images."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from extraction import extract_details
from llm_adapter import (
    FieldRequest,
    LLMConfig,
    apply_grounding,
    default_registry,
    load_config,
    merge_fill_empty,
    normalize_accepted,
)
from mock_openai_server import propose, start
from rules_plus import extract_rules_plus

FIELDS = ["题名", "责任者", "文件日期", "文号", "密级", "页数"]


class RulesPlusTests(unittest.TestCase):
    def test_signature_org_outside_current_suffix_list(self):
        text = "\n".join([
            "示例市档案局文件",
            "示档局发〔2024〕12号",
            "关于开展档案数字化的通知",
            "各有关单位：",
            "请于2023年5月6日前报送。",
            "示例市档案局",
            "2024年3月15日",
        ])
        current = extract_details(text, FIELDS, 1)[0]
        improved = extract_rules_plus(text, FIELDS, 1)
        self.assertEqual(current["责任者"], "")
        self.assertEqual(current["文件日期"], "")
        self.assertEqual(improved["责任者"], "示例市档案局")
        self.assertEqual(improved["文件日期"], "2024-03-15")
        self.assertEqual(improved["题名"], "关于开展档案数字化的通知")
        self.assertEqual(improved["文号"], "示档局发〔2024〕12号")
        self.assertEqual(improved["页数"], "1")

    def test_title_without_guanyu_and_points(self):
        text = "示例市人民政府文件\n示政发〔2024〕3号\n开展档案数字化的通知\n各有关单位：\n正文。\n示例市人民政府\n2024年6月1日"
        improved = extract_rules_plus(text, FIELDS, 1)
        self.assertEqual(improved["题名"], "开展档案数字化的通知")
        points = "示例市人民政府文件\n示政发〔2024〕4号\n开展档案数字化工作要点\n各有关单位：\n正文。"
        self.assertEqual(extract_rules_plus(points, FIELDS, 1)["题名"], "开展档案数字化工作要点")

    def test_empty_ocr_does_not_invent_page_count(self):
        self.assertEqual(extract_rules_plus("", FIELDS, 2)["页数"], "")


class AdapterTests(unittest.TestCase):
    def test_kunlun_is_not_guessed(self):
        provider = default_registry().create(LLMConfig(provider="kunlun"))
        with self.assertRaises(Exception) as caught:
            provider.complete(FieldRequest(fields=FIELDS, ocr_text="原文"))
        self.assertIn("猜测", str(caught.exception))
        self.assertIn("昆仑", str(caught.exception))

    def test_config_rejects_repo_file_and_keeps_key_out_of_code(self):
        inside = ROOT / "eval" / "llm.example.json"
        with self.assertRaises(ValueError):
            load_config({"ARCHIVE_LLM_CONFIG": str(inside)})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm.json"
            path.write_text(json.dumps({
                "provider": "openai_compatible",
                "base_url": "http://10.0.0.8/v1",
                "model": "kunlun-placeholder",
                "api_key": "secret-from-outside",
                "vision": True,
            }), encoding="utf-8")
            loaded = load_config({"ARCHIVE_LLM_CONFIG": str(path), "ARCHIVE_LLM_API_KEY": "env-wins"})
        self.assertEqual(loaded.api_key, "env-wins")
        self.assertTrue(loaded.vision)
        self.assertEqual(loaded.base_url, "http://10.0.0.8/v1")
        self.assertNotIn("secret-from-outside", (ROOT / "eval" / "llm_adapter.py").read_text(encoding="utf-8"))

    def test_grounding_rejects_text_the_model_added(self):
        ocr = "关于开展档案数字化的通知\n示档发〔2024〕12号"
        accepted, rejected = apply_grounding(
            {"题名": "关于开展档案数字化的通知（补写）", "文号": "示档发〔2024〕12号", "页数": "9"},
            ocr, FIELDS,
        )
        self.assertEqual(accepted["题名"], "")
        self.assertEqual(accepted["文号"], "示档发〔2024〕12号")
        self.assertNotIn("页数", accepted)
        self.assertEqual(rejected, ["题名"])

    def test_mock_server_roundtrip_vision_and_hallucination(self):
        ocr = "\n".join([
            "--- 第 1 页 ---",
            "机密",
            "示例市档案管理局文件",
            "示档发〔2024〕12号",
            "关于开展档案数字化的通知",
            "各有关单位：",
            "请于2023年5月6日前报送。",
            "示例市档案管理局",
            "2024年3月15日",
        ])
        key = "unit-test-key"
        server, base = start("hallucinate", expect_key=key)
        self.addCleanup(server.shutdown)
        os.environ["ARCHIVE_LLM_PROVIDER"] = "openai_compatible"
        try:
            config = LLMConfig(provider="openai_compatible", base_url=base, model="mock", api_key=key, vision=True, timeout_s=10)
            provider = default_registry().create(config)
            from PIL import Image
            import io
            buf = io.BytesIO()
            Image.new("RGB", (8, 8), "red").save(buf, format="PNG")
            result = provider.complete(FieldRequest(fields=FIELDS, ocr_text=ocr, page_images=[buf.getvalue()]))
        finally:
            os.environ.pop("ARCHIVE_LLM_PROVIDER", None)
        accepted, rejected = apply_grounding(result.values, ocr, FIELDS)
        self.assertIn("题名", rejected)
        self.assertIn("文件日期", rejected)
        self.assertEqual(accepted["文号"], "示档发〔2024〕12号")
        self.assertEqual(server.stats["requests_with_image"], 1)
        self.assertEqual(server.stats["images_decoded"], 1)
        self.assertEqual(server.stats["auth_ok"], 1)
        self.assertNotIn(key, json.dumps(server.stats))
        # Missing key is refused and does not return fields.
        bare = LLMConfig(provider="openai_compatible", base_url=base, model="mock", api_key="", vision=False, timeout_s=10)
        with self.assertRaises(Exception):
            default_registry().create(bare).complete(FieldRequest(fields=FIELDS, ocr_text=ocr))
        self.assertGreaterEqual(server.stats["unauthorized"], 1)

    def test_fill_empty_does_not_override_a_rule_value(self):
        rules = {"题名": "关于甲的通知", "文件日期": "", "文号": "", "责任者": "", "密级": "", "页数": "1"}
        accepted = normalize_accepted({"题名": "关于乙的通知", "文件日期": "2024年3月15日"})
        # 2024年3月15日 normalizes; 题名 is kept by clean.
        merged, filled = merge_fill_empty(rules, {"题名": accepted["题名"], "文件日期": accepted["文件日期"]}, "关于甲的通知\n2024年3月15日", checked=True)
        self.assertEqual(merged["题名"], "关于甲的通知")
        self.assertEqual(merged["文件日期"], "2024-03-15")
        self.assertEqual(filled, ["文件日期"])

    def test_propose_does_not_need_ground_truth(self):
        values = propose("示档发〔2024〕12号\n关于开展档案数字化的通知", "grounded")
        self.assertEqual(values["文号"], "示档发〔2024〕12号")
        self.assertEqual(values["题名"], "关于开展档案数字化的通知")


if __name__ == "__main__":
    unittest.main()
