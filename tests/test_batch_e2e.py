"""Ten synthetic PDFs through import, recognition, and one-click export."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import io
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitz
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QApplication, QPushButton
from app import Window, STYLE
from fixtures import cjk_font_path, example_template
from template_io import inspect_template
from tools.compare_template import compare_workbooks


def _page_image(lines):
    font = ImageFont.truetype(str(cjk_font_path()), 72)
    image = Image.new("RGB", (1800, 900), "white")
    draw = ImageDraw.Draw(image)
    y = 80
    for line in lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 140
    return image


def _write_pdf(path, images):
    document = fitz.open()
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page = document.new_page(width=image.width, height=image.height)
        page.insert_image(page.rect, stream=buffer.getvalue())
    document.save(path)
    document.close()


def write_batch_pdfs(folder):
    """file-01.pdf … file-10.pdf. The last file has two pages and is still one document."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for number in range(1, 11):
        pages = [
            _page_image(
                [
                    f"文件名称：归档通知{number:02d}",
                    "文号：档发〔2026〕12号",
                    "日期：2026年10月26日",
                    "责任单位：示例单位A",
                ]
            )
        ]
        if number == 10:
            pages.append(
                _page_image(
                    [
                        "文件名称：归档通知10续页",
                        "文号：档发〔2026〕12号",
                        "日期：2026年10月26日",
                        "责任单位：示例单位A",
                    ]
                )
            )
        path = folder / f"file-{number:02d}.pdf"
        _write_pdf(path, pages)
        paths.append(path)
    return paths


class BatchExportFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def _wait(self, window, timeout):
        deadline = time.monotonic() + timeout
        while window.busy() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        self.assertFalse(window.busy(), window.status.text())

    def test_ten_pdfs_export_ten_matching_workbooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sources = write_batch_pdfs(tmp / "in")
            self.assertEqual(len(sources), 10)
            window = Window(tmp / "project.json")
            template = example_template()
            meta = inspect_template(template, "管理类_件")
            window.use_template = True
            window.template_path = str(template)
            window.template_sheet = "管理类_件"
            window.fields = meta["headers"]
            window.choices = meta["choices"]
            window.build_form()
            window.add_paths([str(path) for path in sources])
            self.assertEqual(len(window.records), 10)
            window.start()
            self._wait(window, 180)
            self.app.processEvents()
            self.assertEqual(
                [record["status"] for record in window.records],
                ["待核对"] * 10,
                [record.get("warning") for record in window.records],
            )
            self.assertEqual(
                [record["pages"] for record in window.records],
                [1] * 9 + [2],
            )
            output = tmp / "out"
            output.mkdir()
            export_button = next(
                button
                for button in window.findChildren(QPushButton)
                if button.text() == "导出 Excel"
            )
            summary_button = next(
                button
                for button in window.findChildren(QPushButton)
                if button.text() == "汇总导出（可选）"
            )
            self.assertEqual(export_button.objectName(), "primary")
            self.assertNotEqual(summary_button.objectName(), "primary")
            with (
                patch(
                    "app.QFileDialog.getExistingDirectory",
                    return_value=str(output),
                ),
                patch("app.QMessageBox.information") as information,
                patch("app.QMessageBox.warning") as warning,
                patch("app.QMessageBox.question") as question,
            ):
                export_button.click()
                self._wait(window, 60)
                self.app.processEvents()
            question.assert_not_called()
            warning.assert_not_called()
            self.assertTrue(information.called)
            report = information.call_args.args[2]
            self.assertEqual(information.call_args.args[1], "批量导出结果")
            self.assertIn("成功 10 份，失败 0 份，待核对 10 份。", report)
            names = sorted(path.name for path in output.glob("*.xlsx"))
            self.assertEqual(
                names, [f"file-{number:02d}.xlsx" for number in range(1, 11)]
            )
            by_stem = {path.stem: path for path in sources}
            for workbook in output.glob("*.xlsx"):
                self.assertIn(workbook.stem, by_stem)
                ok, lines = compare_workbooks(template, workbook)
                self.assertTrue(ok, workbook.name + "\n" + "\n".join(lines))
                book = load_workbook(workbook)
                self.assertEqual(book["管理类_件"]["H2"].value, "30年")
                self.assertEqual(book["管理类_件"]["I2"].value, "纸质")
                self.assertIsNone(book["管理类_卷"]["A2"].value)
                self.assertIsNone(book["管理类_卷内件"]["A2"].value)
                book.close()
            window.close()


if __name__ == "__main__":
    unittest.main()
