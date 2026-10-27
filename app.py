import json
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QPlainTextEdit,
    QLineEdit,
    QFormLayout,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QScrollArea,
    QTabWidget,
    QProgressBar,
    QAbstractItemView,
    QFrame,
    QComboBox,
    QSizePolicy,
    QCheckBox,
)
from batch_export import (
    describe_batch,
    export_mapped_separate,
    manifest_rows,
    write_export_list,
    write_manifest,
    write_summary,
)
from errors import chinese_message
from catalog_defaults import (
    DEFAULTS,
    DEFAULT_SHEET,
    effective_defaults,
    validate_defaults,
)
from unit_link import link_record
from extraction import canonical, normalize_date, extract_details
from template_io import inspect_template, export_template, standard_value
from core import DEFAULT_FIELDS, SUPPORTED, Processor, Cancelled, VERSION
from status_model import (
    FAILED,
    STOPPED,
    classify_recognition,
    needs_ocr,
    not_exportable,
)


ORIGINAL_TEMPLATE_SHA256 = "9eea9e889ec934fc5ca6e97083e089a45d2944848498810c2ca5cab956937ac5"

def require_original_template(path):
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError("无法读取原始 Excel 模板，请重新选择用户提供的原模板。") from error
    if digest not in {ORIGINAL_TEMPLATE_SHA256, "771a9a4905382921cc4839904cd0bd52a7d6e9a265983bcd77278247e00d42e2"}:
        raise ValueError("所选文件与已确认的 Excel 模板不一致，已停止导出。")


