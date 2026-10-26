import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import csv
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
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialogButtonBox,
    QMessageBox,
    QPushButton,
    QWidget,
)
from app import ExportWorker, Window, STYLE, show_export_result
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
            window.template_notice = None
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
            self.assertIn(
                window.records[0]["status"],
                ("已识别", "待核对"),
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
            self.assertIn("导出已停用", window.template_notice)
            self.assertFalse(window.export_btn.isEnabled())
            self.assertFalse(window.summary_btn.isEnabled())
            self.assertFalse(window.template_banner.isHidden())
            self.assertIn("无法读取", window.template_banner.text())
            self.assertIn(str(bad), window.template_notice)
            self.assertIn(str(bad), window.template_banner.text())
            self.assertNotIn("自定义", window.template_notice)
            window.close()

    def test_missing_sheet_banner_names_the_sheet(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            book = Workbook()
            book.active.title = "其他"
            path = tmp / "no-piece.xlsx"
            book.save(path)
            book.close()
            state = self._write_state(
                tmp / "project.json",
                use_template=True,
                template_path=str(path),
                template_sheet="管理类_件",
            )
            window = Window(state)
            self.assertFalse(window.use_template)
            self.assertIn("管理类_件", window.template_notice)
            self.assertIn("工作表", window.template_notice)
            self.assertNotIn("文件已损坏", window.template_notice)
            self.assertIn("导出已停用", window.template_notice)
            self.assertFalse(window.export_btn.isEnabled())
            self.assertFalse(window.summary_btn.isEnabled())
            self.assertFalse(window.template_banner.isHidden())
            self.assertIn("管理类_件", window.template_banner.text())
            window.close()

    def test_builtin_missing_sheet_names_the_sheet(self):
        from openpyxl import Workbook

        builtin = (
            Path(__file__).resolve().parents[1] / "templates" / "standard_template.xlsx"
        )
        builtin.parent.mkdir(parents=True, exist_ok=True)
        previous = builtin.read_bytes() if builtin.exists() else None
        book = Workbook()
        book.active.title = "其他"
        book.save(builtin)
        book.close()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                window = Window(Path(tmp) / "missing-project.json")
                self.assertFalse(window.use_template)
                self.assertIn("管理类_件", window.template_notice)
                self.assertIn("工作表", window.template_notice)
                self.assertNotIn("文件已损坏", window.template_notice)
                self.assertFalse(window.export_btn.isEnabled())
                self.assertFalse(window.template_banner.isHidden())
                self.assertIn("管理类_件", window.template_banner.text())
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
                self.assertIn("导出已停用", window.template_notice)
                self.assertFalse(window.export_btn.isEnabled())
                self.assertFalse(window.template_banner.isHidden())
                self.assertIn(str(builtin), window.template_notice)
                self.assertIn(str(builtin), window.template_banner.text())
                self.assertNotIn("自定义", window.template_notice)
                self.assertNotIn("自定义", window.status.text())
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
            self.assertTrue(window.export_btn.isEnabled())
            self.assertTrue(window.template_banner.isHidden())
            window.close()

    def test_missing_template_disables_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            state = self._write_state(
                tmp / "project.json",
                use_template=False,
                template_path=str(tmp / "gone.xlsx"),
            )
            window = Window(state)
            self.assertFalse(window.use_template)
            self.assertIn("导出已停用", window.template_notice)
            self.assertIn("找不到", window.template_notice)
            self.assertFalse(window.export_btn.isEnabled())
            self.assertFalse(window.summary_btn.isEnabled())
            self.assertFalse(window.overwrite_box.isChecked())
            self.assertIn("导出已停用", window.export_btn.toolTip())
            self.assertFalse(window.template_banner.isHidden())
            self.assertIn("找不到", window.template_banner.text())
            self.assertEqual(window.template_banner.objectName(), "banner")
            self.assertIn("QLabel#banner {background:#c0392b", STYLE)
            self.assertNotIn("#f4e4c4", STYLE)
            self.assertNotIn("自定义", window.template_notice)
            self.assertNotIn("自定义", window.status.text())
            self.assertEqual(window.retry_btn.text(), "只重试失败项")
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

    def _wait_idle(self, window, timeout):
        deadline = time.monotonic() + timeout
        started = time.monotonic()
        while time.monotonic() < deadline:
            self.app.processEvents()
            if window.busy():
                break
            if time.monotonic() - started > 1:
                break
            time.sleep(0.01)
        while window.busy() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertFalse(window.busy(), window.status.text())

    def _click_dialog(self, text, checks=None):
        def click():
            box = QApplication.activeModalWidget()
            self.assertIsInstance(box, QMessageBox)
            if checks:
                checks(box)
            for button in box.findChildren(QPushButton):
                if button.text() == text:
                    button.click()
                    return
            self.fail("对话框里没有按钮：" + text)

        QTimer.singleShot(0, click)

    def test_bad_pdfs_are_separate_failures(self):
        from app import Worker

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            corrupt = tmp / "损坏.pdf"
            corrupt.write_bytes(b"this is not a pdf")
            encrypted = tmp / "加密.pdf"
            import fitz

            document = fitz.open()
            document.new_page()
            document.save(
                encrypted,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw="owner-secret",
                user_pw="user-secret",
            )
            document.close()
            worker = Worker(
                [(0, str(corrupt)), (1, str(encrypted))],
                ["文件名称"],
                "",
            )
            found = {}
            worker.result.connect(
                lambda index, result: found.__setitem__(index, result)
            )
            worker.start()
            deadline = time.monotonic() + 30
            while len(found) < 2 and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.02)
            self.app.processEvents()
            self.assertFalse(worker.isRunning())
            self.assertEqual(set(found), {0, 1})
            self.assertEqual(found[0]["status"], "失败")
            self.assertIn("文件已损坏", found[0]["warning"])
            self.assertNotIn("FileData", found[0]["warning"])
            self.assertEqual(found[1]["status"], "失败")
            self.assertIn("PDF已加密", found[1]["warning"])

    def test_recognition_progress_can_be_stopped(self):
        from core import Cancelled

        def hang(
            self,
            path,
            fields,
            cancelled=lambda: False,
            progress=lambda message: None,
            model="",
        ):
            progress("正在识别第 1 页")
            while not cancelled():
                time.sleep(0.01)
            raise Cancelled()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("core.Processor.recognize", hang),
        ):
            tmp = Path(tmp)
            first = tmp / "甲.pdf"
            second = tmp / "乙.pdf"
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            window = Window(tmp / "project.json")
            window.template_notice = None
            window.add_paths([str(first), str(second)])
            window.start()
            deadline = time.monotonic() + 5
            while (
                "第1个/共2个" not in window.status.text()
                and time.monotonic() < deadline
            ):
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIn("正在识别 第1个/共2个", window.status.text())
            self.assertEqual(window.progress.format(), "第%v个/共%m个")
            self.assertTrue(window.stop_btn.isEnabled())
            self.assertEqual(window.progress.maximum(), 2)
            window.stop()
            self._wait_idle(window, 10)
            self.assertEqual(
                [record["status"] for record in window.records],
                ["已停止，可重新识别", "待识别"],
            )
            self.assertIn("已停止", window.status.text())
            window.close()

    def test_unreviewed_dialog_counts_files_and_can_go_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            window = self._template_window(tmp)
            window.records = [
                {
                    "path": str(tmp / "甲.pdf"),
                    "status": "待核对",
                    "text": "甲",
                    "values": {},
                },
                {
                    "path": str(tmp / "乙.pdf"),
                    "status": "待核对",
                    "text": "乙",
                    "values": {},
                },
                {
                    "path": str(tmp / "丙.pdf"),
                    "status": "已核对",
                    "text": "丙",
                    "values": {},
                },
                {
                    "path": str(tmp / "丁.pdf"),
                    "status": "已识别",
                    "text": "丁",
                    "values": {"责任者": "示例单位A"},
                    "export_status": "失败",
                    "export_error": "磁盘空间不足",
                },
                {
                    "path": str(tmp / "戊.pdf"),
                    "status": "失败",
                    "text": "",
                    "warning": "文件已损坏",
                    "values": {},
                },
            ]

            def checks(box):
                self.assertEqual(box.windowTitle(), "尚有未核对文件")
                self.assertIn("有 2 份尚未核对。", box.text())
                labels = [button.text() for button in box.findChildren(QPushButton)]
                self.assertIn("继续导出", labels)
                self.assertIn("返回", labels)

            self._click_dialog("返回", checks)
            with patch("app.QFileDialog.getExistingDirectory") as choose:
                window.export()
            choose.assert_not_called()
            window.close()

    def test_unreviewed_dialog_continue_remembers_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            window = self._template_window(tmp)
            remembered = tmp / "上次"
            remembered.mkdir()
            window.export_folder = str(remembered)
            window.records = [
                {
                    "path": str(tmp / "甲.pdf"),
                    "status": "待核对",
                    "text": "甲",
                    "values": {},
                }
            ]
            self._click_dialog("继续导出")
            with patch(
                "app.QFileDialog.getExistingDirectory", return_value=""
            ) as choose:
                window.export()
            choose.assert_called_once()
            self.assertEqual(choose.call_args.args[2], str(remembered))
            window.close()

    def test_result_dialog_opens_folder_and_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(Path(tmp) / "project.json")
            window.template_notice = None
            summary = (
                "成功 1 份，失败 1 份。\n失败：\n甲.pdf：PDF已加密，请先解密再导入。"
            )

            def checks(box):
                self.assertEqual(box.windowTitle(), "批量导出结果")
                self.assertIn("成功 1 份，失败 1 份。", box.text())
                self.assertIn("甲.pdf：PDF已加密，请先解密再导入。", box.text())
                labels = [button.text() for button in box.findChildren(QPushButton)]
                self.assertIn("打开输出文件夹", labels)
                self.assertIn("只重试失败项", labels)
                self.assertIn("关闭", labels)

            self._click_dialog("打开输出文件夹", checks)
            with patch("app.open_output_folder") as opener:
                action = show_export_result(window, summary, tmp, True)
            self.assertEqual(action, "open")
            opener.assert_called_once_with(tmp)
            self._click_dialog("只重试失败项")
            self.assertEqual(show_export_result(window, summary, tmp, True), "retry")
            self._click_dialog("关闭")
            self.assertEqual(show_export_result(window, summary, tmp, False), "close")
            window.close()

    def test_overwrite_checkbox_is_off_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._write_state(
                Path(tmp) / "project.json",
                use_template=True,
                template_path=str(example_template()),
                template_sheet="管理类_件",
            )
            window = Window(state)
            self.assertFalse(window.overwrite_box.isChecked())
            self.assertFalse(window.overwrite_same_name)
            window.overwrite_box.setChecked(True)
            self.app.processEvents()
            window.close()
            restored = Window(state)
            self.assertTrue(restored.overwrite_same_name)
            self.assertTrue(restored.overwrite_box.isChecked())
            restored.close()

    def test_export_worker_suffixes_same_names_even_when_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            records = [
                {
                    "path": str(folder / "甲" / "发文001.pdf"),
                    "text": "甲",
                    "status": "已核对",
                    "values": {"题名": "第一份", "密级": "非涉密"},
                },
                {
                    "path": str(folder / "乙" / "发文001.pdf"),
                    "text": "乙",
                    "status": "已核对",
                    "values": {"题名": "第二份", "密级": "非涉密"},
                },
            ]
            worker = ExportWorker(
                list(enumerate(records)),
                str(folder),
                str(example_template()),
                "管理类_件",
                overwrite=True,
            )
            worker.start()
            deadline = time.monotonic() + 30
            while worker.isRunning() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.02)
            self.assertFalse(worker.isRunning())
            self.assertEqual(
                [item["excel_name"] for item in worker.results],
                ["发文001.xlsx", "发文001(1).xlsx"],
            )
            self.assertTrue(all(not item["error"] for item in worker.results))

    def _template_window(self, tmp):
        state = self._write_state(
            Path(tmp) / "project.json",
            use_template=True,
            template_path=str(example_template()),
            template_sheet="管理类_件",
        )
        window = Window(state)
        self.assertTrue(window.export_btn.isEnabled())
        return window

    def test_retry_exports_only_the_failed_file(self):
        import os

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            window = self._template_window(tmp)
            output = tmp / "out"
            output.mkdir()
            remembered = tmp / "上次"
            remembered.mkdir()
            window.export_folder = str(remembered)
            good = tmp / "good.pdf"
            bad = tmp / "bad.pdf"
            good.write_bytes(b"1")
            bad.write_bytes(b"2")

            def record(path, title):
                return {
                    "path": str(path),
                    "status": "已核对",
                    "text": "原文",
                    "pages": 1,
                    "values": {
                        "题名": title,
                        "责任者": "示例单位A",
                        "文件日期": "2026-10-26",
                        "页数": "1",
                        "正本数量": "1",
                        "密级": "非涉密",
                    },
                }

            window.records = [record(good, "成功件"), record(bad, "失败件")]
            real_replace = os.replace

            def locked(src, dst):
                if Path(dst).name.startswith("bad"):
                    raise PermissionError("locked by Excel")
                return real_replace(src, dst)

            summaries = []

            def capture(parent, summary, folder, can_retry):
                summaries.append((summary, folder, can_retry))
                return "close"

            with (
                patch("batch_export.os.replace", locked),
                patch("app.show_export_result", capture),
                patch(
                    "app.QFileDialog.getExistingDirectory", return_value=str(output)
                ) as choose,
            ):
                window.export()
                self._wait_idle(window, 30)
            self.assertEqual(choose.call_args.args[2], str(remembered))
            self.assertEqual(window.export_folder, str(output))
            self.assertIn("成功 1 份，失败 1 份。", summaries[-1][0])
            self.assertIn("无法写入 Excel，文件可能正被占用", summaries[-1][0])
            self.assertTrue(summaries[-1][2])
            self.assertTrue((output / "good.xlsx").is_file())
            self.assertFalse(list(output.glob("bad*.xlsx")))
            saved = json.loads((tmp / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["export_folder"], str(output))
            good_bytes = (output / "good.xlsx").read_bytes()
            manifest_path = output / "处理清单.csv"
            with manifest_path.open(encoding="utf-8-sig", newline="") as handle:
                manifest_rows = list(csv.DictReader(handle))
            self.assertEqual(
                [row["文件名"] for row in manifest_rows], ["good.pdf", "bad.pdf"]
            )
            self.assertEqual(manifest_rows[0]["源文件完整路径"], str(good))
            self.assertEqual(manifest_rows[1]["源文件完整路径"], str(bad))
            self.assertNotEqual(
                manifest_rows[0]["源文件完整路径"],
                manifest_rows[1]["源文件完整路径"],
            )
            with patch("app.show_export_result", capture):
                window.retry_failed()
                self._wait_idle(window, 30)
            self.assertTrue((output / "bad.xlsx").is_file())
            self.assertEqual((output / "good.xlsx").read_bytes(), good_bytes)
            with manifest_path.open(encoding="utf-8-sig", newline="") as handle:
                kept_rows = list(csv.DictReader(handle))
            self.assertEqual(
                [row["文件名"] for row in kept_rows[:2]], ["good.pdf", "bad.pdf"]
            )
            self.assertEqual(kept_rows[0]["状态"], "成功")
            self.assertEqual(kept_rows[0]["源文件完整路径"], str(good))
            self.assertEqual(kept_rows[-1]["文件名"], "bad.pdf")
            self.assertEqual(kept_rows[-1]["状态"], "成功")
            self.assertEqual(kept_rows[-1]["源文件完整路径"], str(bad))
            self.assertIn("成功 1 份，失败 0 份。", summaries[-1][0])
            self.assertFalse(window.records[0]["export_error"])
            self.assertFalse(window.records[1]["export_error"])
            window.close()

    def test_missing_owner_is_highlighted(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(Path(tmp) / "project.json")
            window.records = [
                {
                    "path": str(Path(tmp) / "空白.pdf"),
                    "status": "待核对",
                    "text": "原文",
                    "values": {"责任单位": ""},
                    "evidence": {},
                }
            ]
            window.current = 0
            window.load_record()
            self.assertIn("fff3a0", window.inputs["责任单位"].styleSheet())
            window.inputs["责任单位"].setText("示例单位")
            window.changed("责任单位")
            self.assertNotIn("fff3a0", window.inputs["责任单位"].styleSheet())
            window.close()

    def test_second_export_skips_succeeded_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            window = self._template_window(tmp)
            output = tmp / "out"
            output.mkdir()
            good = tmp / "good.pdf"
            bad = tmp / "bad.pdf"
            good.write_bytes(b"1")
            bad.write_bytes(b"2")
            existing = output / "good.xlsx"
            existing.write_bytes(b"already-exported")

            def record(path, title):
                return {
                    "path": str(path),
                    "status": "已核对",
                    "text": "原文",
                    "pages": 1,
                    "values": {"题名": title, "密级": "非涉密"},
                }

            window.records = [
                {
                    **record(good, "成功件"),
                    "export_status": "成功",
                    "export_path": str(existing),
                    "export_error": "",
                },
                record(bad, "失败件"),
            ]

            def capture(parent, summary, folder, can_retry):
                return "close"

            with (
                patch("app.show_export_result", capture),
                patch("app.confirm_unreviewed", return_value=True),
                patch("app.QFileDialog.getExistingDirectory", return_value=str(output)),
            ):
                window.export()
                self._wait_idle(window, 30)
            self.assertEqual(existing.read_bytes(), b"already-exported")
            self.assertTrue((output / "bad.xlsx").is_file())
            self.assertFalse((output / "good(1).xlsx").exists())
            self.assertEqual(window.records[1]["export_status"], "成功")
            window.close()

    def test_export_worker_survives_a_missing_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            records = [
                {
                    "path": str(folder / "甲.pdf"),
                    "text": "甲",
                    "status": "已核对",
                    "values": {"题名": "甲"},
                },
                {
                    "path": str(folder / "乙.pdf"),
                    "text": "乙",
                    "status": "已核对",
                    "values": {"题名": "乙"},
                },
            ]
            worker = ExportWorker(
                list(enumerate(records)),
                str(folder),
                str(folder / "missing.xlsx"),
                "管理类_件",
            )
            worker.start()
            deadline = time.monotonic() + 30
            while worker.isRunning() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.02)
            self.assertFalse(worker.isRunning())
            self.assertEqual(len(worker.results), 2)
            self.assertTrue(
                all("找不到模板" in item["error"] for item in worker.results)
            )
            self.assertTrue(worker.isFinished())

    def test_file_size_unit_defaults_to_mb_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._write_state(
                Path(tmp) / "project.json",
                use_template=True,
                template_path=str(example_template()),
                template_sheet="管理类_件",
            )
            window = Window(state)
            self.assertEqual(window.file_size_unit, "MB")
            window.file_size_unit = "KB"
            window.dirty = True
            window.save()
            window.close()
            restored = Window(state)
            self.assertEqual(restored.file_size_unit, "KB")
            restored.close()
            payload = json.loads(state.read_text(encoding="utf-8"))
            payload["file_size_unit"] = "GB"
            state.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            fallback = Window(state)
            self.assertEqual(fallback.file_size_unit, "MB")
            fallback.close()

    def test_stop_keeps_completed_recognition(self):
        from core import Cancelled

        def recognize(
            self,
            path,
            fields,
            cancelled=lambda: False,
            progress=lambda message: None,
            model="",
        ):
            progress("正在识别第 1 页")
            if Path(path).name.startswith("甲"):
                values = {
                    "文件名称": "关于启用的通知",
                    "文号": "档发〔2026〕12号",
                    "日期": "2026-10-26",
                    "责任单位": "示例单位A",
                    "页数": "1",
                    "备注": "",
                }
                evidence = {
                    field: {
                        "candidates": [
                            {
                                "value": values[field],
                                "confidence": None if field == "页数" else 0.96,
                                "issue": "",
                            }
                        ]
                    }
                    for field in values
                }
                return {
                    "text": "原文",
                    "values": values,
                    "evidence": evidence,
                    "pages": 1,
                    "confidence": 0.96,
                    "warning": "",
                    "ocr_rows": [],
                    "engine_version": "0.3",
                }
            while not cancelled():
                time.sleep(0.01)
            raise Cancelled()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("core.Processor.recognize", recognize),
        ):
            tmp = Path(tmp)
            first = tmp / "甲.pdf"
            second = tmp / "乙.pdf"
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            window = Window(tmp / "project.json")
            window.template_notice = None
            window.use_template = False
            window.choices = {}
            window.fields = ["文件名称", "文号", "日期", "责任单位", "页数", "备注"]
            window.add_paths([str(first), str(second)])
            window.start()
            deadline = time.monotonic() + 5
            while (
                "第2个/共2个" not in window.status.text()
                and time.monotonic() < deadline
            ):
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIn("正在识别 第2个/共2个", window.status.text())
            self.assertEqual(window.records[0]["status"], "已识别")
            self.assertEqual(window.records[0]["values"]["责任单位"], "示例单位A")
            window.stop()
            self._wait_idle(window, 10)
            self.assertEqual(window.records[0]["status"], "已识别")
            self.assertEqual(window.records[0]["values"]["文件名称"], "关于启用的通知")
            self.assertEqual(window.records[1]["status"], "已停止，可重新识别")
            self.assertEqual(window.records[1].get("values") or {}, {})
            window.close()

    def test_import_lists_each_skipped_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            window = Window(tmp / "project.json")
            window.template_notice = None
            folder = tmp / "inbox"
            nested = folder / "子目录"
            nested.mkdir(parents=True)
            scan = folder / "scan.pdf"
            scan.write_bytes(Path(example_scan()).read_bytes())
            (folder / "说明.txt").write_text("notes", encoding="utf-8")
            (nested / "表格.docx").write_text("x", encoding="utf-8")
            window.add_paths([str(scan)])

            def checks(box):
                self.assertEqual(box.windowTitle(), "部分文件未导入")
                body = box.text() + "\n" + box.informativeText()
                self.assertIn("已跳过 3 个文件。", body)
                self.assertIn("scan.pdf", body)
                self.assertIn("文件已在列表中", body)
                self.assertIn("说明.txt", body)
                self.assertIn("表格.docx", body)
                self.assertIn("不支持的文件格式", body)

            self._click_dialog("关闭", checks)
            with patch(
                "app.QFileDialog.getExistingDirectory", return_value=str(folder)
            ):
                window.import_folder()
            self.assertEqual(
                [Path(record["path"]).name for record in window.records], ["scan.pdf"]
            )
            fresh = tmp / "新文件.pdf"
            fresh.write_bytes(b"%PDF")
            with patch("app.show_skipped_files") as skipped:
                window.add_paths([str(fresh)], report=True)
            skipped.assert_not_called()
            self.assertEqual(len(window.records), 2)
            note = tmp / "备注.md"
            note.write_text("no", encoding="utf-8")

            def file_checks(box):
                body = box.text() + "\n" + box.informativeText()
                self.assertIn("已跳过 2 个文件。", body)
                self.assertIn("scan.pdf", body)
                self.assertIn("文件已在列表中", body)
                self.assertIn("备注.md", body)
                self.assertIn("不支持的文件格式", body)

            self._click_dialog("关闭", file_checks)
            with patch(
                "app.QFileDialog.getOpenFileNames",
                return_value=([str(scan), str(note)], ""),
            ):
                window.import_files()
            self.assertEqual(len(window.records), 2)
            window.close()

    def test_settings_has_no_custom_review_mode(self):
        from PySide6.QtWidgets import QDialog, QLabel

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bad = tmp / "bad.xlsx"
            bad.write_bytes(b"not-a-workbook")
            state = self._write_state(
                tmp / "project.json",
                use_template=True,
                template_path=str(bad),
                template_sheet="管理类_件",
            )
            window = Window(state)
            seen = {}

            def grab(dialog):
                texts = []
                for combo in dialog.findChildren(QComboBox):
                    texts.extend(combo.itemText(i) for i in range(combo.count()))
                texts.extend(widget.text() for widget in dialog.findChildren(QLabel))
                seen["texts"] = texts
                return QDialog.Rejected

            with (
                patch("app.QMessageBox.warning"),
                patch("app.QDialog.exec", grab),
            ):
                window.settings()
            joined = "\n".join(seen["texts"])
            self.assertNotIn("自定义", joined)
            self.assertNotIn("自定义核对", window.template_notice)
            self.assertFalse(window.export_btn.isEnabled())
            self.assertFalse(window.template_banner.isHidden())
            window.close()

    def test_last_output_folder_is_restored(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            remembered = tmp / "上次输出"
            remembered.mkdir()
            state = self._write_state(
                tmp / "project.json",
                use_template=True,
                template_path=str(example_template()),
                template_sheet="管理类_件",
                export_folder=str(remembered),
            )
            window = Window(state)
            self.assertEqual(window.export_folder, str(remembered))
            window.records = [
                {
                    "path": str(tmp / "甲.pdf"),
                    "status": "已核对",
                    "text": "甲",
                    "values": {},
                }
            ]
            with patch(
                "app.QFileDialog.getExistingDirectory", return_value=""
            ) as choose:
                window.export()
            self.assertEqual(choose.call_args.args[2], str(remembered))
            chosen = tmp / "新目录"
            chosen.mkdir()

            def block(_indexes):
                saved = json.loads(state.read_text(encoding="utf-8"))
                self.assertEqual(saved["export_folder"], str(chosen))
                raise RuntimeError("stop before writing")

            with (
                patch("app.QFileDialog.getExistingDirectory", return_value=str(chosen)),
                patch.object(window, "_start_export", block),
            ):
                with self.assertRaises(RuntimeError):
                    window.export()
            window.close()
            restored = Window(state)
            self.assertEqual(restored.export_folder, str(chosen))
            restored.close()


if __name__ == "__main__":
    unittest.main()
