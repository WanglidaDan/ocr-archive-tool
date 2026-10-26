"""Ten synthetic PDFs through import, recognition, and one-click export."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import csv
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


def write_batch_pdfs(folder, page_counts=None):
    """Ten PDFs. Each document is one to five pages and still one Excel."""
    if page_counts is None:
        page_counts = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for number, count in enumerate(page_counts, 1):
        pages = [
            _page_image(
                [
                    f"文件名称：归档通知{number:02d}",
                    "文号：档发〔2026〕12号",
                    "日期：2026年10月26日",
                    "责任单位：示例单位A",
                ]
            )
            for _page in range(count)
        ]
        path = folder / f"file-{number:02d}.pdf"
        _write_pdf(path, pages)
        paths.append(path)
    return paths


def _cpu_description():
    text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    model = "unknown"
    count = 0
    for line in text.splitlines():
        if line.startswith("model name"):
            model = line.split(":", 1)[1].strip()
            count += 1
    if count == 0:
        count = os.cpu_count() or 0
    return f"{model} × {count}"


class BatchExportFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def _wait(self, window, timeout, seen=None):
        deadline = time.monotonic() + timeout
        started = time.monotonic()
        noticed = set()
        while not window.busy() and time.monotonic() - started < 2:
            self.app.processEvents()
            time.sleep(0.01)
        while window.busy() and time.monotonic() < deadline:
            if seen is not None:
                text = window.status.text()
                if text and text not in noticed:
                    noticed.add(text)
                    seen.append(text)
                if window.stop_btn.isEnabled() and "STOP-ENABLED" not in noticed:
                    noticed.add("STOP-ENABLED")
                    seen.append("STOP-ENABLED")
                # The window stays hidden in this test, so isVisible() is false
                # even after setVisible(True). The bar's own format still changes.
                formatted = "FORMAT " + window.progress.format()
                if formatted not in noticed:
                    noticed.add(formatted)
                    seen.append(formatted)
                span = f"RANGE {window.progress.minimum()}-{window.progress.maximum()}"
                if span not in noticed:
                    noticed.add(span)
                    seen.append(span)
            self.app.processEvents()
            time.sleep(0.02)
        self.assertFalse(window.busy(), window.status.text())

    def test_ten_pdfs_export_ten_matching_workbooks(self):
        page_counts = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sources = write_batch_pdfs(tmp / "in", page_counts)
            self.assertEqual(len(sources), 10)
            window = Window(tmp / "project.json")
            template = example_template()
            meta = inspect_template(template, "管理类_件")
            window.use_template = True
            window.template_notice = None
            window.template_path = str(template)
            window.template_sheet = "管理类_件"
            window.fields = meta["headers"]
            window.choices = meta["choices"]
            window.build_form()
            window._apply_export_enabled()
            window.add_paths([str(path) for path in sources])
            self.assertEqual(len(window.records), 10)
            self.assertFalse(window.overwrite_box.isChecked())
            seen = []
            started = time.monotonic()
            window.start()
            self._wait(window, 300, seen)
            ocr_seconds = time.monotonic() - started
            self.app.processEvents()
            statuses = [record["status"] for record in window.records]
            self.assertTrue(
                all(status in ("已识别", "待核对") for status in statuses),
                list(
                    zip(statuses, [record.get("warning") for record in window.records])
                ),
            )
            pending = statuses.count("待核对")
            self.assertEqual(
                [record["pages"] for record in window.records],
                page_counts,
            )
            progress = "\n".join(seen)
            self.assertIn("正在识别 第1个/共10个", progress)
            self.assertIn("正在识别 第10个/共10个", progress)
            self.assertIn("FORMAT 第%v个/共%m个", seen)
            self.assertIn("RANGE 0-10", seen)
            self.assertIn("STOP-ENABLED", seen)
            output = tmp / "out"
            output.mkdir()
            remembered = tmp / "上次目录"
            remembered.mkdir()
            window.export_folder = str(remembered)
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
            self.assertTrue(export_button.isEnabled())
            self.assertEqual(export_button.objectName(), "primary")
            self.assertNotEqual(summary_button.objectName(), "primary")
            summaries = []

            def capture(parent, summary, folder, can_retry):
                summaries.append((summary, folder, can_retry))
                return "close"

            export_started = time.monotonic()
            with (
                patch(
                    "app.QFileDialog.getExistingDirectory",
                    return_value=str(output),
                ) as choose,
                patch("app.confirm_unreviewed", return_value=True) as confirm,
                patch("app.show_export_result", capture),
                patch("app.QMessageBox.warning") as warning,
                patch("app.QMessageBox.question") as question,
            ):
                export_button.click()
                self._wait(window, 60)
                self.app.processEvents()
            export_seconds = time.monotonic() - export_started
            question.assert_not_called()
            warning.assert_not_called()
            if pending:
                confirm.assert_called_once()
                self.assertEqual(confirm.call_args.args[1], pending)
            else:
                confirm.assert_not_called()
            self.assertEqual(choose.call_args.args[2], str(remembered))
            self.assertEqual(window.export_folder, str(output))
            self.assertEqual(len(summaries), 1)
            report = summaries[0][0]
            self.assertIn("成功 10 份，失败 0 份。", report)
            self.assertNotIn("失败：", report)
            names = sorted(
                path.name
                for path in output.glob("*.xlsx")
                if not path.name.startswith("导出清单_")
            )
            self.assertEqual(len(list(output.glob("导出清单_*.xlsx"))), 1)
            self.assertEqual(
                names, [f"file-{number:02d}.xlsx" for number in range(1, 11)]
            )
            with (output / "处理清单.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 10)
            self.assertEqual(
                sum(row["状态"] == "成功" for row in rows)
                + sum(row["状态"] == "失败" for row in rows),
                10,
            )
            self.assertEqual(
                [row["对应Excel名"] for row in rows],
                [f"file-{number:02d}.xlsx" for number in range(1, 11)],
            )
            by_stem = {path.stem: path for path in sources}
            required = (
                "通过 · 工作表名称和顺序一致",
                "通过 · 列名、顺序和表头文字一致",
                "通过 · 表头字体一致",
                "通过 · 表头边框一致",
                "通过 · 合并单元格一致",
                "通过 · 列宽一致",
            )
            for workbook in sorted(output.glob("*.xlsx")):
                if workbook.name.startswith("导出清单_"):
                    continue
                self.assertIn(workbook.stem, by_stem)
                ok, lines = compare_workbooks(template, workbook)
                self.assertTrue(ok, workbook.name + "\n" + "\n".join(lines))
                for phrase in required:
                    self.assertIn(phrase, lines)
                book = load_workbook(workbook)
                self.assertEqual(book["管理类_件"]["H2"].value, "30年")
                self.assertEqual(book["管理类_件"]["I2"].value, "纸质")
                self.assertIsNone(book["管理类_卷"]["A2"].value)
                self.assertIsNone(book["管理类_卷内件"]["A2"].value)
                book.close()
            total = ocr_seconds + export_seconds
            cpu = _cpu_description()
            message = (
                f"BATCH_TIME ocr={ocr_seconds:.2f}s export={export_seconds:.2f}s "
                f"total={total:.2f}s files=10 pages={sum(page_counts)} cpu={cpu}"
            )
            print("\n" + message + "\n", flush=True)
            Path("/tmp/batch-timing.txt").write_text(message + "\n", encoding="utf-8")
            window.close()


if __name__ == "__main__":
    unittest.main()
