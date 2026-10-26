import csv, os, sys, unittest, tempfile, zipfile, re
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_export import (
    LIST_COLUMNS,
    MANIFEST_COLUMNS,
    describe_batch,
    describe_excel_name,
    export_mapped_separate,
    export_separate,
    manifest_rows,
    write_export_list,
    write_manifest,
)
from extraction import extract_details
from fixtures import example_template

TEMPLATE = example_template()


class StrictBatchTests(unittest.TestCase):
    def test_per_document_classification_and_missing(self):
        for value in [
            "内部",
            "普通商密",
            "非涉密",
            "无密级",
            "油商密★",
            "油商密★★",
            "石油内部",
            "石油商密",
            "秘密",
            "机密",
            "绝密",
            "",
        ]:
            r = extract_details(value + "\n文件内容", ["密级"], 1)
            self.assertEqual(r[0]["密级"], value)
        self.assertEqual(
            extract_details("正文提到内部管理", ["密级"], 1)[0]["密级"], ""
        )
        self.assertEqual(
            extract_details("无标记", ["密级"], 1, additional={"密级": "内部"})[0][
                "密级"
            ],
            "",
        )

    def test_classification_conflict_and_position(self):
        v, e, w = extract_details(
            "--- 第 1 页 ---\n内部\n--- 第 2 页 ---\n普通商密", ["密级"], 2
        )
        self.assertEqual(v["密级"], "")
        self.assertEqual(e["密级"]["status"], "候选冲突")
        rows = [
            {
                "text": "内部",
                "page": 1,
                "confidence": 1,
                "boxes": [[[10, 700], [50, 700], [50, 720], [10, 720]]],
                "page_width": 600,
                "page_height": 800,
            }
        ]
        self.assertEqual(extract_details("", ["密级"], 1, rows)[0]["密级"], "")

    def test_one_workbook_per_file_and_no_overwrite(self):
        from openpyxl import load_workbook

        records = [
            {
                "path": "甲/同名.pdf",
                "values": {"题名": "第一份", "密级": "内部", "正本数量": "1"},
            },
            {
                "path": "乙/同名.pdf",
                "values": {"题名": "第二份", "密级": "普通商密", "正本数量": "1"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            results = export_separate(records, tmp, TEMPLATE, "管理类_件")
            self.assertEqual(len(results), 2)
            self.assertTrue(all(not r["error"] for r in results))
            self.assertEqual(Path(results[0]["output"]).name, "同名.xlsx")
            self.assertEqual(Path(results[1]["output"]).name, "同名(1).xlsx")
            self.assertNotEqual(results[0]["output"], results[1]["output"])
            for record, result in zip(records, results):
                b = load_workbook(result["output"])
                self.assertEqual(b["管理类_件"]["D2"].value, record["values"]["题名"])
                self.assertIsNone(b["管理类_件"]["D3"].value)
                from copy import copy

                original = load_workbook(TEMPLATE)
                for x, y in zip(original["管理类_件"][2], b["管理类_件"][2]):
                    for attr in [
                        "font",
                        "fill",
                        "border",
                        "alignment",
                        "protection",
                        "number_format",
                    ]:
                        self.assertEqual(copy(getattr(x, attr)), copy(getattr(y, attr)))
                with (
                    zipfile.ZipFile(TEMPLATE) as a,
                    zipfile.ZipFile(result["output"]) as z,
                ):
                    self.assertEqual(a.namelist(), z.namelist())
                    self.assertEqual(
                        [n for n in a.namelist() if a.read(n) != z.read(n)],
                        ["xl/worksheets/sheet1.xml"],
                    )
                    # Remove only the written data cells; every other byte of the
                    # changed worksheet, including headers and validators, matches.
                    aa = a.read("xl/worksheets/sheet1.xml").decode()
                    zz = z.read("xl/worksheets/sheet1.xml").decode()
                    for address in ["D2", "K2", "T2"]:
                        pattern = r'<c\b[^>]*\br="' + address + r'"[^>]*(?:/>|>.*?</c>)'
                        aa = re.sub(pattern, "", aa, flags=re.S)
                        zz = re.sub(pattern, "", zz, flags=re.S)
                    self.assertEqual(aa, zz)
            old = Path(results[0]["output"]).read_bytes()
            more = export_separate(records[:1], tmp, TEMPLATE, "管理类_件")
            self.assertEqual(Path(more[0]["output"]).name, "同名(2).xlsx")
            self.assertNotEqual(more[0]["output"], results[0]["output"])
            self.assertEqual(Path(results[0]["output"]).read_bytes(), old)

    def test_bad_file_does_not_stop_other_files(self):
        records = [
            {"path": "bad.pdf", "values": {"密级": "未知密级"}},
            {"path": "good.pdf", "values": {"密级": "非涉密"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            results = export_separate(records, tmp, TEMPLATE, "管理类_件")
            self.assertTrue(results[0]["error"])
            self.assertFalse(results[1]["error"])
            self.assertEqual(Path(results[1]["output"]).name, "good.xlsx")
            self.assertEqual(
                [path.name for path in Path(tmp).glob("*.xlsx")], ["good.xlsx"]
            )
            summary = describe_batch(
                [
                    {**records[0], "status": "待核对", "text": "x"},
                    {**records[1], "status": "已核对", "text": "y"},
                    {"path": "miss.pdf", "status": "处理失败", "text": ""},
                ],
                results,
            )
            self.assertIn("成功 1 份，失败 2 份。", summary)
            self.assertIn("bad.pdf：", summary)
            self.assertIn("miss.pdf：识别失败，未导出", summary)
            self.assertNotIn("待核对", summary)

    def test_summary_counts_review_separately_from_failure(self):
        text = describe_batch(
            [
                {"path": "a.pdf", "status": "待核对", "text": "a"},
                {"path": "b.pdf", "status": "已核对", "text": "b"},
            ],
            [
                {"source": "a.pdf", "output": "a.xlsx", "error": ""},
                {"source": "b.pdf", "output": "b.xlsx", "error": ""},
            ],
        )
        self.assertIn("成功 2 份，失败 0 份。", text)
        self.assertNotIn("失败：", text)

    def test_stop_before_start_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                export_separate(
                    [{"path": "a.pdf", "values": {}}],
                    tmp,
                    TEMPLATE,
                    "管理类_件",
                    cancelled=lambda: True,
                ),
                [],
            )
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_same_stem_from_two_folders_gets_numbered_suffix(self):
        records = [
            {
                "path": "收文/发文001.pdf",
                "values": {"题名": "第一份", "密级": "非涉密"},
            },
            {
                "path": "发文/发文001.pdf",
                "values": {"题名": "第二份", "密级": "非涉密"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            results = export_separate(records, tmp, TEMPLATE, "管理类_件")
            self.assertEqual(
                [item["excel_name"] for item in results],
                ["发文001.xlsx", "发文001(1).xlsx"],
            )
            self.assertTrue(all(not item["error"] for item in results))
            rows = manifest_rows(records, results)
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                sum(row["状态"] == "成功" for row in rows)
                + sum(row["状态"] == "失败" for row in rows),
                len(records),
            )
            self.assertEqual(
                [row["对应Excel名"] for row in rows],
                ["发文001.xlsx", "发文001(1).xlsx"],
            )

    def test_overwrite_replaces_existing_file_but_not_the_sibling(self):
        from openpyxl import load_workbook

        seed = {
            "path": "旧/发文001.pdf",
            "values": {"题名": "旧文件", "密级": "非涉密"},
        }
        records = [
            {"path": "甲/发文001.pdf", "values": {"题名": "第一份", "密级": "非涉密"}},
            {"path": "乙/发文001.pdf", "values": {"题名": "第二份", "密级": "非涉密"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            export_separate([seed], tmp, TEMPLATE, "管理类_件")
            original = (Path(tmp) / "发文001.xlsx").read_bytes()
            kept = export_separate(records, tmp, TEMPLATE, "管理类_件", overwrite=False)
            self.assertEqual(kept[0]["excel_name"], "发文001(1).xlsx")
            self.assertEqual(kept[1]["excel_name"], "发文001(2).xlsx")
            self.assertEqual((Path(tmp) / "发文001.xlsx").read_bytes(), original)
            replaced = export_separate(
                records[:1], tmp, TEMPLATE, "管理类_件", overwrite=True
            )
            self.assertEqual(replaced[0]["excel_name"], "发文001.xlsx")
            self.assertNotEqual((Path(tmp) / "发文001.xlsx").read_bytes(), original)
            book = load_workbook(replaced[0]["output"])
            self.assertEqual(book["管理类_件"]["D2"].value, "第一份")
            book.close()
            sibling = (Path(tmp) / "发文001(1).xlsx").read_bytes()
            again = export_separate(records, tmp, TEMPLATE, "管理类_件", overwrite=True)
            self.assertEqual(again[0]["excel_name"], "发文001.xlsx")
            self.assertEqual(again[1]["excel_name"], "发文001(1).xlsx")
            self.assertNotEqual((Path(tmp) / "发文001(1).xlsx").read_bytes(), sibling)

    def test_locked_workbook_is_one_failure_and_others_continue(self):
        records = [
            {"path": "locked.pdf", "values": {"密级": "非涉密", "题名": "被占用"}},
            {"path": "ok.pdf", "values": {"密级": "非涉密", "题名": "正常"}},
            {
                "path": "miss.pdf",
                "status": "处理失败",
                "warning": "PDF已加密，请先解密再导入。",
                "values": {},
            },
        ]
        real_replace = os.replace

        def locked(src, dst):
            if Path(dst).name.startswith("locked"):
                raise PermissionError("locked by Excel")
            return real_replace(src, dst)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("batch_export.os.replace", locked),
        ):
            results = export_separate(records, tmp, TEMPLATE, "管理类_件")
            self.assertEqual(len(results), 3)
            self.assertIn("无法写入 Excel，文件可能正被占用", results[0]["error"])
            self.assertFalse(results[1]["error"])
            self.assertIn("加密", results[2]["error"])
            names = sorted(path.name for path in Path(tmp).glob("*.xlsx"))
            self.assertEqual(names, ["ok.xlsx"])
            rows = manifest_rows(records, results)
            self.assertEqual(
                sum(row["状态"] == "成功" for row in rows)
                + sum(row["状态"] == "失败" for row in rows),
                3,
            )
            summary = describe_batch(records, results)
            self.assertIn("成功 1 份，失败 2 份。", summary)
            self.assertIn(
                "locked.pdf：无法写入 Excel，文件可能正被占用：locked.xlsx", summary
            )
            self.assertIn("miss.pdf：PDF已加密，请先解密再导入。", summary)
            manifest = write_manifest(tmp, records, results)
            self.assertEqual(manifest.name, "处理清单.csv")
            with manifest.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(tuple(reader.fieldnames), MANIFEST_COLUMNS)
                written = list(reader)
            self.assertEqual(
                [row["文件名"] for row in written], ["locked.pdf", "ok.pdf", "miss.pdf"]
            )
            self.assertEqual(written[1]["对应Excel名"], "ok.xlsx")
            self.assertEqual(written[0]["状态"], "失败")
            self.assertEqual(written[1]["状态"], "成功")

    def test_reserved_and_long_names_are_explained(self):
        long_name = "a" * 150 + ".pdf"
        records = [
            {"path": "CON.pdf", "values": {"密级": "非涉密", "题名": "保留名"}},
            {"path": long_name, "values": {"密级": "非涉密", "题名": "超长"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            results = export_separate(records, tmp, TEMPLATE, "管理类_件")
            self.assertEqual(results[0]["excel_name"], "_CON.xlsx")
            self.assertIn("保留名", results[0]["name_note"])
            self.assertEqual(len(Path(results[1]["excel_name"]).stem), 80)
            self.assertIn("截断", results[1]["name_note"])
            listed = write_export_list(tmp, records, results)
            self.assertTrue(listed.name.startswith("导出清单_"))
            book = __import__("openpyxl").load_workbook(listed)
            sheet = book.active
            headers = [cell.value for cell in sheet[1]]
            self.assertEqual(tuple(headers), LIST_COLUMNS)
            rows = list(sheet.iter_rows(min_row=2, values_only=True))
            self.assertEqual(rows[0][0], "CON.pdf")
            self.assertIn("_CON.xlsx", rows[0][1])
            self.assertIn("保留名", rows[0][1])
            self.assertEqual(rows[0][2], "成功")
            self.assertIn("截断", rows[1][1])
            self.assertIn(long_name, rows[1][0])
            book.close()
            self.assertIn("保留名", describe_excel_name("CON.pdf", "_CON.xlsx"))

    def test_template_removed_between_files_keeps_going(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            template = tmp / "模板.xlsx"
            template.write_bytes(Path(TEMPLATE).read_bytes())
            folder = tmp / "out"
            first = {
                "path": "甲.pdf",
                "status": "已核对",
                "text": "甲",
                "values": {"密级": "非涉密", "题名": "甲"},
            }
            second = {
                "path": "乙.pdf",
                "status": "已核对",
                "text": "乙",
                "values": {"密级": "非涉密", "题名": "乙"},
            }
            done = export_mapped_separate([first], folder, template, "管理类_件")
            template.unlink()
            failed = export_mapped_separate([second], folder, template, "管理类_件")
            self.assertFalse(done[0]["error"])
            self.assertIn("找不到模板", failed[0]["error"])
            self.assertNotIn("Error", failed[0]["error"])
            self.assertTrue((folder / "甲.xlsx").is_file())
            self.assertFalse(list(folder.glob("乙*.xlsx")))

    def test_permission_error_stays_chinese(self):
        records = [{"path": "只读.pdf", "values": {"密级": "非涉密"}}]

        def denied(*_args, **_kwargs):
            raise PermissionError(13, "Permission denied")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("batch_export.os.open", denied),
        ):
            results = export_separate(records, tmp, TEMPLATE, "管理类_件")
        self.assertIn("权限", results[0]["error"])
        self.assertNotIn("Errno", results[0]["error"])
        self.assertNotIn("Permission", results[0]["error"])


if __name__ == "__main__":
    unittest.main()
