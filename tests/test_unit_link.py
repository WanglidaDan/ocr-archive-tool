import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unit_link import match_unit,link_record

class UnitLinkTests(unittest.TestCase):
    def test_unique_leaf_and_full_path(self):
        options=['公司-机关-档案馆','公司-开发部']
        self.assertEqual(match_unit('档案馆',options)[0],options[0])
        self.assertEqual(match_unit(options[0],options)[0],options[0])
    def test_no_fuzzy_guess(self):
        self.assertEqual(match_unit('开发', ['公司-开发部'])[0],'')
        self.assertEqual(match_unit('档案馆',['甲-档案馆','乙-档案馆'])[0],'')
    def test_link_updates_review_and_preserves_original(self):
        r={'status':'已核对','text':'原文','values':{'责任者':'档案馆','归档单位':''}}
        self.assertTrue(link_record(r,['公司-档案馆']))
        self.assertEqual(r['values'],{'责任者':'档案馆','归档单位':'公司-档案馆'})
        self.assertEqual(r['status'],'待核对')
        self.assertFalse(link_record(r,['公司-档案馆']))
        r['values']['责任者']='其他';self.assertFalse(link_record(r,[],False))
        self.assertTrue(link_record(r,['公司-档案馆']));self.assertEqual(r['values']['归档单位'],'')
    def test_blank_responsible_clears_stale_unit(self):
        r={'values':{'责任者':'','归档单位':'旧单位'}}
        self.assertTrue(link_record(r,['公司-档案馆']));self.assertEqual(r['values']['归档单位'],'')

if __name__=='__main__':unittest.main()
