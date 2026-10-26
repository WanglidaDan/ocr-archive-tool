import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import tempfile
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import Window, STYLE

class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]); cls.app.setStyleSheet(STYLE)
    def test_full_worker_edit_save_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'project.json'; window=Window(state); window.use_template=False;window.choices={};window.fields=['文件名称','文号','日期','责任单位','页数','备注'];window.build_form();window.show()
            scan=str(Path(__file__).parents[1]/'samples/sample_scan.png')
            window.add_paths([scan,scan]); self.assertEqual(len(window.records),1)
            window.table.selectRow(0); window.start()
            deadline=time.monotonic()+90
            while window.busy() and time.monotonic()<deadline:
                self.app.processEvents(); time.sleep(.02)
            self.assertFalse(window.busy()); self.app.processEvents()
            self.assertEqual(window.records[0]['values']['责任单位'],'档案馆')
            window.records[0]['status']='已核对'
            window.inputs['责任单位'].setText('人工核对单位'); window.changed()
            self.assertEqual(window.records[0]['status'],'待核对')
            window.save(); window.close()
            restored=Window(state)
            self.assertEqual(restored.records[0]['values']['责任单位'],'人工核对单位'); restored.close()

if __name__=='__main__':unittest.main()