def program_directory():
    """Folder that contains the program. Frozen builds use the exe directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def program_template_path():
    """标准模板放在程序目录旁的 templates 文件夹，不打进安装包。"""
    return program_directory() / "templates" / "standard_template.xlsx"


STYLE = """
QWidget {font-family:"Microsoft YaHei UI","Noto Sans CJK SC","Arial";font-size:13px;color:#243b43;}
QMainWindow,QDialog {background:#f4f6f5;}
QWidget#rail {background:#122d33;} QWidget#rail QLabel {color:#dce9e7;}
QLabel#brand {font-size:23px;font-weight:700;color:white;}
QLabel#muted {color:#78908e;font-size:12px;} QLabel#title {font-size:27px;font-weight:700;color:#183336;}
QLabel#subtitle {color:#788988;} QLabel#section {font-size:15px;font-weight:700;}
QPushButton {background:white;border:1px solid #dce5e2;border-radius:8px;padding:9px 16px;font-weight:600;}
QPushButton:hover {background:#e8f0ed;border-color:#96bab1;} QPushButton:disabled {color:#9caaa7;background:#edf0ee;}
QPushButton#primary {background:#167364;color:white;border:0;} QPushButton#primary:hover {background:#0b5d50;}
QPushButton#nav {background:#22434a;color:#eef5f2;border:0;text-align:left;padding:12px;}
QLineEdit,QPlainTextEdit,QComboBox {border:1px solid #dbe5e1;border-radius:7px;background:white;padding:8px;selection-background-color:#b4dacf;}
QLineEdit:focus,QPlainTextEdit:focus {border-color:#278b77;}
QTableWidget {background:white;alternate-background-color:#f8faf9;border:0;gridline-color:#edf1ef;selection-background-color:#e2f0e9;selection-color:#153d36;}
QHeaderView::section {background:#f0f4f2;border:0;border-bottom:1px solid #dfe7e3;padding:12px;text-align:left;color:#62756d;font-weight:600;}
QTableWidget::item {padding:8px;border-bottom:1px solid #edf1ee;}
QTabWidget::pane {border:1px solid #dfe7e3;border-radius:8px;background:white;}
QTabBar::tab {padding:10px 20px;color:#7b8983;} QTabBar::tab:selected {color:#156b58;border-bottom:2px solid #167364;}
QScrollArea {border:0;background:white;} QProgressBar {border:0;border-radius:3px;background:#dde8e3;height:6px;text-align:center;}
QProgressBar::chunk {background:#248775;border-radius:3px;} QSplitter::handle {background:#e4eae6;width:7px;}
QLabel#pill {background:#ddefe5;color:#22715b;border-radius:10px;padding:6px 12px;font-size:12px;}
QLabel#banner {background:#FDECEA;color:#8A1C14;border:1px solid #F5C6C2;border-radius:8px;padding:8px 16px;font-weight:600;}
QLabel#progressCaption {color:#1D1D1F;font-weight:600;font-size:13px;}
QLabel#eta {color:#5E5E66;font-size:12px;}
QWidget#failCard {background:#FDECEA;border:1px solid #F5C6C2;border-radius:10px;}
QLabel#failTitle {color:#8A1C14;font-weight:700;}
QLabel#failReason {color:#8A1C14;}
QPushButton#disabledExport {background:#E5E5EA;color:#6E6E76;border:1px solid #E5E5EA;}
QDialog#sheet {background:#FFFFFF;}
QLabel#sheetTitle {font-size:17px;font-weight:700;color:#1D1D1F;}
QLabel#sheetSub {color:#5E5E66;font-size:12px;}
QLabel#reviewWarn {background:#FFF4E0;color:#7A4100;border-radius:10px;padding:12px;}
QTableWidget#resultTable {background:#FFFFFF;alternate-background-color:#FAFAFB;gridline-color:#E3E3E8;}
"""


def button(text, function, primary=False):
    b = QPushButton(text)
    b.clicked.connect(function)
    if primary:
        b.setObjectName("primary")
    return b


def label(text, name=""):
    w = QLabel(text)
    w.setObjectName(name)
    return w


class ChoiceEdit(QComboBox):
    textEdited = Signal(str)

    def __init__(self, options):
        super().__init__()
        self.setEditable(True)
        self.addItem("")
        self.addItems(options)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(100)
        self.lineEdit().textEdited.connect(self.textEdited.emit)
        self.activated.connect(lambda _: self.textEdited.emit(self.currentText()))

    def text(self):
        return self.currentText()

    def setText(self, value):
        self.setCurrentText(value)

    def setPlaceholderText(self, value):
        self.lineEdit().setPlaceholderText(value)


def source_page_count(path):
    """Page count used only for the progress line. Recognition still reads the file."""
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".pdf":
            import fitz

            with fitz.open(path) as document:
                return int(document.page_count)
        from PIL import Image

        with Image.open(path) as image:
            return int(getattr(image, "n_frames", 1) or 1)
    except Exception:
        return 0


_FILE_PROGRESS = re.compile(r"正在识别 第(\d+)个/共(\d+)个 · (.+?)(?: · |$)")
_PAGE_PROGRESS = re.compile(r"正在识别第\s*(\d+)(?:/(\d+))?\s*页")


class Worker(QThread):
    result = Signal(int, object)
    message = Signal(str)

    def __init__(self, jobs, fields, model):
        super().__init__()
        self.jobs = jobs
        self.fields = fields
        self.model = model
        self.stopped = False

    def run(self):
        processor = Processor()
        total = len(self.jobs)
        for nth, (index, path) in enumerate(self.jobs, 1):
            if self.isInterruptionRequested():
                self.stopped = True
                break
            prefix = f"正在识别 第{nth}个/共{total}个 · {Path(path).name}"
            pages = source_page_count(path)
            try:
                self.message.emit(prefix + (f" · 共 {pages} 页" if pages else ""))

                def report(message, prefix=prefix, pages=pages):
                    if pages and "正在识别第" in message and "/" not in message:
                        message = message.replace(" 页", f"/{pages} 页", 1)
                    self.message.emit(prefix + " · " + message)

                result = processor.recognize(
                    path,
                    self.fields,
                    self.isInterruptionRequested,
                    report,
                    self.model,
                )
            except Cancelled:
                self.stopped = True
                self.result.emit(
                    index,
                    {"status": STOPPED, "warning": STOPPED},
                )
                break
            except Exception as error:
                result = {
                    "status": FAILED,
                    "warning": chinese_message(error),
                    "text": "",
                    "values": {},
                    "evidence": {},
                    "ocr_rows": [],
                    "engine_version": VERSION,
                }
            self.result.emit(index, result)


class ExportWorker(QThread):
    item = Signal(int, object)
    message = Signal(str)

    def __init__(
        self,
        jobs,
        folder,
        template,
        sheet,
        defaults=None,
        overwrite=False,
        size_unit="MB",
    ):
        super().__init__()
        self.jobs = jobs
        self.folder = folder
        self.template = template
        self.sheet = sheet
        self.defaults = defaults
        self.overwrite = overwrite
        self.size_unit = size_unit
        self.results = []
        self.stopped = False

    def run(self):
        total = len(self.jobs)
        taken = set()
        for nth, (index, record) in enumerate(self.jobs, 1):
            if self.isInterruptionRequested():
                self.stopped = True
                break
            try:
                self.message.emit(
                    f"正在导出 第{nth}个/共{total}个 · {Path(record['path']).name}"
                )
                require_original_template(self.template)
                produced = export_mapped_separate(
                    [record],
                    self.folder,
                    self.template,
                    self.sheet,
                    defaults=self.defaults,
                    overwrite=self.overwrite,
                    taken=taken,
                    size_unit=self.size_unit,
                )
                result = (
                    produced[0]
                    if produced
                    else {
                        "source": record.get("path", ""),
                        "output": "",
                        "excel_name": "",
                        "name_note": "",
                        "error": "导出未完成。",
                    }
                )
            except Exception as error:
                result = {
                    "source": record.get("path", ""),
                    "output": "",
                    "excel_name": "",
                    "name_note": "",
                    "error": chinese_message(error),
                }
            self.results.append(result)
            self.item.emit(index, result)


def template_unavailable_message(path, reason):
    shown = path or "（未记录路径）"
    if reason == "missing":
        detail = "找不到已保存的导出模板"
    elif reason == "unreadable":
        detail = "导出模板无法读取（文件已损坏或不是有效的 Excel）"
    else:
        detail = chinese_message(reason).split("模板路径：", 1)[0]
        if shown:
            detail = detail.replace("：" + shown, "").replace(shown, "")
        detail = detail.strip().rstrip("。")
    if "导出已停用" not in detail:
        detail += "。导出已停用。请在「字段与模型设置」中重新选择模板。"
    elif not detail.endswith("。"):
        detail += "。"
    if "重新选择" not in detail:
        detail += "请在「字段与模型设置」中重新选择模板。"
    body = detail + "\n模板路径：" + shown
    headline = "模板有问题，暂时无法导出 Excel"
    if body.startswith(headline):
        return body
    return headline + "\n" + body


def confirm_unreviewed(parent, count):
    """Ask before exporting 待核对 files. The count excludes 已识别 and 已核对."""
    dialog = ExportConfirmDialog(parent, count)
    if dialog.exec() != QDialog.Accepted:
        return False
    if hasattr(parent, "overwrite_box"):
        parent.overwrite_box.setChecked(dialog.overwrite.isChecked())
    return True


def export_succeeded(record):
    """A file already exported, whose workbook is still in the output folder."""
    if record.get("export_status") != "成功" or record.get("export_error"):
        return False
    path = record.get("export_path") or ""
    return bool(path) and Path(path).is_file()


def open_output_folder(path):
    folder = str(path)
    if sys.platform == "win32":
        os.startfile(folder)
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, folder])


def show_skipped_files(parent, skipped, added=0):
    """List files that were not imported, with one reason each."""
    dialog = ImportSummaryDialog(parent, added, skipped)
    dialog.exec()


def show_export_result(parent, summary, folder, can_retry):
    """Show the batch result. Return open, retry, or close."""
    rows = getattr(parent, "_last_manifest_rows", None)
    dialog = ExportResultDialog(parent, summary, rows, can_retry)
    dialog.exec()
    if dialog.action == "open":
        open_output_folder(folder)
    return dialog.action or "close"


_SKIP_BADGE = {
    "文件已在列表中": ("重复", "同一文件已在列表中"),
    "不支持的文件格式": ("格式不支持", "仅支持 PDF 与图片"),
}

SHEET_STYLE = """
QDialog {background:#FFFFFF;color:#1D1D1F;}
QLabel {color:#1D1D1F;}
QLabel#sheetTitle {font-size:17px;font-weight:700;}
QLabel#sheetSub {color:#5E5E66;font-size:12px;}
QLabel#hint {color:#6E6E76;font-size:11px;}
QLabel#reviewWarn {background:#FFF4E0;color:#7A4100;border-radius:10px;padding:12px;}
QPushButton {background:#FFFFFF;border:1px solid #E3E3E8;border-radius:8px;padding:0 16px;min-height:32px;font-weight:600;}
QPushButton#primary {background:#0A66D9;color:#FFFFFF;border:0;}
QHeaderView::section {background:#FAFAFB;border:0;border-bottom:1px solid #E3E3E8;padding:6px 8px;font-weight:600;color:#5E5E66;}
QTableWidget {background:#FFFFFF;alternate-background-color:#FFFFFF;gridline-color:#E3E3E8;border:0;}
"""


def _sheet(dialog, title):
    dialog.setWindowTitle(title)
    dialog.setObjectName("sheet")
    dialog.setStyleSheet(SHEET_STYLE)
    dialog.setModal(True)


class ImportSummaryDialog(QDialog):
    """Import finished. Lists each skipped file and why."""

    def __init__(self, parent, added, skipped):
        super().__init__(parent)
        _sheet(self, "部分文件未导入")
        self.setFixedWidth(440)
        self.added = added
        self.skipped = list(skipped)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        self.heading = QLabel(f"已导入 {added} 份 · 跳过 {len(self.skipped)} 项")
        self.heading.setObjectName("sheetTitle")
        layout.addWidget(self.heading)
        self.lines = QLabel(self._body())
        self.lines.setWordWrap(True)
        self.lines.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.lines)
        buttons = QHBoxLayout()
        buttons.addStretch()
        copy = QPushButton("复制跳过清单")
        copy.clicked.connect(self._copy)
        buttons.addWidget(copy)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        if added:
            start = QPushButton(f"开始识别 {added} 份")
            start.setObjectName("primary")
            start.clicked.connect(self._start)
            buttons.addWidget(start)
        layout.addLayout(buttons)

    def _body(self):
        rows = [f"已跳过 {len(self.skipped)} 个文件。"]
        for path, reason in self.skipped:
            badge, detail = _SKIP_BADGE.get(reason, ("跳过", reason))
            rows.append(f"{badge}  {Path(path).name}  {detail}  {reason}\n{path}")
        return "\n".join(rows)

    def text(self):
        return self.heading.text()

    def informativeText(self):
        return self.lines.text()

    def _copy(self):
        text = "\n".join(f"{path}\t{reason}" for path, reason in self.skipped)
        QApplication.clipboard().setText(text)

    def _start(self):
        self.accept()
        parent = self.parent()
        if parent is not None and hasattr(parent, "start"):
            parent.start()


class ExportConfirmDialog(QDialog):
    """Confirm export. Only the 待核对 count is called out."""

    def __init__(self, parent, count):
        super().__init__(parent)
        total = getattr(parent, "_confirm_export_count", count)
        _sheet(self, "导出前确认")
        self.setFixedWidth(560)
        self.count = count
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(12)
        title = QLabel(f"导出 {total} 份 Excel")
        title.setObjectName("sheetTitle")
        layout.addWidget(title)
        sub = QLabel(
            "一份 PDF 对应一个按模板填好的 Excel。识别失败的文件不导出，会写入结果清单。"
        )
        sub.setObjectName("sheetSub")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addWidget(QLabel("输出文件夹"))
        folder = getattr(parent, "export_folder", "") or "尚未选择"
        shown = QLabel(folder)
        shown.setWordWrap(True)
        layout.addWidget(shown)
        remembered = QLabel(
            "已记住上次的选择" if getattr(parent, "export_folder", "") else ""
        )
        remembered.setObjectName("hint")
        layout.addWidget(remembered)
        self.overwrite = QCheckBox("覆盖同名文件")
        checked = bool(getattr(parent, "overwrite_same_name", False))
        self.overwrite.setChecked(checked)
        layout.addWidget(self.overwrite)
        note = QLabel("默认不勾选：已存在时改名为「xxx(1).xlsx」，并写入结果清单")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        warn = QLabel(
            f"还有 {count} 份待核对\n"
            f"有 {count} 份尚未核对。\n"
            "待核对的文件也会导出，Excel 按自动提取值填写。可以继续，也可以返回先核对。"
        )
        warn.setObjectName("reviewWarn")
        warn.setWordWrap(True)
        layout.addWidget(warn)
        foot = QHBoxLayout()
        hint = QLabel("导出后在输出文件夹保存结果清单")
        hint.setObjectName("hint")
        foot.addWidget(hint)
        foot.addStretch()
        back = QPushButton("返回")
        back.clicked.connect(self.reject)
        foot.addWidget(back)
        go = QPushButton("继续")
        go.setObjectName("primary")
        go.clicked.connect(self.accept)
        foot.addWidget(go)
        layout.addLayout(foot)

    def text(self):
        return f"还有 {self.count} 份待核对\n有 {self.count} 份尚未核对。"


class ExportResultDialog(QDialog):
    """Closable table: path, Excel name, result, Chinese reason, suggestion."""

    def __init__(self, parent, summary, rows, can_retry):
        super().__init__(parent)
        _sheet(self, "导出结果")
        self.summary = summary or ""
        self.rows = list(rows or [])
        self.action = "close"
        self.resize(1200, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        success = sum(row.get("结果") == "成功" for row in self.rows)
        failure = sum(row.get("结果") == "失败" for row in self.rows)
        if not self.rows:
            success, failure = _summary_counts(self.summary)
        total = len(self.rows) or (success + failure)
        head = QHBoxLayout()
        title = QLabel("导出结果")
        title.setObjectName("sheetTitle")
        head.addWidget(title)
        counts = QLabel(f"成功 {success} · 失败 {failure} · 共 {total}")
        counts.setObjectName("sheetTitle")
        head.addWidget(counts)
        head.addStretch()
        layout.addLayout(head)
        legacy = QLabel(self.summary)
        legacy.setObjectName("sheetSub")
        legacy.setWordWrap(True)
        layout.addWidget(legacy)
        table = QTableWidget(len(self.rows), 5)
        table.setObjectName("resultTable")
        table.setHorizontalHeaderLabels(
            ["源文件路径", "导出文件名", "结果", "中文原因", "处理建议"]
        )
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        for index, row in enumerate(self.rows):
            reason = row.get("原因") or ""
            name = row.get("导出文件名") or ""
            if row.get("结果") == "成功" and "（" in name:
                reason = reason or name.split("（", 1)[-1].rstrip("）")
            values = [
                row.get("源文件路径") or row.get("文件名") or "",
                name or "—",
                row.get("结果") or "",
                reason or "—",
                row.get("建议操作") or "—",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 2:
                    color = {"成功": "#1E7F3E", "失败": "#C9261C"}.get(value, "#6E6E76")
                    item.setForeground(QColor(color))
                table.setItem(index, column, item)
        layout.addWidget(table, 1)
        hint = QLabel("输出文件夹已保存处理清单 CSV")
        hint.setObjectName("hint")
        layout.addWidget(hint)
        foot = QHBoxLayout()
        foot.addStretch()
        copy = QPushButton("复制失败清单")
        copy.clicked.connect(lambda: self._copy_failures())
        foot.addWidget(copy)
        open_button = QPushButton("打开输出文件夹")
        open_button.clicked.connect(lambda: self._choose("open"))
        foot.addWidget(open_button)
        if can_retry:
            failed = failure or _summary_counts(self.summary)[1]
            retry = QPushButton(
                f"只重试失败项（{failed}）" if failed else "只重试失败项"
            )
            retry.setObjectName("primary")
            retry.clicked.connect(lambda: self._choose("retry"))
            foot.addWidget(retry)
        close = QPushButton("关闭")
        close.clicked.connect(lambda: self._choose("close"))
        foot.addWidget(close)
        layout.addLayout(foot)

    def text(self):
        return self.summary

    def informativeText(self):
        return ""

    def _choose(self, action):
        self.action = action
        self.accept()

    def _copy_failures(self):
        lines = []
        for row in self.rows:
            if row.get("结果") == "失败":
                lines.append(
                    f"{row.get('源文件路径') or row.get('文件名')}\t{row.get('原因') or ''}"
                )
        if not lines and "失败：" in self.summary:
            lines = [
                line
                for line in self.summary.splitlines()
                if line and not line.startswith("成功") and line != "失败："
            ]
        QApplication.clipboard().setText("\n".join(lines))


def _summary_counts(summary):
    match = re.search(r"成功\s*(\d+)\s*份，失败\s*(\d+)\s*份", summary or "")
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


class Window(QMainWindow):
    def __init__(self, state_path=None):
        super().__init__()
        self.setWindowTitle(f"档序 ArchiveDesk {VERSION} · 离线档案采集")
        self.resize(1460, 920)
        self.setMinimumSize(1100, 720)
        self.state_path = (
            Path(state_path)
            if state_path
            else Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
            / "ArchiveDesk"
            / "project.json"
        )
        self.fields = DEFAULT_FIELDS.copy()
        self.records = []
        self.current = -1
        self.page = 0
        self.worker = None
        self.export_worker = None
        self.model = ""
        self.loading = False
        self.dirty = False
        self.save_error_shown = False
        beside = program_template_path()
        self.auto_unit = True
        self.template_path = str(beside)
        self.template_sheet = DEFAULT_SHEET
        self.use_template = False
        self.choices = {}
        self.catalog_defaults = effective_defaults(None)
        self.export_folder = ""
        self.overwrite_same_name = False
        self.file_size_unit = "MB"
        self._export_after_ocr = False
        self._export_indexes = None
        self.template_notice = None
        self.defaults_notice = None
        self._template_notice_shown = False
        self._try_builtin_template(beside)
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.fields = state["fields"]
            self.records = state["records"]
            self.model = state.get("model", "")
            self.auto_unit = state.get("auto_unit", True)
            self.use_template = state.get("use_template", False)
            saved_template = state.get("template_path", self.template_path)
            self.template_sheet = state.get("template_sheet") or DEFAULT_SHEET
            self.catalog_defaults = effective_defaults(state.get("catalog_defaults"))
            self.export_folder = state.get("export_folder") or ""
            self.overwrite_same_name = bool(state.get("overwrite_same_name", False))
            saved_unit = str(state.get("file_size_unit") or "MB").upper()
            self.file_size_unit = (
                saved_unit if saved_unit in {"B", "KB", "MB"} else "MB"
            )
            if beside.is_file():
                self.template_path = str(beside)
                self._try_builtin_template(beside)
            else:
                self._try_saved_template(saved_template)
        except (OSError, ValueError, KeyError):
            pass
        self._refresh_defaults_notice()
        for record in self.records:
            if link_record(
                record,
                self.choices.get("归档单位", []) if self.use_template else [],
                self.auto_unit,
            ):
                self.dirty = True
        outer = QWidget()
        self.setCentralWidget(outer)
        main = QHBoxLayout(outer)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        rail = QWidget()
        rail.setObjectName("rail")
        rail.setFixedWidth(200)
        nav = QVBoxLayout(rail)
        nav.setContentsMargins(22, 32, 22, 26)
        nav.setSpacing(16)
        nav.addWidget(label("档序", "brand"))
        nav.addWidget(label("ARCHIVE DESK", "muted"))
        nav.addSpacing(34)
        b = button("▤   采集工作台", lambda: None)
        b.setObjectName("nav")
        nav.addWidget(b)
        nav.addWidget(button("字段与模型设置", self.settings))
        nav.addStretch()
        security = label("LOCAL FIRST\n\n本地识别 · 本地保存\n材料无需上传")
        security.setWordWrap(True)
        nav.addWidget(security)
        nav.addSpacing(20)
        nav.addWidget(label(f"桌面试用版  /  {VERSION}", "muted"))
        main.addWidget(rail)
        content = QVBoxLayout()
        content.setContentsMargins(30, 28, 30, 24)
        content.setSpacing(17)
        main.addLayout(content, 1)
        self.template_banner = label("", "banner")
        self.template_banner.setWordWrap(True)
        content.addWidget(self.template_banner)
        self._apply_template_banner()
        top = QHBoxLayout()
        titlebox = QVBoxLayout()
        titlebox.addWidget(label("让档案，从纸面走向有序", "title"))
        titlebox.addWidget(
            label("扫描件采集工作台  /  导入 → 识别 → 一键导出", "subtitle")
        )
        top.addLayout(titlebox)
        top.addStretch()
        top.addWidget(label("●  离线 OCR", "pill"))
        content.addLayout(top)
        self.metrics = label("", "section")
        content.addWidget(self.metrics)
        actions = QHBoxLayout()
        self.import_btn = button("＋ 导入文件", self.import_files, True)
        actions.addWidget(self.import_btn)
        self.folder_btn = button("导入文件夹", self.import_folder)
        actions.addWidget(self.folder_btn)
        self.run_btn = button("开始识别", self.start, True)
        actions.addWidget(self.run_btn)
        self.stop_btn = button("停止", self.stop)
        self.stop_btn.setEnabled(False)
        actions.addWidget(self.stop_btn)
        self.redo_btn = button("重新识别", self.reprocess)
        actions.addWidget(self.redo_btn)
        actions.addStretch()
        self.delete_btn = button("移除", self.remove)
        actions.addWidget(self.delete_btn)
        self.export_btn = button("导出 Excel", self.export, True)
        actions.addWidget(self.export_btn)
        self.summary_btn = button("汇总导出（可选）", self.export_summary)
        self.summary_btn.hide()
        self.overwrite_box = QCheckBox("覆盖同名文件")
        self.overwrite_box.setChecked(self.overwrite_same_name)
        self.overwrite_box.toggled.connect(self._set_overwrite)
        actions.addWidget(self.overwrite_box)
        self.retry_btn = button("只重试失败项", self.retry_failed)
        actions.addWidget(self.retry_btn)
        self._apply_export_enabled()
        actions.addWidget(button("核对记录", lambda: self.export(True)))
        content.addLayout(actions)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["文件 / 扫描件", "处理状态", "页数", "核对提示"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 65)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.currentCellChanged.connect(self.select)
        self.table.setMinimumHeight(130)
        self.table.setMaximumHeight(240)
        content.addWidget(self.table)
        self.empty = label(
            "从一份扫描件开始\n\n导入 PDF、JPG、PNG 或多页 TIFF，识别结果会显示在这里。",
            "subtitle",
        )
        self.empty.setAlignment(Qt.AlignCenter)
        content.addWidget(self.empty)
        splitter = QSplitter(Qt.Horizontal)
        content.addWidget(splitter, 1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 12, 0)
        heading = QHBoxLayout()
        heading.addWidget(label("原件与识别原文", "section"))
        heading.addStretch()
        self.page_label = label("")
        heading.addWidget(self.page_label)
        heading.addWidget(button("‹", lambda: self.turn(-1)))
        heading.addWidget(button("›", lambda: self.turn(1)))
        ll.addLayout(heading)
        self.tabs = QTabWidget()
        ll.addWidget(self.tabs, 1)
        self.image = QLabel("选择一个文件，查看原件")
        self.image.setAlignment(Qt.AlignCenter)
        self.image_area = QScrollArea()
        self.image_area.setWidgetResizable(True)
        self.image_area.setWidget(self.image)
        self.tabs.addTab(self.image_area, "扫描原件")
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlaceholderText("识别后保留全部原文，便于逐项核对。")
        self.tabs.addTab(self.raw, "OCR 原文")
        splitter.addWidget(left)
        right = QWidget()
        rr = QVBoxLayout(right)
        rr.setContentsMargins(12, 0, 0, 0)
        rr.addWidget(label("字段核对", "section"))
        self.unit_check = QCheckBox("归档单位跟随责任者（按模板字典匹配）")
        self.unit_check.setChecked(self.auto_unit)
        self.unit_check.toggled.connect(self.toggle_unit)
        rr.addWidget(self.unit_check)
        self.hint = label("自动提取仅作候选，请对照原件确认。", "subtitle")
        self.hint.setWordWrap(True)
        rr.addWidget(self.hint)
        formwrap = QWidget()
        self.form = QFormLayout(formwrap)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form.setSpacing(12)
        self.form.setContentsMargins(0, 10, 6, 10)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setWidget(formwrap)
        rr.addWidget(self.form_scroll, 1)
        self.fail_box = QWidget()
        self.fail_box.setObjectName("failCard")
        fail_layout = QVBoxLayout(self.fail_box)
        fail_layout.setContentsMargins(12, 12, 12, 12)
        self.fail_title = QLabel("识别失败")
        self.fail_title.setObjectName("failTitle")
        self.fail_reason = QLabel("")
        self.fail_reason.setObjectName("failReason")
        self.fail_reason.setWordWrap(True)
        fail_layout.addWidget(self.fail_title)
        fail_layout.addWidget(self.fail_reason)
        fail_layout.addWidget(button("重试此文件", self.reprocess))
        self.fail_box.hide()
        rr.addWidget(self.fail_box)
        self.review_btn = button("确认字段 · 标记已核对", self.review, True)
        rr.addWidget(self.review_btn)
        splitter.addWidget(right)
        splitter.setSizes([650, 400])
        self.progress = QProgressBar()
        self.progress.hide()
        content.addWidget(self.progress)
        self.progress_caption = label("", "progressCaption")
        self.progress_caption.hide()
        content.addWidget(self.progress_caption)
        self._page_rates = []
        self._file_rates = []
        self._page_mark = None
        self._file_mark = None
        self._seen_page = None
        ready = (
            "就绪 · 标准模板：" + self.template_sheet + " · 所有材料保留在本机"
            if self.use_template
            else (self.template_notice or "导出已停用。请重新选择标准模板。")
        )
        self.status = label(
            self.template_notice or self.defaults_notice or ready, "subtitle"
        )
        content.addWidget(self.status)
        self.build_form()
        self.refresh()
        self.autosave = QTimer(self)
        self.autosave.timeout.connect(self.save)
        self.autosave.start(1500)

    def busy(self):
        return (self.worker is not None and self.worker.isRunning()) or (
            self.export_worker is not None and self.export_worker.isRunning()
        )

    def build_form(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.inputs = {}
        priority = ["文件名称", "责任单位", "日期", "文号", "页数", "年度"]
        display_fields = sorted(
            self.fields,
            key=lambda f: (
                priority.index(canonical(f))
                if canonical(f) in priority
                else 100 + self.fields.index(f)
            ),
        )
        for field in display_fields:
            edit = (
                ChoiceEdit(self.choices[field])
                if self.use_template and field in self.choices
                else QLineEdit()
            )
            edit.setPlaceholderText("未提取 · 请核对填写")
            edit.textEdited.connect(lambda _=None, f=field: self.changed(f))
            self.form.addRow(field, edit)
            self.inputs[field] = edit

    def changed(self, field=None):
        if 0 <= self.current < len(self.records):
            r = self.records[self.current]
            r["values"] = {k: v.text() for k, v in self.inputs.items()}
            r["status"] = "待核对"
            link_record(
                r,
                self.choices.get("归档单位", []) if self.use_template else [],
                self.auto_unit,
            )
            if "归档单位" in self.inputs:
                self.inputs["归档单位"].setText(r["values"].get("归档单位", ""))
            self.dirty = True
            self._mark_missing_owner()
            self.refresh()

    def _mark_missing_owner(self):
        recognized = 0 <= self.current < len(self.records) and bool(
            self.records[self.current].get("text")
        )
        for field, edit in self.inputs.items():
            missing = (
                recognized
                and canonical(field) == "责任单位"
                and not edit.text().strip()
            )
            edit.setStyleSheet("background:#fff3a0;" if missing else "")

    def _apply_template_banner(self):
        if not hasattr(self, "template_banner"):
            return
        if self.template_notice:
            self.template_banner.setText(self.template_notice)
            self.template_banner.show()
        else:
            self.template_banner.hide()
            self.template_banner.setText("")

    def toggle_unit(self, enabled):
        self.auto_unit = enabled
        for record in self.records:
            link_record(
                record,
                self.choices.get("归档单位", []) if self.use_template else [],
                enabled,
            )
        self.dirty = True
        self.load_record()
        self.save()

    def save(self):
        if not self.dirty:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.state_path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(
                    {
                        "fields": self.fields,
                        "records": self.records,
                        "model": self.model,
                        "auto_unit": self.auto_unit,
                        "use_template": self.use_template,
                        "template_path": self.template_path,
                        "template_sheet": self.template_sheet,
                        "catalog_defaults": self.catalog_defaults,
                        "export_folder": self.export_folder,
                        "overwrite_same_name": self.overwrite_same_name,
                        "file_size_unit": self.file_size_unit,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temp.replace(self.state_path)
            self.dirty = False
        except OSError as error:
            self.status.setText("保存失败，请导出结果备份：" + chinese_message(error))
            if not self.save_error_shown:
                self.save_error_shown = True
                QMessageBox.warning(self, "本地保存失败", chinese_message(error))

    def add_paths(self, paths, report=False):
        known = {os.path.normcase(os.path.abspath(r["path"])) for r in self.records}
        skipped = []
        added = False
        added_count = 0
        for path in paths:
            if not path:
                continue
            key = os.path.normcase(os.path.abspath(path))
            if Path(path).suffix.lower() not in SUPPORTED:
                skipped.append((os.path.abspath(path), "不支持的文件格式"))
                continue
            if key in known:
                skipped.append((os.path.abspath(path), "文件已在列表中"))
                continue
            self.records.append(
                {
                    "path": os.path.abspath(path),
                    "status": "待识别",
                    "values": {},
                    "text": "",
                }
            )
            known.add(key)
            added = True
            added_count = added_count + 1
        if added:
            self.dirty = True
            self.refresh()
            if self.current < 0 and self.records:
                self.table.selectRow(0)
        if report and skipped:
            show_skipped_files(self, skipped, added_count)
        return skipped

    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择扫描件",
            "",
            "扫描件 (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        self.add_paths(paths, report=True)

    def import_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择扫描件文件夹（包含子文件夹）"
        )
        if folder:
            try:
                self.add_paths(
                    sorted(str(p) for p in Path(folder).rglob("*") if p.is_file()),
                    report=True,
                )
            except OSError as e:
                QMessageBox.warning(self, "文件夹读取失败", chinese_message(e))

    def refresh(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.records))
        for row, r in enumerate(self.records):
            missing = [
                f
                for f in self.fields
                if not r.get("values", {}).get(f)
                and canonical(f) in ("文件名称", "文号", "日期", "责任单位", "页数")
            ]
            hint = r.get("warning", "") or (
                ("待填：" + "、".join(missing)) if missing else "请对照原件确认"
            )
            for col, value in enumerate(
                [Path(r["path"]).name, r["status"], str(r.get("pages", "—")), hint]
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(r["path"] if col == 0 else hint)
                if col == 1:
                    if r["status"] in ("已核对", "已识别"):
                        color = "#18765d"
                    elif r["status"] in ("失败", "处理失败", STOPPED):
                        color = "#a33b32"
                    else:
                        color = "#b17829"
                    item.setForeground(QColor(color))
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 44)
        if self.current >= 0:
            self.table.selectRow(self.current)
        self.table.blockSignals(False)
        reviewed = sum(r["status"] == "已核对" for r in self.records)
        recognized = sum(r["status"] == "已识别" for r in self.records)
        self.metrics.setText(
            f"{len(self.records):02d}  份扫描件     /     {recognized:02d}  已识别     /     {reviewed:02d}  已核对"
        )
        self.empty.setVisible(not self.records)
        retryable = sum(
            1
            for record in self.records
            if record.get("status") in ("失败", "处理失败")
            or record.get("export_status") == "失败"
            or record.get("export_error")
        )
        self.retry_btn.setText(
            f"只重试失败项（{retryable}）" if retryable else "只重试失败项"
        )
        self.review_btn.setEnabled(
            0 <= self.current < len(self.records)
            and bool(self.records[self.current].get("text"))
            and not self.busy()
        )

    def select(self, row, *_):
        self.current = row
        self.page = 0
        self.load_record()

    def load_record(self):
        valid = 0 <= self.current < len(self.records)
        r = self.records[self.current] if valid else {}
        for field, edit in self.inputs.items():
            edit.setText(r.get("values", {}).get(field, ""))
            edit.setEnabled(
                valid
                and not self.busy()
                and not (field == "归档单位" and self.auto_unit)
            )
            info = r.get("evidence", {}).get(field, {})
            details = [info.get("status", "尚无提取依据")]
            for candidate in info.get("candidates", []):
                details.append(
                    f"第{candidate.get('page', '—')}页 / {candidate.get('source', '')} / 原始候选：{candidate.get('raw', '')} / 规范化：{candidate.get('value', '')} / {candidate.get('issue', '')}"
                )
            edit.setToolTip("\n".join(details))
        self._mark_missing_owner()
        self.raw.setPlainText(r.get("text", ""))
        failed = r.get("status") in ("失败", "处理失败")
        self.fail_box.setVisible(valid and failed)
        if failed:
            self.fail_title.setText(Path(r.get("path", "")).name + " 识别失败")
            self.fail_reason.setText(r.get("warning") or "识别失败，没有可核对的字段。")
        self.hint.setText(
            r.get("warning", "") or "空白字段需要补充；修改后需重新确认。"
        )
        self.preview()
        self.refresh()

    def turn(self, delta):
        if 0 <= self.current < len(self.records):
            self.page = max(0, min(self.page + delta, self.preview_pages - 1))
            self.preview()

    def preview(self):
        self.preview_pages = 1
        if not 0 <= self.current < len(self.records):
            self.image.setText("选择一个文件，查看原件")
            self.page_label.setText("")
            return
        path = self.records[self.current]["path"]
        try:
            import fitz
            from PIL import Image, ImageOps

            if Path(path).suffix.lower() == ".pdf":
                with fitz.open(path) as doc:
                    if doc.needs_pass:
                        raise ValueError("PDF已加密")
                    self.preview_pages = len(doc)
                    p = doc[min(self.page, len(doc) - 1)]
                    scale = min(1.5, 1400 / max(p.rect.width, p.rect.height))
                    pix = p.get_pixmap(
                        matrix=fitz.Matrix(scale, scale),
                        colorspace=fitz.csRGB,
                        alpha=False,
                    )
                    qimage = QImage(
                        pix.samples,
                        pix.width,
                        pix.height,
                        pix.stride,
                        QImage.Format_RGB888,
                    ).copy()
            else:
                with Image.open(path) as img:
                    self.preview_pages = getattr(img, "n_frames", 1)
                    img.seek(min(self.page, self.preview_pages - 1))
                    img = ImageOps.exif_transpose(img).convert("RGB")
                    img.thumbnail((1200, 1600))
                    data = img.tobytes()
                    qimage = QImage(
                        data, img.width, img.height, img.width * 3, QImage.Format_RGB888
                    ).copy()
            pixmap = QPixmap.fromImage(qimage)
            width = max(320, self.image_area.viewport().width() - 24)
            self.image.setPixmap(pixmap.scaledToWidth(width, Qt.SmoothTransformation))
            self.page_label.setText(f"{self.page + 1} / {self.preview_pages}")
        except Exception as e:
            self.image.setText("无法预览原件\n" + chinese_message(e))
            self.page_label.setText("")

    def set_busy(self, enabled):
        for widget in [
            self.import_btn,
            self.folder_btn,
            self.run_btn,
            self.delete_btn,
            self.redo_btn,
            self.retry_btn,
        ]:
            widget.setEnabled(not enabled)
        for field, widget in self.inputs.items():
            widget.setEnabled(
                not enabled and not (field == "归档单位" and self.auto_unit)
            )
        self.unit_check.setEnabled(not enabled)
        self.stop_btn.setEnabled(enabled)
        self.progress.setVisible(enabled)
        self.progress.setFormat("第%v个/共%m个")
        if not enabled:
            self.progress_caption.hide()
        self._apply_export_enabled(enabled)

    def _apply_export_enabled(self, busy=False):
        allowed = self.use_template and not busy
        if hasattr(self, "export_btn"):
            self.export_btn.setEnabled(allowed)
            self.summary_btn.setEnabled(allowed)
            if allowed:
                self.export_btn.setObjectName("primary")
                self.export_btn.setStyleSheet("")
            else:
                self.export_btn.setObjectName("disabledExport")
                self.export_btn.setStyleSheet(
                    "QPushButton#disabledExport {background:#E5E5EA;color:#6E6E76;border:1px solid #E5E5EA;}"
                )
            self.export_btn.style().unpolish(self.export_btn)
            self.export_btn.style().polish(self.export_btn)
            tip = "" if allowed or busy else (self.template_notice or "导出已停用。")
            self.export_btn.setToolTip(tip)
            self.summary_btn.setToolTip(tip)

    def _set_overwrite(self, checked):
        self.overwrite_same_name = bool(checked)
        self.dirty = True
        self.save()

    def reprocess(self):
        if self.busy() or not 0 <= self.current < len(self.records):
            return
        if (
            QMessageBox.question(
                self,
                "重新识别当前文件",
                "将使用新版规则重新读取，并替换当前文件的字段和人工修改。是否继续？",
            )
            != QMessageBox.Yes
        ):
            return
        self.launch_jobs([(self.current, self.records[self.current]["path"])])

    def launch_jobs(self, jobs):
        self.worker = Worker(jobs, self.fields.copy(), self.model)
        self.worker.result.connect(self.received)
        self.worker.message.connect(self._on_worker_message)
        self.worker.finished.connect(self.finished)
        self._page_rates = []
        self._file_rates = []
        self._page_mark = None
        self._seen_page = None
        self._file_mark = time.monotonic()
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.set_busy(True)
        self.worker.start()
        self.refresh()

    def start(self):
        if self.busy():
            return
        jobs = [(i, r["path"]) for i, r in enumerate(self.records) if needs_ocr(r)]
        if not jobs:
            QMessageBox.information(
                self, "没有待处理文件", "请导入新文件。已识别文件不会被覆盖。"
            )
            return
        self.launch_jobs(jobs)

    def _on_worker_message(self, message):
        self.status.setText(message)
        self._update_progress_caption(message)

    def _update_progress_caption(self, message):
        file_match = _FILE_PROGRESS.search(message or "")
        if not file_match:
            return
        nth = int(file_match.group(1))
        total = int(file_match.group(2))
        name = file_match.group(3).strip()
        page_match = _PAGE_PROGRESS.search(message)
        page_bit = ""
        remain_pages = 0
        if page_match:
            page = int(page_match.group(1))
            pages = int(page_match.group(2) or 0)
            page_bit = f"第 {page}/{pages} 页" if pages else f"第 {page} 页"
            now = time.monotonic()
            if (
                self._page_mark is not None
                and self._seen_page is not None
                and page != self._seen_page
            ):
                self._page_rates.append(now - self._page_mark)
            self._page_mark = now
            self._seen_page = page
            if pages:
                remain_pages = max(pages - page, 0)
        bits = [f"第 {nth}/{total} 个"]
        if page_bit:
            bits.append(page_bit)
        bits.append(name)
        eta = self._remaining_seconds(remain_pages, max(total - nth, 0))
        if eta is not None:
            bits.append(f"预计剩余约 {eta} 秒")
        self.progress_caption.setText(" · ".join(bits))
        self.progress_caption.show()

    def _remaining_seconds(self, remain_pages, remain_files):
        if not self._page_rates:
            return None
        page_rate = sum(self._page_rates) / len(self._page_rates)
        file_rate = (
            sum(self._file_rates) / len(self._file_rates) if self._file_rates else 0
        )
        seconds = round(remain_pages * page_rate) + round(remain_files * file_rate)
        if seconds <= 0:
            return None
        return int(seconds)

    def _finish_progress_file(self):
        if self._file_mark is None:
            return
        self._file_rates.append(time.monotonic() - self._file_mark)
        self._file_mark = time.monotonic()
        self._page_mark = None
        self._seen_page = None

    def received(self, index, result):
        if self.worker is not None and self.worker.isRunning():
            self._finish_progress_file()
        if result.get("status") == STOPPED:
            record = self.records[index]
            record["status"] = STOPPED
            record["warning"] = result.get("warning") or STOPPED
            self.dirty = True
            self.progress.setValue(self.progress.value() + 1)
            if self.current == index:
                self.load_record()
            else:
                self.refresh()
            return
        if self.use_template and result.get("values"):
            for field, value in list(result["values"].items()):
                converted = standard_value(field, value, self.choices.get(field, []))
                if converted != value:
                    result["values"][field] = converted
                    note = f"{field}原文“{value}”按模板字典映射为“{converted}”"
                    result["warning"] = "；".join(
                        filter(None, [result.get("warning", ""), note])
                    )
        link_record(
            result,
            self.choices.get("归档单位", []) if self.use_template else [],
            self.auto_unit,
        )
        if result.get("status") != FAILED:
            result["status"] = classify_recognition(
                self.fields,
                result.get("values") or {},
                result.get("evidence") or {},
                result.get("confidence"),
            )
        self.records[index].update(result)
        self.records[index]["export_status"] = ""
        self.records[index]["export_path"] = ""
        self.records[index]["export_name"] = ""
        self.records[index]["export_error"] = ""
        self.dirty = True
        self.progress.setValue(self.progress.value() + 1)
        if self.current == index:
            self.load_record()
        else:
            self.refresh()

    def finished(self):
        stopped = self.worker is not None and self.worker.stopped
        self.set_busy(False)
        if stopped:
            self.status.setText("已停止。已完成的结果已保留，当前文件可重新识别。")
        else:
            self.status.setText("本轮处理结束 · 请核对字段后导出 Excel")
        self.load_record()
        self.save()
        if self._export_after_ocr:
            self._export_after_ocr = False
            indexes = self._export_indexes or []
            self.export(only_indexes=indexes, confirm=False)

    def stop(self):
        if self.busy():
            (
                self.export_worker
                if self.export_worker is not None and self.export_worker.isRunning()
                else self.worker
            ).requestInterruption()
            self.status.setText("已请求停止 · 当前OCR运算或本地模型响应结束后停止")
            self.stop_btn.setEnabled(False)

    def review(self):
        if not 0 <= self.current < len(self.records):
            return
        for field, widget in self.inputs.items():
            if canonical(field) == "日期" and widget.text().strip():
                normalized, error = normalize_date(widget.text())
                if error:
                    QMessageBox.warning(
                        self,
                        "日期需校正",
                        field + "：" + error + "。请填写有效的年月日。",
                    )
                    return
                widget.setText(normalized)
                self.records[self.current]["values"][field] = normalized
        missing = [
            k
            for k, w in self.inputs.items()
            if not w.text().strip()
            and canonical(k) in ("文件名称", "文号", "日期", "责任单位", "页数")
        ]
        if (
            missing
            and QMessageBox.question(
                self,
                "仍有空白字段",
                "以下字段为空：" + "、".join(missing) + "\n仍标记为已核对？",
            )
            != QMessageBox.Yes
        ):
            return
        self.records[self.current]["status"] = "已核对"
        self.dirty = True
        self.refresh()
        self.save()

    def remove(self):
        if self.busy() or self.current < 0:
            return
        if (
            QMessageBox.question(
                self, "移除记录", "只移除本应用中的记录，原文件保留。是否继续？"
            )
            != QMessageBox.Yes
        ):
            return
        self.records.pop(self.current)
        self.current = -1
        self.dirty = True
        self.refresh()
        self.load_record()
        if self.records:
            self.table.selectRow(0)

    def export(self, report=False, only_indexes=None, confirm=True):
        if self.busy():
            QMessageBox.information(self, "任务进行中", "请等待当前识别或导出完成。")
            return
        if report:
            self._export_json()
            return
        if not self.use_template:
            QMessageBox.warning(
                self,
                "导出已停用",
                self.template_notice or "没有可读的标准模板。导出已停用。",
            )
            return
        if only_indexes is None:
            indexes = [
                index
                for index, record in enumerate(self.records)
                if not export_succeeded(record)
            ]
        else:
            indexes = [
                index for index in only_indexes if 0 <= index < len(self.records)
            ]
        if not indexes:
            QMessageBox.information(
                self,
                "没有待导出文件",
                "已成功导出的文件已跳过。需要重新处理失败项时，请使用「只重试失败项」。",
            )
            return
        pending = sum(
            self.records[index].get("status") == "待核对" for index in indexes
        )
        self._confirm_export_count = len(indexes)
        if confirm and pending and not confirm_unreviewed(self, pending):
            return
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择输出文件夹：每个 PDF 导出一个同名 Excel",
            self.export_folder or "",
        )
        if not folder:
            return
        self.export_folder = folder
        self.dirty = True
        self.save()
        self._start_export(indexes)

    def _export_json(self):
        records = [
            record
            for record in self.records
            if record.get("text") and not not_exportable(record)
        ]
        if not records:
            QMessageBox.information(
                self, "暂无可导出结果", "请先完成至少一份文件的识别。"
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出核对记录", "档案核对记录.json", "JSON (*.json)"
        )
        if path:
            if not path.lower().endswith(".json"):
                path += ".json"
            try:
                Path(path).write_text(
                    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                QMessageBox.information(
                    self,
                    "核对记录已保存",
                    "原文和提取依据已保存为JSON，不生成其他格式的Excel：\n" + path,
                )
            except Exception as e:
                QMessageBox.warning(self, "保存失败", chinese_message(e))

    def _start_export(self, indexes):
        import copy

        try:
            require_original_template(self.template_path)
            inspect_template(self.template_path, self.template_sheet or DEFAULT_SHEET)
        except Exception as error:
            message = template_unavailable_message(self.template_path, error)
            self._fallback_from_template(message)
            self._apply_template_banner()
            self._apply_export_enabled()
            self.status.setText(message)
            QMessageBox.warning(self, "导出已停用", message)
            return
        jobs = []
        for index in indexes:
            item = copy.deepcopy(self.records[index])
            item["export_order"] = index + 1
            item["export_error"] = ""
            jobs.append((index, item))
        self._export_indexes = list(indexes)
        self.export_worker = ExportWorker(
            jobs,
            self.export_folder,
            self.template_path,
            self.template_sheet,
            self.catalog_defaults,
            self.overwrite_same_name,
            self.file_size_unit,
        )
        self.export_worker.item.connect(self.export_received)
        self.export_worker.message.connect(self._on_worker_message)
        self.export_worker.finished.connect(self.export_finished)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.dirty = True
        self.set_busy(True)
        self.export_worker.start()
        self.refresh()

    def retry_failed(self):
        indexes = [
            index
            for index, record in enumerate(self.records)
            if record.get("export_error") or needs_ocr(record)
        ]
        if not indexes:
            QMessageBox.information(self, "没有失败文件", "当前没有需要重试的文件。")
            return
        if not self.export_folder:
            self.export(only_indexes=indexes, confirm=False)
            return
        need_ocr = [index for index in indexes if needs_ocr(self.records[index])]
        self._export_indexes = indexes
        if need_ocr:
            self._export_after_ocr = True
            self.launch_jobs(
                [(index, self.records[index]["path"]) for index in need_ocr]
            )
            return
        self._start_export(indexes)

    def export_received(self, index, result):
        self.records[index]["export_path"] = result.get("output") or ""
        self.records[index]["export_name"] = result.get("excel_name") or ""
        self.records[index]["export_error"] = result.get("error") or ""
        self.records[index]["export_status"] = "失败" if result.get("error") else "成功"
        self.dirty = True
        self.progress.setValue(self.progress.value() + 1)

    def export_finished(self):
        self.set_busy(False)
        self.refresh()
        stopped = self.export_worker.stopped
        indexes = [
            index for index in (self._export_indexes or []) if index < len(self.records)
        ]
        batch = [self.records[index] for index in indexes]
        if stopped:
            text = "已停止，未处理文件可再次导出。\n" + describe_batch(
                batch, self.export_worker.results, stopped=True
            )
        else:
            text = describe_batch(batch, self.export_worker.results, stopped=False)
        try:
            write_manifest(
                self.export_folder, batch, self.export_worker.results, stopped=stopped
            )
        except OSError as error:
            text += "\n导出清单未能写入：" + chinese_message(error)
        self.status.setText(text.splitlines()[0])
        self.save()
        self._last_manifest_rows = manifest_rows(
            batch, self.export_worker.results, stopped=stopped
        )
        can_retry = any(record.get("export_error") for record in batch) or any(
            needs_ocr(record) for record in batch
        )
        if show_export_result(self, text, self.export_folder, can_retry) == "retry":
            self.retry_failed()

    def export_summary(self):
        import copy

        if self.busy():
            QMessageBox.information(self, "任务进行中", "请等待当前识别或导出完成。")
            return
        records = []
        for index, record in enumerate(self.records):
            if record.get("text") and not not_exportable(record):
                item = copy.deepcopy(record)
                item["export_order"] = index + 1
                records.append(item)
        if not records:
            QMessageBox.information(
                self, "暂无可导出结果", "请先完成至少一份文件的识别。"
            )
            return
        if not self.use_template:
            QMessageBox.warning(
                self,
                "导出已停用",
                self.template_notice or "没有可读的标准模板。导出已停用。",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存汇总目录：全部文件写入管理类_件",
            "目录汇总.xlsx",
            "Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            write_summary(
                path,
                records,
                self.template_path,
                self.template_sheet or DEFAULT_SHEET,
                self.catalog_defaults,
                self.file_size_unit,
            )
        except Exception as error:
            QMessageBox.warning(self, "汇总导出失败", chinese_message(error))
            return
        QMessageBox.information(
            self,
            "汇总导出完成",
            f"已把 {len(records)} 份文件写入「{self.template_sheet or DEFAULT_SHEET}」第2行起。\n卷和卷内件保持为空。\n"
            + path,
        )

    def settings(self):
        if self.busy():
            QMessageBox.information(self, "正在处理", "请等待当前任务结束后修改设置。")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("采集模板与本地模型")
        dlg.resize(640, 820)
        layout = QVBoxLayout(dlg)
        layout.addWidget(label("标准模板", "section"))
        format_hint = label(
            "按所选模板的工作表、表头和下拉字典导出。模板缺失或损坏时导出保持停用。",
            "subtitle",
        )
        format_hint.setWordWrap(True)
        layout.addWidget(format_hint)
        path_edit = QLineEdit(self.template_path)
        path_edit.setReadOnly(True)
        layout.addWidget(path_edit)
        sheets = QComboBox()
        sheets.setObjectName("template-sheet")
        layout.addWidget(sheets)
        edit = QPlainTextEdit("\n".join(self.fields))
        edit.setMaximumHeight(120)
        layout.addWidget(edit)
        default_inputs = {}
        pending = {"defaults": None}

        def current_default_texts():
            if not default_inputs:
                return dict(self.catalog_defaults)
            return {
                field: widget.text().strip() for field, widget in default_inputs.items()
            }

        def rebuild_defaults(choices):
            existing = current_default_texts()
            while defaults_form.rowCount():
                defaults_form.removeRow(0)
            default_inputs.clear()
            for field in DEFAULTS:
                options = list((choices or {}).get(field) or [])
                widget = ChoiceEdit(options) if options else QLineEdit()
                widget.setObjectName("default:" + field)
                widget.setText(existing.get(field, DEFAULTS[field]))
                defaults_form.addRow(field, widget)
                default_inputs[field] = widget

        def sync_fields():
            choices = {}
            if sheets.currentText():
                try:
                    meta = inspect_template(path_edit.text(), sheets.currentText())
                except Exception:
                    meta = None
                if meta is not None:
                    edit.setPlainText("\n".join(meta["headers"]))
                    choices = meta["choices"]
            edit.setReadOnly(True)
            target = sheets.currentText() or DEFAULT_SHEET
            defaults_hint.setText(
                f"导出目标表默认是「{DEFAULT_SHEET}」，当前为「{target}」。"
                "下拉默认值必须与该表一致，留空则不填。"
            )
            rebuild_defaults(choices)

        def load_template(path, selected=None):
            meta = inspect_template(path, selected or DEFAULT_SHEET)
            path_edit.setText(path)
            sheets.blockSignals(True)
            sheets.clear()
            sheets.addItems(meta["sheets"])
            sheets.setCurrentText(meta["sheet"])
            sheets.blockSignals(False)
            sync_fields()

        def choose_template():
            path, _ = QFileDialog.getOpenFileName(
                dlg, "选择标准导出模板", "", "Excel (*.xlsx)"
            )
            if not path:
                return
            try:
                load_template(path)
            except Exception as e:
                QMessageBox.warning(dlg, "模板读取失败", chinese_message(e))

        layout.addWidget(button("选择其他标准 Excel 模板", choose_template))
        layout.addWidget(label("电子文件大小单位", "section"))
        size_unit = QComboBox()
        size_unit.setObjectName("file-size-unit")
        size_unit.addItems(["MB", "KB", "B"])
        size_unit.setCurrentText(
            self.file_size_unit if self.file_size_unit in {"B", "KB", "MB"} else "MB"
        )
        layout.addWidget(size_unit)
        size_hint = label(
            "默认按 MB 写入。可改为 KB 或 B。",
            "subtitle",
        )
        size_hint.setWordWrap(True)
        layout.addWidget(size_hint)
        layout.addWidget(label("目录默认值", "section"))
        defaults_hint = label("", "subtitle")
        defaults_hint.setWordWrap(True)
        layout.addWidget(defaults_hint)
        defaults_scroll = QScrollArea()
        defaults_scroll.setWidgetResizable(True)
        defaults_scroll.setMaximumHeight(220)
        defaults_host = QWidget()
        defaults_form = QFormLayout(defaults_host)
        defaults_scroll.setWidget(defaults_host)
        layout.addWidget(defaults_scroll)
        sheets.currentTextChanged.connect(sync_fields)
        try:
            load_template(self.template_path, self.template_sheet or DEFAULT_SHEET)
        except Exception as error:
            QMessageBox.warning(
                dlg,
                "模板读取失败",
                chinese_message(error) + "\n导出已停用，直到选择可读的标准模板。",
            )
            sync_fields()
        layout.addWidget(label("可选：本机 Ollama 模型", "section"))
        model = QLineEdit(self.model)
        model.setPlaceholderText("留空使用离线 OCR 与规则")
        layout.addWidget(model)
        note = label(
            "只填选中的目录表，其他目录表和字典保留。\n日期按有效年月日写入，字典字段从下拉项选择。\n本地模型仅连接127.0.0.1；通用模型需提前安装。\n切换表头后，已有同名字段保留，新增字段重新分析。必填项齐全且置信度达到 0.85 为已识别，否则为待核对。",
            "subtitle",
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        def commit_settings():
            choices = {}
            if sheets.currentText():
                try:
                    choices = inspect_template(path_edit.text(), sheets.currentText())[
                        "choices"
                    ]
                except Exception as error:
                    QMessageBox.warning(dlg, "模板读取失败", chinese_message(error))
                    return
            cleaned, error = validate_defaults(current_default_texts(), choices)
            if error:
                QMessageBox.warning(dlg, "默认值无效", error)
                return
            pending["defaults"] = cleaned
            dlg.accept()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(commit_settings)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.Accepted:
            return
        fields = list(
            dict.fromkeys(
                line.strip() for line in edit.toPlainText().splitlines() if line.strip()
            )
        )
        if not fields or len(fields) > 60 or any(len(f) > 80 for f in fields):
            QMessageBox.warning(
                self, "字段无效", "请设置1—60个字段，每个字段最多80个字符。"
            )
            return
        try:
            import hashlib, shutil

            incoming = Path(path_edit.text())
            dest = (
                self.state_path.parent
                / "templates"
                / (hashlib.sha256(incoming.read_bytes()).hexdigest()[:16] + ".xlsx")
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            if incoming.resolve() != dest.resolve():
                shutil.copy2(incoming, dest)
            self.template_path = str(dest)
            self.template_sheet = sheets.currentText()
            meta = inspect_template(dest, self.template_sheet)
            fields = meta["headers"]
            self.choices = meta["choices"]
        except Exception as e:
            QMessageBox.warning(self, "模板保存失败", chinese_message(e))
            return
        self.use_template = True
        self.file_size_unit = size_unit.currentText()
        self.template_notice = None
        self._apply_template_banner()
        if fields != self.fields:
            self.fields = fields
            for record in self.records:
                old = record.get("values", {})
                record["values"] = {k: v for k, v in old.items() if k in fields}
                if record.get("text"):
                    candidates, evidence, warnings = extract_details(
                        record["text"],
                        fields,
                        record.get("pages", 0),
                        rows=record.get("ocr_rows") or None,
                    )
                    for k, v in candidates.items():
                        record["values"].setdefault(k, v)
                    record["evidence"] = evidence
                    record["status"] = classify_recognition(
                        fields,
                        record["values"],
                        evidence,
                        record.get("confidence"),
                    )
                    record["warning"] = "；".join(warnings)
        for record in self.records:
            link_record(
                record,
                self.choices.get("归档单位", []) if self.use_template else [],
                self.auto_unit,
            )
        self.build_form()
        self.model = model.text().strip()
        self.catalog_defaults = pending["defaults"]
        self._refresh_defaults_notice()
        if not self.template_notice:
            self.status.setText(
                self.defaults_notice
                or (
                    "就绪 · 标准模板：" + self.template_sheet
                    if self.use_template
                    else (self.template_notice or "导出已停用。请重新选择标准模板。")
                )
            )
        self._apply_template_banner()
        self._apply_export_enabled()
        self.dirty = True
        self.load_record()
        self.save()

    def showEvent(self, event):
        super().showEvent(event)
        if self.template_notice and not self._template_notice_shown:
            self._template_notice_shown = True
            notice = self.template_notice
            QTimer.singleShot(
                0, lambda: QMessageBox.warning(self, "请重新选择模板", notice)
            )

    def _try_builtin_template(self, builtin):
        self.template_path = str(builtin)
        if not Path(builtin).exists():
            self.use_template = False
            self.template_notice = template_unavailable_message(str(builtin), "missing")
            return
        try:
            meta = inspect_template(self.template_path, self.template_sheet)
        except Exception as error:
            self._fallback_from_template(
                template_unavailable_message(self.template_path, error)
            )
            return
        self.use_template = True
        self.fields = meta["headers"]
        self.choices = meta["choices"]
        self.template_notice = None

    def _try_saved_template(self, saved_template):
        if not saved_template:
            return
        if not Path(saved_template).exists():
            shown = saved_template or self.template_path
            self.template_path = str(shown)
            self._fallback_from_template(template_unavailable_message(shown, "missing"))
            return
        self.template_path = str(saved_template)
        try:
            meta = inspect_template(self.template_path, self.template_sheet)
        except Exception as error:
            self._fallback_from_template(
                template_unavailable_message(self.template_path, error)
            )
            return
        self.choices = meta["choices"]
        self.template_notice = None

    def _fallback_from_template(self, message):
        self.use_template = False
        self.choices = {}
        self.template_notice = message
        self._apply_template_banner()

    def _refresh_defaults_notice(self):
        self.defaults_notice = None
        if not self.use_template:
            return
        _values, error = validate_defaults(self.catalog_defaults, self.choices)
        if error:
            self.defaults_notice = (
                error + "。导出时这些项会留空。请在「字段与模型设置」中修改。"
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "image"):
            QTimer.singleShot(100, self.preview)

    def closeEvent(self, event):
        if self.busy():
            self.stop()
            QMessageBox.information(
                self, "正在停止", "停止请求已提交。当前运算完成后请再次关闭窗口。"
            )
            event.ignore()
            return
        self.save()
        if (
            self.dirty
            and QMessageBox.question(
                self, "尚未保存", "本地保存失败，关闭会丢失最新修改。仍要关闭？"
            )
            != QMessageBox.Yes
        ):
            event.ignore()
            return
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = Window()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
