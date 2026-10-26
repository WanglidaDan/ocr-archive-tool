import sys,tempfile,unittest
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from template_io import inspect_template,export_template
TEMPLATE=Path(__file__).parents[1]/'templates/standard_template.xlsx'

class TemplateTests(unittest.TestCase):
    def test_schema_preserved_with_real_date_types(self):
        from openpyxl import load_workbook
        meta=inspect_template(TEMPLATE)
        self.assertEqual(len(meta['headers']),30);self.assertIn('永久',meta['choices']['保管期限'])
        record={'values':{'题名':'=1+1','文件日期':'2026年10月26日','页数':'4','年度':'2026','责任者':'档案馆'}}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'output.xlsx';export_template(p,[record],TEMPLATE,'管理类_件')
            a=load_workbook(TEMPLATE);b=load_workbook(p)
            self.assertEqual(a.sheetnames,b.sheetnames)
            for aa,bb in zip(a,b):
                self.assertEqual([c.value for c in aa[1]],[c.value for c in bb[1]])
                self.assertEqual(aa.data_validations.to_tree().attrib,bb.data_validations.to_tree().attrib)
                self.assertEqual(str(aa.data_validations),str(bb.data_validations))
            ws=b['管理类_件'];self.assertEqual(ws['D2'].data_type,'s');self.assertEqual(ws['F2'].value,'2026-10-26');self.assertEqual(ws['S2'].value,4)
            self.assertEqual(list(a.defined_names),list(b.defined_names))
    def test_invalid_dictionary_and_date_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for values in [{'密级':'未定义密级'},{'文件日期':'2026年13月1日'},{'文件日期':'2099-01-01'},{'页数':'4.5'}]:
                with self.assertRaises(ValueError):export_template(Path(tmp)/'bad.xlsx',[{'values':values}],TEMPLATE,'管理类_件')
    def test_all_catalog_sheets_supported(self):
        for sheet,count in [('管理类_件',30),('管理类_卷',28),('管理类_卷内件',24)]:
            self.assertEqual(len(inspect_template(TEMPLATE,sheet)['headers']),count)

if __name__=='__main__':unittest.main()
