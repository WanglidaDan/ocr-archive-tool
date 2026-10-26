"""P0 surfaces from the v2.1 redesign: banner, progress, import, confirm, results, retry."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

from app import (
    STYLE,
    ExportConfirmDialog,
    ExportResultDialog,
    ImportSummaryDialog,
    Window,
)
from fixtures import example_template


class RedesignP0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def test_template_problem_banner_greys_out_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bad = tmp / "bad.xlsx"
            bad.write_bytes(b"not a zip")
            state = tmp / "project.json"
            state.write_text(
                '{"fields": ["文件名称"], "records": [], "use_template": true, '
                '"template_path": "%s", "template_sheet": "管理类_件"}' % str(bad),
                encoding="utf-8",
            )
            window = Window(state)
            self.assertIn("模板有问题，暂时无法导出 Excel", window.template_notice)
            self.assertIn("无法读取", window.template_notice)
            self.assertIn("\n模板路径：" + str(bad), window.template_banner.text())
            self.assertFalse(window.export_btn.isEnabled())
            self.assertEqual(window.export_btn.objectName(), "disabledExport")
            self.assertIn("#E5E5EA", window.export_btn.styleSheet())
            self.assertIn("QLabel#banner {background:#FDECEA", STYLE)
            window.close()

    def test_progress_line_uses_pages_and_hides_eta_until_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(Path(tmp) / "project.json")
            window._page_rates = []
            window._file_rates = []
            window._page_mark = None
            window._seen_page = None
            window._update_progress_caption(
                "正在识别 第5个/共10个 · 示例-2024-收文-0005-合订本.pdf · 正在识别第 12/40 页"
            )
            self.assertIn("第 5/10 个", window.progress_caption.text())
            self.assertIn("第 12/40 页", window.progress_caption.text())
            self.assertNotIn("预计剩余", window.progress_caption.text())
            window._page_rates = [37 / 28]
            window._file_rates = [1.8]
            window._page_mark = None
            window._seen_page = None
            window._update_progress_caption(
                "正在识别 第5个/共10个 · 示例-2024-收文-0005-合订本.pdf · 正在识别第 12/40 页"
            )
            self.assertIn("预计剩余约 46 秒", window.progress_caption.text())
            window.set_busy(True)
            self.assertEqual(window.progress.format(), "第%v个/共%m个")
            self.assertFalse(window.progress_caption.isHidden())
            window.close()

    def test_import_summary_lists_reasons_and_can_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(Path(tmp) / "project.json")
            skipped = [
                (str(Path(tmp) / "甲.pdf"), "文件已在列表中"),
                (str(Path(tmp) / "说明.docx"), "不支持的文件格式"),
            ]
            dialog = ImportSummaryDialog(window, 8, skipped)
            body = dialog.informativeText()
            self.assertIn("已导入 8 份 · 跳过 2 项", dialog.text())
            self.assertIn("已跳过 2 个文件。", body)
            self.assertIn("重复", body)
            self.assertIn("文件已在列表中", body)
            self.assertIn("格式不支持", body)
            self.assertIn("不支持的文件格式", body)
            labels = [button.text() for button in dialog.findChildren(QPushButton)]
            self.assertIn("复制跳过清单", labels)
            self.assertIn("开始识别 8 份", labels)
            dialog._copy()
            copied = QApplication.clipboard().text()
            self.assertIn("甲.pdf", copied)
            self.assertIn("说明.docx", copied)
            self.assertIn("不支持的文件格式", copied)
            window.close()

    def test_export_confirm_names_only_the_unreviewed_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            window = Window(tmp / "project.json")
            window.use_template = True
            window.export_folder = str(tmp / "上次")
            window._confirm_export_count = 8
            dialog = ExportConfirmDialog(window, 5)
            titles = [label.text() for label in dialog.findChildren(QLabel)]
            joined = "\n".join(titles)
            self.assertIn("导出 8 份 Excel", joined)
            self.assertIn("还有 5 份待核对", dialog.text())
            self.assertIn("有 5 份尚未核对。", dialog.text())
            self.assertNotIn("已识别", dialog.text())
            self.assertFalse(dialog.overwrite.isChecked())
            self.assertIn(str(tmp / "上次"), joined)
            labels = [button.text() for button in dialog.findChildren(QPushButton)]
            self.assertEqual(labels[-2:], ["返回", "继续"])
            window.close()

    def test_result_table_lists_each_file_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(Path(tmp) / "project.json")
            rows = [
                {
                    "源文件路径": r"D:\一月\示例-2024-收文-0001.pdf",
                    "导出文件名": "示例-2024-收文-0001.xlsx",
                    "结果": "成功",
                    "原因": "",
                    "建议操作": "无需处理",
                },
                {
                    "源文件路径": r"D:\一月\示例-2024-收文-0004.pdf",
                    "导出文件名": "",
                    "结果": "失败",
                    "原因": "磁盘空间不足",
                    "建议操作": "请清理磁盘空间后重试",
                },
                {
                    "源文件路径": r"D:\一月\CON.pdf",
                    "导出文件名": "_CON.xlsx（源文件名“CON”是 Windows 保留名，已改为“_CON”）",
                    "结果": "成功",
                    "原因": "",
                    "建议操作": "请核对导出文件名",
                },
            ]
            summary = (
                "成功 2 份，失败 1 份。\n失败：\n示例-2024-收文-0004.pdf：磁盘空间不足"
            )
            dialog = ExportResultDialog(window, summary, rows, True)
            joined = "\n".join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn("成功 2 · 失败 1 · 共 3", joined)
            self.assertIn("成功 2 份，失败 1 份。", dialog.text())
            table = dialog.findChild(QTableWidget, "resultTable")
            self.assertEqual(table.item(1, 2).text(), "失败")
            self.assertEqual(table.item(1, 3).text(), "磁盘空间不足")
            self.assertIn("保留名", table.item(2, 3).text())
            labels = [button.text() for button in dialog.findChildren(QPushButton)]
            self.assertIn("只重试失败项（1）", labels)
            self.assertIn("打开输出文件夹", labels)
            self.assertIn("导出清单_时间.xlsx", joined)
            window.close()

    def test_retry_button_counts_failures_without_touching_successes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            window = Window(tmp / "project.json")
            window.records = [
                {
                    "path": str(tmp / "甲.pdf"),
                    "status": "已识别",
                    "text": "已经识别",
                    "values": {"文件名称": "甲"},
                },
                {
                    "path": str(tmp / "乙.pdf"),
                    "status": "失败",
                    "text": "",
                    "warning": "PDF已加密，请先解密再导入。",
                    "values": {},
                },
            ]
            window.current = 1
            window.refresh()
            window.load_record()
            self.assertEqual(window.retry_btn.text(), "只重试失败项（1）")
            self.assertFalse(window.fail_box.isHidden())
            self.assertIn("PDF已加密", window.fail_reason.text())
            seen = []
            window.launch_jobs = lambda jobs: seen.append(jobs)
            window.export_folder = str(tmp)
            window.retry_failed()
            self.assertEqual(seen, [[(1, str(tmp / "乙.pdf"))]])
            window.close()

    def test_deleted_template_before_export_puts_the_path_on_its_own_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            template = tmp / "模板.xlsx"
            template.write_bytes(Path(example_template()).read_bytes())
            state = tmp / "project.json"
            window = Window(state)
            window.use_template = True
            window.template_notice = None
            window.template_path = str(template)
            window.template_sheet = "管理类_件"
            window._apply_export_enabled()
            window.records = [
                {
                    "path": str(tmp / "甲.pdf"),
                    "status": "已核对",
                    "text": "甲",
                    "values": {},
                }
            ]
            template.unlink()
            with (
                patch("app.QMessageBox.warning") as warning,
                patch(
                    "app.QFileDialog.getExistingDirectory",
                    return_value=str(tmp / "out"),
                ),
            ):
                window.export()
            message = warning.call_args.args[2]
            self.assertIn("模板有问题", message)
            self.assertIn("找不到模板", message)
            self.assertIn("\n模板路径：" + str(template), message)
            self.assertNotIn(str(template), message.splitlines()[0])
            self.assertIn("\n模板路径：" + str(template), window.template_banner.text())
            self.assertFalse(window.export_btn.isEnabled())
            window.close()

    def test_show_skipped_files_still_reports_the_skip_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(Path(tmp) / "project.json")
            dialogs = []

            def grab(parent, skipped, added=0):
                dialogs.append((added, skipped))

            with patch("app.show_skipped_files", grab):
                window.add_paths([str(Path(tmp) / "笔记.txt")], report=True)
            self.assertEqual(dialogs[0][0], 0)
            self.assertIn("不支持的文件格式", dialogs[0][1][0][1])
            window.close()


if __name__ == "__main__":
    unittest.main()
