import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from openpyxl import load_workbook
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QWidget
from app import Window, STYLE
from fixtures import example_scan, example_template


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def test_full_worker_edit_save_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "project.json"
            window = Window(state)
            window.use_template = False
            window.choices = {}
            window.fields = ["文件名称", "文号", "日期", "责任单位", "页数", "备注"]
            window.build_form()
            window.show()
            scan = str(example_scan())
            window.add_paths([scan, scan])
            self.assertEqual(len(window.records), 1)
            window.table.selectRow(0)
            window.start()
            deadline = time.monotonic() + 90
            while window.busy() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.02)
            self.assertFalse(window.busy())
            self.app.processEvents()
            # A failed recognize() stores values as {}. Indexing 责任单位 then
            # raises KeyError instead of showing the recognition error.
            self.assertEqual(
                window.records[0]["status"],
                "待核对",
                window.records[0].get("warning"),
            )
            self.assertEqual(window.records[0]["values"]["责任单位"], "档案馆")
            window.records[0]["status"] = "已核对"
            window.inputs["责任单位"].setText("人工核对单位")
            window.changed()
            self.assertEqual(window.records[0]["status"], "待核对")
            window.save()
            window.close()
            restored = Window(state)
            self.assertEqual(restored.records[0]["values"]["责任单位"], "人工核对单位")
            restored.close()

    def _write_state(self, path, **extra):
        payload = {"fields": ["文件名称", "责任单位"], "records": []}
        payload.update(extra)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_missing_saved_template_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            state = self._write_state(
                tmp / "project.json",
                use_template=True,
                template_path=str(tmp / "gone.xlsx"),
                template_sheet="管理类_件",
            )
            window = Window(state)
            self.assertFalse(window.use_template)
            self.assertIn("找不到", window.template_notice)
            self.assertIn("重新选择", window.template_notice)
            self.assertEqual(window.status.text(), window.template_notice)
            self.assertEqual(window.fields, ["文件名称", "责任单位"])
            with patch("app.QMessageBox.warning") as warning:
                window.show()
                self.app.processEvents()
            warning.assert_called_once()
            self.assertEqual(warning.call_args.args[1], "请重新选择模板")
            self.assertIn("重新选择", warning.call_args.args[2])
            window.close()

    def test_corrupt_saved_template_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bad = tmp / "bad.xlsx"
            bad.write_bytes(b"this is not a zip")
            state = self._write_state(
                tmp / "project.json",
                use_template=True,
                template_path=str(bad),
                template_sheet="管理类_件",
            )
            window = Window(state)
            self.assertFalse(window.use_template)
            self.assertIn("无法读取", window.template_notice)
            self.assertIn("重新选择", window.template_notice)
            window.close()

    def test_corrupt_builtin_template_still_starts(self):
        builtin = (
            Path(__file__).resolve().parents[1] / "templates" / "standard_template.xlsx"
        )
        builtin.parent.mkdir(parents=True, exist_ok=True)
        previous = builtin.read_bytes() if builtin.exists() else None
        builtin.write_bytes(b"not-a-workbook")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                window = Window(Path(tmp) / "missing-project.json")
                self.assertFalse(window.use_template)
                self.assertIn("无法读取", window.template_notice)
                self.assertIn("重新选择", window.template_notice)
                window.close()
        finally:
            if previous is None:
                builtin.unlink(missing_ok=True)
                try:
                    builtin.parent.rmdir()
                except OSError:
                    pass
            else:
                builtin.write_bytes(previous)

    def test_readable_template_stays_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._write_state(
                Path(tmp) / "project.json",
                use_template=True,
                template_path=str(example_template()),
                template_sheet="管理类_件",
            )
            window = Window(state)
            self.assertTrue(window.use_template)
            self.assertIsNone(window.template_notice)
            self.assertIn("永久", window.choices["保管期限"])
            self.assertIn("示例单位A", window.choices["归档单位"])
            self.assertIn("示例单位A", window.choices["归档单位(系统生成)"])
            window.close()

    def test_custom_mode_ignores_missing_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            state = self._write_state(
                tmp / "project.json",
                use_template=False,
                template_path=str(tmp / "gone.xlsx"),
            )
            window = Window(state)
            self.assertFalse(window.use_template)
            self.assertIsNone(window.template_notice)
            window.close()

    def test_builtin_defaults_and_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(Path(tmp) / "missing-project.json")
            self.assertEqual(window.template_sheet, "管理类_件")
            self.assertEqual(window.catalog_defaults["保管期限"], "30年")
            self.assertEqual(window.catalog_defaults["载体类型"], "纸质")
            self.assertEqual(window.catalog_defaults["来源"], "")
            self.assertEqual(window.catalog_defaults["职能标签"], "")
            window.close()

    def test_invalid_saved_default_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._write_state(
                Path(tmp) / "project.json",
                use_template=True,
                template_path=str(example_template()),
                template_sheet="管理类_件",
                catalog_defaults={"保管期限": "不存在", "载体类型": "纸质"},
            )
            window = Window(state)
            self.assertTrue(window.use_template)
            self.assertIn("保管期限", window.defaults_notice)
            self.assertIn("不存在", window.defaults_notice)
            self.assertEqual(window.status.text(), window.defaults_notice)
            window.close()

    def _open_settings(self, window, edit):
        QTimer.singleShot(0, edit)
        window.settings()

    def test_settings_saves_defaults_and_export_uses_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            state = self._write_state(
                tmp / "project.json",
                use_template=True,
                template_path=str(example_template()),
                template_sheet="管理类_件",
            )
            window = Window(state)

            def edit():
                dialog = QApplication.activeModalWidget()
                self.assertEqual(
                    dialog.findChild(QComboBox, "template-sheet").currentText(),
                    "管理类_件",
                )
                dialog.findChild(QWidget, "default:保管期限").setText("永久")
                dialog.findChild(QWidget, "default:载体类型").setText("照片")
                dialog.findChild(QWidget, "default:来源").setText("人工来源")
                dialog.findChild(QWidget, "default:保密期限").setText("")
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()

            self._open_settings(window, edit)
            self.assertEqual(window.catalog_defaults["保管期限"], "永久")
            self.assertEqual(window.catalog_defaults["载体类型"], "照片")
            self.assertEqual(window.catalog_defaults["来源"], "人工来源")
            self.assertEqual(window.catalog_defaults["保密期限"], "")
            self.assertEqual(window.template_sheet, "管理类_件")
            window.close()
            restored = Window(state)
            self.assertEqual(restored.catalog_defaults["保管期限"], "永久")
            self.assertEqual(restored.catalog_defaults["载体类型"], "照片")
            self.assertEqual(restored.catalog_defaults["来源"], "人工来源")
            scan = tmp / "甲.png"
            scan.write_bytes(b"abc")
            restored.records = [
                {
                    "path": str(scan),
                    "text": "原文",
                    "status": "待核对",
                    "values": {"题名": "设置导出", "责任者": "没有这个单位"},
                }
            ]
            output = tmp / "汇总.xlsx"
            with (
                patch(
                    "app.QFileDialog.getSaveFileName",
                    return_value=(str(output), ""),
                ),
                patch("app.QMessageBox.information"),
                patch("app.QMessageBox.warning") as warning,
            ):
                restored.export_summary()
            self.assertFalse(warning.called)
            book = load_workbook(output)
            sheet = book["管理类_件"]
            self.assertEqual(sheet["D2"].value, "设置导出")
            self.assertEqual(sheet["H2"].value, "永久")
            self.assertEqual(sheet["I2"].value, "照片")
            self.assertEqual(sheet["AB2"].value, "人工来源")
            self.assertIsNone(sheet["G2"].value)
            self.assertIsNone(sheet["L2"].value)
            book.close()
            restored.close()

    def test_settings_rejects_default_outside_dropdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._write_state(
                Path(tmp) / "project.json",
                use_template=True,
                template_path=str(example_template()),
                template_sheet="管理类_件",
            )
            window = Window(state)

            def edit():
                dialog = QApplication.activeModalWidget()
                dialog.findChild(QWidget, "default:载体类型").setText("塑料")
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
                self.assertTrue(dialog.isVisible())
                dialog.findChild(QDialogButtonBox).button(
                    QDialogButtonBox.Cancel
                ).click()

            with patch("app.QMessageBox.warning") as warning:
                self._open_settings(window, edit)
            self.assertEqual(warning.call_args.args[1], "默认值无效")
            self.assertIn("载体类型", warning.call_args.args[2])
            self.assertEqual(window.catalog_defaults["载体类型"], "纸质")
            self.assertEqual(window.catalog_defaults["保管期限"], "30年")
            window.close()


if __name__ == "__main__":
    unittest.main()
