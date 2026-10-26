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

from fixtures import example_template
from PySide6.QtWidgets import QApplication

from app import Window
from tools import offline_guard
from tools.inject_template import inject
from tools.inject_template import main as inject_main
from tools.smoke_batch import run_packaged, write_pdfs
from tools.stage_windows_dist import archive_names, make_zip, prepare_dist
from tools.verify_base_zip import inspect_zip
from tools.verify_base_zip import main as verify_main


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

    def test_peak_memory_reading_is_positive(self):
        from tools.smoke_batch import peak_memory_bytes

        self.assertGreater(peak_memory_bytes(), 0)

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

    def test_offline_guard_refuses_remote_and_restores(self):
        import socket

        original = socket.socket.connect
        self.addCleanup(offline_guard.uninstall)
        offline_guard.uninstall()
        offline_guard.install()
        offline_guard.install()

        class Dummy:
            pass

        with self.assertRaises(OSError) as raised:
            socket.socket.connect(Dummy(), ("8.8.8.8", 53))
        self.assertIn("离线模式拒绝联网", str(raised.exception))
        self.assertEqual(len(offline_guard.remote_attempts), 1)
        with self.assertRaises(Exception) as loopback:
            socket.socket.connect(Dummy(), ("127.0.0.1", 9))
        self.assertNotIn("离线模式拒绝联网", str(loopback.exception))
        with self.assertRaises(Exception) as local_name:
            socket.socket.connect(Dummy(), ("localhost", 9))
        self.assertNotIn("离线模式拒绝联网", str(local_name.exception))
        offline_guard.uninstall()
        self.assertIs(socket.socket.connect, original)
        self.assertEqual(offline_guard.remote_attempts, [])

    def test_verify_base_zip_requires_runtime_dlls_and_rejects_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bad = folder / "bad.zip"
            with zipfile.ZipFile(bad, "w") as archive:
                archive.writestr("ArchiveDesk/ArchiveDesk.exe", b"MZ")
                archive.writestr("ArchiveDesk/templates/standard_template.xlsx", b"PK")
            info = inspect_zip(bad)
            self.assertTrue(info["xlsx"])
            self.assertIn("vcruntime140.dll", info["missing_dlls"])
            self.assertEqual(verify_main([str(bad)]), 1)
            good = folder / "good.zip"
            with zipfile.ZipFile(good, "w") as archive:
                archive.writestr("ArchiveDesk/vcruntime140.dll", b"a")
                archive.writestr("ArchiveDesk/_internal/vcruntime140_1.dll", b"b")
                archive.writestr("ArchiveDesk/msvcp140.dll", b"c")
                archive.writestr(
                    "ArchiveDesk/templates/请将标准模板放在这里.txt", "note"
                )
            info = inspect_zip(good)
            self.assertEqual(info["missing_dlls"], [])
            self.assertEqual(info["xlsx"], [])
            self.assertEqual(
                info["required_dlls"]["vcruntime140.dll"],
                "ArchiveDesk/vcruntime140.dll",
            )
            self.assertEqual(verify_main([str(good)]), 0)

    def test_packaged_smoke_writes_a_report_without_a_console(self):
        self.addCleanup(offline_guard.uninstall)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = folder / "smoke-report.json"
            with patch("sys.stdout", None):
                code = run_packaged(
                    [
                        "--pdf-dir",
                        str(folder / "pdfs"),
                        "--out-dir",
                        str(folder / "out"),
                        "--report",
                        str(report),
                        "--template",
                        str(folder / "missing.xlsx"),
                    ]
                )
            self.assertEqual(code, 2)
            body = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(body["remote_socket_attempts"], 0)
            self.assertFalse(body["elevated"])
            self.assertIn("模板不存在", body["error"])


if __name__ == "__main__":
    unittest.main()
