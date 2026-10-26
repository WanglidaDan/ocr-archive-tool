import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from template_io import inspect_template, export_template
from fixtures import example_template

TEMPLATE = example_template()


class TemplateTests(unittest.TestCase):
    def test_schema_preserved_with_real_date_types(self):
        from openpyxl import load_workbook

        meta = inspect_template(TEMPLATE)
        self.assertEqual(len(meta["headers"]), 30)
        self.assertIn("永久", meta["choices"]["保管期限"])
        record = {
            "values": {
                "题名": "=1+1",
                "文件日期": "2026年10月26日",
                "页数": "4",
                "年度": "2026",
                "责任者": "档案馆",
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "output.xlsx"
            export_template(p, [record], TEMPLATE, "管理类_件")
            a = load_workbook(TEMPLATE)
            b = load_workbook(p)
            self.assertEqual(a.sheetnames, b.sheetnames)
            for aa, bb in zip(a, b):
                self.assertEqual([c.value for c in aa[1]], [c.value for c in bb[1]])
                self.assertEqual(
                    aa.data_validations.to_tree().attrib,
                    bb.data_validations.to_tree().attrib,
                )
                self.assertEqual(str(aa.data_validations), str(bb.data_validations))
            ws = b["管理类_件"]
            self.assertEqual(ws["D2"].data_type, "s")
            self.assertEqual(ws["F2"].value, "2026-10-26")
            self.assertEqual(ws["S2"].value, 4)
            self.assertEqual(list(a.defined_names), list(b.defined_names))

    def test_invalid_dictionary_and_date_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for values in [
                {"密级": "未定义密级"},
                {"文件日期": "2026年13月1日"},
                {"年度": "1899"},
                {"页数": "4.5"},
            ]:
                with self.assertRaises(ValueError):
                    export_template(
                        Path(tmp) / "bad.xlsx",
                        [{"values": values}],
                        TEMPLATE,
                        "管理类_件",
                    )

    def test_all_catalog_sheets_supported(self):
        for sheet, count in [
            ("管理类_件", 30),
            ("管理类_卷", 28),
            ("管理类_卷内件", 24),
        ]:
            self.assertEqual(len(inspect_template(TEMPLATE, sheet)["headers"]), count)

    def test_formula_validation_bounds_do_not_crash(self):
        from openpyxl import Workbook, load_workbook
        from openpyxl.worksheet.datavalidation import DataValidation
        from fixtures import _style_blank_row

        def build(path, date_bounds, page_bounds):
            wb = Workbook()
            ws = wb.active
            ws.title = "目录"
            for col, header in enumerate(["文件日期", "页数"], 1):
                ws.cell(1, col, header)
            _style_blank_row(ws, 2)
            dates = DataValidation(
                type="date",
                operator="between",
                formula1=date_bounds[0],
                formula2=date_bounds[1],
                allow_blank=True,
            )
            dates.add("A2:A20")
            ws.add_data_validation(dates)
            pages = DataValidation(
                type="whole",
                operator="between",
                formula1=page_bounds[0],
                formula2=page_bounds[1],
                allow_blank=True,
            )
            pages.add("B2:B20")
            ws.add_data_validation(pages)
            wb.save(path)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            formula = tmp / "formula.xlsx"
            build(formula, ("TODAY()", "$Z$1"), ("SUM(A1)", "Sheet1!B1"))
            out = tmp / "out.xlsx"
            export_template(
                out,
                [{"values": {"文件日期": "2026-10-26", "页数": "4"}}],
                formula,
                "目录",
            )
            book = load_workbook(out)
            self.assertEqual(book.active["A2"].value, "2026-10-26")
            self.assertEqual(book.active["B2"].value, 4)

            bounded = tmp / "bounded.xlsx"
            build(bounded, ("36526", "55153"), ("0", "10"))
            with self.assertRaises(ValueError):
                export_template(
                    tmp / "late.xlsx",
                    [{"values": {"文件日期": "2099-01-01"}}],
                    bounded,
                    "目录",
                )
            with self.assertRaises(ValueError):
                export_template(
                    tmp / "many.xlsx", [{"values": {"页数": "11"}}], bounded, "目录"
                )
            export_template(
                tmp / "ok.xlsx",
                [{"values": {"文件日期": "2026-10-26", "页数": "4"}}],
                bounded,
                "目录",
            )


if __name__ == "__main__":
    unittest.main()
