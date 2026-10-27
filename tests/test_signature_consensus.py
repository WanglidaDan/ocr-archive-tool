import unittest
from enhanced_rules import extract_rules_plus

class SignatureConsensus(unittest.TestCase):
    def value(self, text):
        return extract_rules_plus(text, ['文件日期'], 1)['文件日期']

    def test_matching_two_signature_dates(self):
        self.assertEqual(self.value('甲方（盖章）：示例单位\n日期：2026年10月26日\n乙方（盖章）：示例单位\n日期：2026年10月_26日'), '2026-10-26')

    def test_conflicting_or_unreadable_or_single(self):
        for dates in ['日期：2026年10月26日\n乙方（盖章）\n日期：2026年10月27日', '日期：2026年10月26日\n乙方（盖章）\n日期：不详', '日期：2026年10月26日\n乙方（盖章）']:
            self.assertEqual(self.value('甲方（盖章）\n' + dates), '')

    def test_body_date_not_selected(self):
        self.assertEqual(self.value('请于2026年10月26日办理。'), '')

class RedStampSignature(unittest.TestCase):
    def test_two_line_signature_and_date(self):
        from enhanced_rules import _lines, red_signature_candidate
        text = '示例公司\n示例事务办公室\n2026年-9月14日'
        self.assertEqual(red_signature_candidate(_lines(text, None)), ('示例公司示例事务办公室', '2026-09-14'))

    def test_no_invention_from_partial_signature(self):
        from enhanced_rules import _lines, red_signature_candidate
        self.assertIsNone(red_signature_candidate(_lines('示例公司\n2026年-9月14日', None)))
