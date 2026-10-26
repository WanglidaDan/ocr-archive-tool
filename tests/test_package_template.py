"""Base package layout: no template in the zip, inject script, beside-program path."""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication
from app import Window
from fixtures import example_template
from tools.inject_template import inject, main as inject_main
from tools.smoke_batch import write_pdfs
from tools.stage_windows_dist import archive_names, make_zip, prepare_dist


class PackageTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_base_zip_drops_the_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "ArchiveDesk"
            (dist / "_internal").mkdir(parents=True)
            (dist / "ArchiveDesk.exe").write_bytes(b"MZ")
            (dist / "_internal" / "ch_det.onnx").write_bytes(b"onnx")
            templates = dist / "templates"
            templates.mkdir()
            (templates / "standard_template.xlsx").write_bytes(b"PK")
            prepare_dist(dist, copy_dlls=False)
            zip_path = Path(tmp) / "ArchiveDesk-base.zip"
            make_zip(dist, zip_path)
            names = archive_names(zip_path)
            self.assertTrue(
                any(name.endswith("ArchiveDesk/Start.bat") for name in names)
            )
            self.assertTrue(any(name.endswith("使用说明.txt") for name in names))
            self.assertTrue(
                any(name.endswith("请将标准模板放在这里.txt") for name in names)
            )
            self.assertFalse(any(name.lower().endswith(".xlsx") for name in names))

    def test_inject_requires_a_template_and_rewrites_the_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            dist = folder / "ArchiveDesk"
            dist.mkdir()
            (dist / "ArchiveDesk.exe").write_bytes(b"MZ")
            package = folder / "base.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.write(dist / "ArchiveDesk.exe", "ArchiveDesk/ArchiveDesk.exe")
            missing = inject_main([str(package), str(folder / "no-such.xlsx")])
            self.assertEqual(missing, 1)
            output = folder / "with-template.zip"
            inject(package, example_template(), output)
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertIn("ArchiveDesk/templates/standard_template.xlsx", names)

    def test_smoke_pdfs_are_written_into_a_new_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_pdfs(Path(tmp) / "pdfs")
            self.assertEqual(len(paths), 10)
            self.assertTrue(all(path.is_file() for path in paths))

    def test_template_beside_the_program_wins_over_a_saved_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            beside = folder / "templates" / "standard_template.xlsx"
            beside.parent.mkdir()
            beside.write_bytes(Path(example_template()).read_bytes())
            state = folder / "project.json"
            state.write_text(
                json.dumps(
                    {
                        "fields": [
                            "文件名称",
                            "文号",
                            "日期",
                            "责任单位",
                            "页数",
                            "备注",
                        ],
                        "records": [],
                        "use_template": False,
                        "template_path": str(folder / "saved-missing.xlsx"),
                    }
                ),
                encoding="utf-8",
            )
            with patch("app.program_template_path", return_value=beside):
                window = Window(state)
            self.assertTrue(window.use_template)
            self.assertEqual(window.template_path, str(beside))
            self.assertIsNone(window.template_notice)
            window.close()


if __name__ == "__main__":
    unittest.main()
