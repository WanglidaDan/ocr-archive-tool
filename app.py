import json
import os
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPixmap, QImage
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QPlainTextEdit, QLineEdit, QFormLayout, QMessageBox, QDialog,
    QDialogButtonBox, QScrollArea, QTabWidget, QProgressBar, QAbstractItemView, QFrame, QComboBox, QSizePolicy, QCheckBox)
from batch_export import export_separate
from unit_link import link_record
from extraction import canonical, normalize_date, extract_details
from template_io import inspect_template, export_template, standard_value
from core import DEFAULT_FIELDS, SUPPORTED, Processor, Cancelled, export_xlsx

STYLE='''
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
'''

def button(text, function, primary=False):
    b=QPushButton(text); b.clicked.connect(function)
    if primary:b.setObjectName('primary')
    return b

def label(text,name=''):
    w=QLabel(text); w.setObjectName(name); return w

class ChoiceEdit(QComboBox):
    textEdited=Signal(str)
    def __init__(self,options):
        super().__init__(); self.setEditable(True); self.addItem(''); self.addItems(options)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);self.setMinimumContentsLength(8);self.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);self.setMinimumWidth(100)
        self.lineEdit().textEdited.connect(self.textEdited.emit)
        self.activated.connect(lambda _:self.textEdited.emit(self.currentText()))
    def text(self):return self.currentText()
    def setText(self,value):self.setCurrentText(value)
    def setPlaceholderText(self,value):self.lineEdit().setPlaceholderText(value)

class Worker(QThread):
    result=Signal(int,object); message=Signal(str)
    def __init__(self, jobs, fields, model):
        super().__init__(); self.jobs=jobs; self.fields=fields; self.model=model
    def run(self):
        processor=Processor()
        for index,path in self.jobs:
            if self.isInterruptionRequested():break
            try:
                self.message.emit('正在处理 · '+Path(path).name)
                result=processor.recognize(path,self.fields,self.isInterruptionRequested,self.message.emit,self.model)
            except Cancelled:break
            except Exception as error:result={'status':'处理失败','warning':str(error),'text':'','values':{},'evidence':{},'ocr_rows':[],'engine_version':'0.2'}
            self.result.emit(index,result)

class ExportWorker(QThread):
    item=Signal(int,object);message=Signal(str)
    def __init__(self,jobs,folder,template,sheet):
        super().__init__();self.jobs=jobs;self.folder=folder;self.template=template;self.sheet=sheet;self.results=[]
    def run(self):
        for index,record in self.jobs:
            if self.isInterruptionRequested():break
            self.message.emit('正在分开导出 · '+Path(record['path']).name)
            result=export_separate([record],self.folder,self.template,self.sheet)[0]
            self.results.append(result);self.item.emit(index,result)

class Window(QMainWindow):
    def __init__(self, state_path=None):
        super().__init__(); self.setWindowTitle('档序 ArchiveDesk 0.3 · 离线档案采集'); self.resize(1460,920)
        self.setMinimumSize(1100,720)
        self.state_path=Path(state_path) if state_path else Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'ArchiveDesk'/'project.json'
        self.fields=DEFAULT_FIELDS.copy(); self.records=[]; self.current=-1; self.page=0; self.worker=None; self.export_worker=None; self.model=''; self.loading=False; self.dirty=False; self.save_error_shown=False
        builtin=Path(__file__).resolve().parent/'templates/standard_template.xlsx'
        self.auto_unit=True; self.template_path=str(builtin); self.template_sheet='管理类_件'; self.use_template=builtin.exists(); self.choices={}
        if self.use_template:
            meta=inspect_template(self.template_path,self.template_sheet); self.fields=meta['headers']; self.choices=meta['choices']
        try:
            state=json.loads(self.state_path.read_text(encoding='utf-8'))
            self.fields=state['fields']; self.records=state['records']; self.model=state.get('model','')
            self.auto_unit=state.get('auto_unit',True)
            self.use_template=state.get('use_template',False)
            saved_template=state.get('template_path',self.template_path)
            if Path(saved_template).exists():self.template_path=saved_template
            self.template_sheet=state.get('template_sheet',self.template_sheet)
            if self.use_template:
                meta=inspect_template(self.template_path,self.template_sheet); self.choices=meta['choices']
        except (OSError,ValueError,KeyError):pass
        for record in self.records:
            if link_record(record,self.choices.get('归档单位',[]) if self.use_template else [],self.auto_unit):self.dirty=True
        outer=QWidget(); self.setCentralWidget(outer); main=QHBoxLayout(outer); main.setContentsMargins(0,0,0,0); main.setSpacing(0)
        rail=QWidget(); rail.setObjectName('rail'); rail.setFixedWidth(200); nav=QVBoxLayout(rail); nav.setContentsMargins(22,32,22,26); nav.setSpacing(16)
        nav.addWidget(label('档序','brand')); nav.addWidget(label('ARCHIVE DESK','muted')); nav.addSpacing(34)
        b=button('▤   采集工作台',lambda:None); b.setObjectName('nav'); nav.addWidget(b)
        nav.addWidget(button('字段与模型设置',self.settings)); nav.addStretch()
        security=label('LOCAL FIRST\n\n本地识别 · 本地保存\n材料无需上传'); security.setWordWrap(True); nav.addWidget(security)
        nav.addSpacing(20); nav.addWidget(label('桌面试用版  /  0.3','muted')); main.addWidget(rail)
        content=QVBoxLayout(); content.setContentsMargins(30,28,30,24); content.setSpacing(17); main.addLayout(content,1)
        top=QHBoxLayout(); titlebox=QVBoxLayout(); titlebox.addWidget(label('让档案，从纸面走向有序','title')); titlebox.addWidget(label('扫描件采集工作台  /  导入 → 识别 → 核对 → 导出','subtitle')); top.addLayout(titlebox); top.addStretch(); top.addWidget(label('●  离线 OCR','pill')); content.addLayout(top)
        self.metrics=label('','section'); content.addWidget(self.metrics)
        actions=QHBoxLayout(); self.import_btn=button('＋ 导入文件',self.import_files,True); actions.addWidget(self.import_btn)
        self.folder_btn=button('导入文件夹',self.import_folder); actions.addWidget(self.folder_btn)
        self.run_btn=button('开始识别',self.start,True); actions.addWidget(self.run_btn)
        self.stop_btn=button('停止',self.stop); self.stop_btn.setEnabled(False); actions.addWidget(self.stop_btn)
        self.redo_btn=button('重新识别',self.reprocess); actions.addWidget(self.redo_btn)
        actions.addStretch(); self.delete_btn=button('移除',self.remove); actions.addWidget(self.delete_btn)
        actions.addWidget(button('分开导出 Excel',self.export)); actions.addWidget(button('核对记录',lambda:self.export(True))); content.addLayout(actions)
        self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(['文件 / 扫描件','处理状态','页数','核对提示'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch); self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        self.table.setColumnWidth(1,110); self.table.setColumnWidth(2,65); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.verticalHeader().hide(); self.table.setAlternatingRowColors(True)
        self.table.currentCellChanged.connect(self.select); self.table.setMinimumHeight(130); self.table.setMaximumHeight(240)
        content.addWidget(self.table)
        self.empty=label('从一份扫描件开始\n\n导入 PDF、JPG、PNG 或多页 TIFF，识别结果会显示在这里。','subtitle'); self.empty.setAlignment(Qt.AlignCenter); content.addWidget(self.empty)
        splitter=QSplitter(Qt.Horizontal); content.addWidget(splitter,1)
        left=QWidget(); ll=QVBoxLayout(left); ll.setContentsMargins(0,0,12,0)
        heading=QHBoxLayout(); heading.addWidget(label('原件与识别原文','section')); heading.addStretch(); self.page_label=label(''); heading.addWidget(self.page_label); heading.addWidget(button('‹',lambda:self.turn(-1))); heading.addWidget(button('›',lambda:self.turn(1))); ll.addLayout(heading)
        self.tabs=QTabWidget(); ll.addWidget(self.tabs,1)
        self.image=QLabel('选择一个文件，查看原件'); self.image.setAlignment(Qt.AlignCenter)
        self.image_area=QScrollArea(); self.image_area.setWidgetResizable(True); self.image_area.setWidget(self.image); self.tabs.addTab(self.image_area,'扫描原件')
        self.raw=QPlainTextEdit(); self.raw.setReadOnly(True); self.raw.setPlaceholderText('识别后保留全部原文，便于逐项核对。'); self.tabs.addTab(self.raw,'OCR 原文')
        splitter.addWidget(left)
        right=QWidget(); rr=QVBoxLayout(right); rr.setContentsMargins(12,0,0,0); rr.addWidget(label('字段核对','section'))
        self.unit_check=QCheckBox('归档单位跟随责任者（按模板字典匹配）'); self.unit_check.setChecked(self.auto_unit); self.unit_check.toggled.connect(self.toggle_unit); rr.addWidget(self.unit_check)
        self.hint=label('自动提取仅作候选，请对照原件确认。','subtitle'); self.hint.setWordWrap(True); rr.addWidget(self.hint)
        formwrap=QWidget(); self.form=QFormLayout(formwrap); self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow); self.form.setSpacing(12); self.form.setContentsMargins(0,10,6,10)
        self.form_scroll=QScrollArea(); self.form_scroll.setWidgetResizable(True); self.form_scroll.setWidget(formwrap); rr.addWidget(self.form_scroll,1)
        self.review_btn=button('确认字段 · 标记已核对',self.review,True); rr.addWidget(self.review_btn)
        splitter.addWidget(right); splitter.setSizes([650,400])
        self.progress=QProgressBar(); self.progress.hide(); content.addWidget(self.progress)
        self.status=label('就绪 · '+('标准模板：'+self.template_sheet if self.use_template else '自定义核对工作簿')+' · 所有材料保留在本机','subtitle'); content.addWidget(self.status)
        self.build_form(); self.refresh(); self.autosave=QTimer(self); self.autosave.timeout.connect(self.save); self.autosave.start(1500)
    def busy(self):return (self.worker is not None and self.worker.isRunning()) or (self.export_worker is not None and self.export_worker.isRunning())
    def build_form(self):
        while self.form.rowCount():self.form.removeRow(0)
        self.inputs={}
        priority=['文件名称','责任单位','日期','文号','页数','年度']
        display_fields=sorted(self.fields,key=lambda f:priority.index(canonical(f)) if canonical(f) in priority else 100+self.fields.index(f))
        for field in display_fields:
            edit=ChoiceEdit(self.choices[field]) if self.use_template and field in self.choices else QLineEdit(); edit.setPlaceholderText('未提取 · 请核对填写'); edit.textEdited.connect(lambda _=None,f=field:self.changed(f)); self.form.addRow(field,edit); self.inputs[field]=edit
    def changed(self,field=None):
        if 0<=self.current<len(self.records):
            r=self.records[self.current]; r['values']={k:v.text() for k,v in self.inputs.items()}; r['status']='待核对'; link_record(r,self.choices.get('归档单位',[]) if self.use_template else [],self.auto_unit)
            if '归档单位' in self.inputs:self.inputs['归档单位'].setText(r['values'].get('归档单位',''))
            self.dirty=True; self.refresh()
    def toggle_unit(self,enabled):
        self.auto_unit=enabled
        for record in self.records:link_record(record,self.choices.get('归档单位',[]) if self.use_template else [],enabled)
        self.dirty=True; self.load_record();self.save()
    def save(self):
        if not self.dirty:return
        try:
            self.state_path.parent.mkdir(parents=True,exist_ok=True)
            temp=self.state_path.with_suffix('.tmp'); temp.write_text(json.dumps({'fields':self.fields,'records':self.records,'model':self.model,'auto_unit':self.auto_unit,'use_template':self.use_template,'template_path':self.template_path,'template_sheet':self.template_sheet},ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(self.state_path); self.dirty=False
        except OSError as error:
            self.status.setText('保存失败，请导出结果备份：'+str(error))
            if not self.save_error_shown:
                self.save_error_shown=True; QMessageBox.warning(self,'本地保存失败',str(error))
    def add_paths(self,paths):
        known={os.path.normcase(os.path.abspath(r['path'])) for r in self.records}
        for path in paths:
            key=os.path.normcase(os.path.abspath(path))
            if Path(path).suffix.lower() in SUPPORTED and key not in known:
                self.records.append({'path':os.path.abspath(path),'status':'待识别','values':{},'text':''}); known.add(key)
        self.dirty=True; self.refresh()
        if self.current<0 and self.records:self.table.selectRow(0)
    def import_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'选择扫描件','','扫描件 (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)'); self.add_paths(paths)
    def import_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'选择扫描件文件夹（包含子文件夹）')
        if folder:
            try:self.add_paths(sorted(str(p) for p in Path(folder).rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED))
            except OSError as e:QMessageBox.warning(self,'文件夹读取失败',str(e))
    def refresh(self):
        self.table.blockSignals(True); self.table.setRowCount(len(self.records))
        for row,r in enumerate(self.records):
            missing=[f for f in self.fields if not r.get('values',{}).get(f) and canonical(f) in ('文件名称','文号','日期','责任单位','页数')]
            hint=r.get('warning','') or (('待填：'+'、'.join(missing)) if missing else '请对照原件确认')
            for col,value in enumerate([Path(r['path']).name,r['status'],str(r.get('pages','—')),hint]):
                item=QTableWidgetItem(value); item.setToolTip(r['path'] if col==0 else hint)
                if col==1:item.setForeground(QColor('#18765d' if r['status']=='已核对' else '#b17829'))
                self.table.setItem(row,col,item)
            self.table.setRowHeight(row,44)
        if self.current>=0:self.table.selectRow(self.current)
        self.table.blockSignals(False)
        reviewed=sum(r['status']=='已核对' for r in self.records); done=sum(bool(r.get('text')) for r in self.records)
        self.metrics.setText(f'{len(self.records):02d}  份扫描件     /     {done:02d}  已识别     /     {reviewed:02d}  已核对')
        self.empty.setVisible(not self.records); self.review_btn.setEnabled(0<=self.current<len(self.records) and bool(self.records[self.current].get('text')) and not self.busy())
    def select(self,row,*_):
        self.current=row; self.page=0; self.load_record()
    def load_record(self):
        valid=0<=self.current<len(self.records); r=self.records[self.current] if valid else {}
        for field,edit in self.inputs.items():
            edit.setText(r.get('values',{}).get(field,'')); edit.setEnabled(valid and not self.busy() and not (field=='归档单位' and self.auto_unit))
            info=r.get('evidence',{}).get(field,{})
            details=[info.get('status','尚无提取依据')]
            for candidate in info.get('candidates',[]):
                details.append(f"第{candidate.get('page','—')}页 / {candidate.get('source','')} / 原始候选：{candidate.get('raw','')} / 规范化：{candidate.get('value','')} / {candidate.get('issue','')}")
            edit.setToolTip('\n'.join(details))
        self.raw.setPlainText(r.get('text','')); self.hint.setText(r.get('warning','') or '空白字段需要补充；修改后需重新确认。')
        self.preview(); self.refresh()
    def turn(self,delta):
        if 0<=self.current<len(self.records):
            self.page=max(0,min(self.page+delta,self.preview_pages-1)); self.preview()
    def preview(self):
        self.preview_pages=1
        if not 0<=self.current<len(self.records):self.image.setText('选择一个文件，查看原件'); self.page_label.setText(''); return
        path=self.records[self.current]['path']
        try:
            import fitz
            from PIL import Image,ImageOps
            if Path(path).suffix.lower()=='.pdf':
                with fitz.open(path) as doc:
                    if doc.needs_pass:raise ValueError('PDF已加密')
                    self.preview_pages=len(doc); p=doc[min(self.page,len(doc)-1)]; scale=min(1.5,1400/max(p.rect.width,p.rect.height)); pix=p.get_pixmap(matrix=fitz.Matrix(scale,scale),colorspace=fitz.csRGB,alpha=False)
                    qimage=QImage(pix.samples,pix.width,pix.height,pix.stride,QImage.Format_RGB888).copy()
            else:
                with Image.open(path) as img:
                    self.preview_pages=getattr(img,'n_frames',1); img.seek(min(self.page,self.preview_pages-1)); img=ImageOps.exif_transpose(img).convert('RGB'); img.thumbnail((1200,1600)); data=img.tobytes(); qimage=QImage(data,img.width,img.height,img.width*3,QImage.Format_RGB888).copy()
            pixmap=QPixmap.fromImage(qimage); width=max(320,self.image_area.viewport().width()-24)
            self.image.setPixmap(pixmap.scaledToWidth(width,Qt.SmoothTransformation)); self.page_label.setText(f'{self.page+1} / {self.preview_pages}')
        except Exception as e:self.image.setText('无法预览原件\n'+str(e)); self.page_label.setText('')
    def set_busy(self,enabled):
        for widget in [self.import_btn,self.folder_btn,self.run_btn,self.delete_btn,self.redo_btn]:widget.setEnabled(not enabled)
        for field,widget in self.inputs.items():widget.setEnabled(not enabled and not (field=='归档单位' and self.auto_unit))
        self.unit_check.setEnabled(not enabled)
        self.stop_btn.setEnabled(enabled); self.progress.setVisible(enabled)
    def reprocess(self):
        if self.busy() or not 0<=self.current<len(self.records):return
        if QMessageBox.question(self,'重新识别当前文件','将使用新版规则重新读取，并替换当前文件的字段和人工修改。是否继续？')!=QMessageBox.Yes:return
        self.launch_jobs([(self.current,self.records[self.current]['path'])])
    def launch_jobs(self,jobs):
        self.worker=Worker(jobs,self.fields.copy(),self.model); self.worker.result.connect(self.received); self.worker.message.connect(self.status.setText); self.worker.finished.connect(self.finished)
        self.progress.setRange(0,len(jobs)); self.progress.setValue(0); self.set_busy(True); self.worker.start(); self.refresh()
    def start(self):
        if self.busy():return
        jobs=[(i,r['path']) for i,r in enumerate(self.records) if r['status'] in ('待识别','处理失败')]
        if not jobs:QMessageBox.information(self,'没有待处理文件','请导入新文件。已识别文件不会被覆盖。'); return
        self.launch_jobs(jobs)
    def received(self,index,result):
        if self.use_template and result.get('values'):
            for field,value in list(result['values'].items()):
                converted=standard_value(field,value,self.choices.get(field,[]))
                if converted!=value:
                    result['values'][field]=converted
                    note=f'{field}原文“{value}”按模板字典映射为“{converted}”'
                    result['warning']='；'.join(filter(None,[result.get('warning',''),note]))
        link_record(result,self.choices.get('归档单位',[]) if self.use_template else [],self.auto_unit)
        self.records[index].update(result); self.dirty=True; self.progress.setValue(self.progress.value()+1)
        if self.current==index:self.load_record()
        else:self.refresh()
    def finished(self):
        self.set_busy(False); self.status.setText('本轮处理结束 · 请核对字段后导出 Excel'); self.load_record(); self.save()
    def stop(self):
        if self.busy():(self.export_worker if self.export_worker is not None and self.export_worker.isRunning() else self.worker).requestInterruption(); self.status.setText('已请求停止 · 当前OCR运算或本地模型响应结束后停止'); self.stop_btn.setEnabled(False)
    def review(self):
        if not 0<=self.current<len(self.records):return
        for field,widget in self.inputs.items():
            if canonical(field)=='日期' and widget.text().strip():
                normalized,error=normalize_date(widget.text())
                if error:
                    QMessageBox.warning(self,'日期需校正',field+'：'+error+'。请填写有效的年月日。'); return
                widget.setText(normalized); self.records[self.current]['values'][field]=normalized
        missing=[k for k,w in self.inputs.items() if not w.text().strip() and canonical(k) in ('文件名称','文号','日期','责任单位','页数')]
        if missing and QMessageBox.question(self,'仍有空白字段','以下字段为空：'+ '、'.join(missing)+'\n仍标记为已核对？')!=QMessageBox.Yes:return
        self.records[self.current]['status']='已核对'; self.dirty=True; self.refresh(); self.save()
    def remove(self):
        if self.busy() or self.current<0:return
        if QMessageBox.question(self,'移除记录','只移除本应用中的记录，原文件保留。是否继续？')!=QMessageBox.Yes:return
        self.records.pop(self.current); self.current=-1; self.dirty=True; self.refresh(); self.load_record()
        if self.records:self.table.selectRow(0)
    def export(self,report=False):
        if self.busy():QMessageBox.information(self,'任务进行中','请等待当前识别或导出完成。');return
        records=[r for r in self.records if r.get('text') and r['status'] not in ('处理失败','待识别')]
        if not records:QMessageBox.information(self,'暂无可导出结果','请先完成至少一份文件的识别。'); return
        skipped=len(self.records)-len(records); pending=sum(r['status']!='已核对' for r in records)
        if (pending or skipped) and QMessageBox.question(self,'导出范围确认',f'将导出 {len(records)} 份记录，其中 {pending} 份尚未核对。\n{skipped} 份未识别或失败的记录不导出。\n是否继续？')!=QMessageBox.Yes:return
        if not report:
            if not self.use_template:QMessageBox.warning(self,'需要原模板','请在设置中选择原标准模板；标准导出不使用自定义工作簿。');return
            folder=QFileDialog.getExistingDirectory(self,'选择输出文件夹：一份PDF对应一个原模板Excel')
            if not folder:return
            import copy
            jobs=[(i,copy.deepcopy(r)) for i,r in enumerate(self.records) if r.get('text') and r['status'] not in ('处理失败','待识别')]
            self.export_worker=ExportWorker(jobs,folder,self.template_path,self.template_sheet)
            self.export_worker.item.connect(self.export_received);self.export_worker.message.connect(self.status.setText);self.export_worker.finished.connect(self.export_finished)
            self.progress.setRange(0,len(jobs));self.progress.setValue(0);self.set_busy(True);self.export_worker.start();self.refresh();return
        path,_=QFileDialog.getSaveFileName(self,'导出核对记录','档案核对记录.json','JSON (*.json)')
        if path:
            if not path.lower().endswith('.json'):path+='.json'
            try:
                Path(path).write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
                QMessageBox.information(self,'核对记录已保存','原文和提取依据已保存为JSON，不生成其他格式的Excel：\n'+path)
            except Exception as e:QMessageBox.warning(self,'保存失败',str(e))
    def export_received(self,index,result):
        self.records[index]['export_path']=result['output'];self.records[index]['export_error']=result['error'];self.dirty=True
        self.progress.setValue(self.progress.value()+1)
    def export_finished(self):
        self.set_busy(False);self.refresh();self.save()
        results=self.export_worker.results;failed=[r for r in results if r['error']];done=len(results)-len(failed)
        self.status.setText(f'分开导出完成：成功{done}份，失败{len(failed)}份')
        details='\n'.join(Path(r['source']).name+'：'+r['error'] for r in failed)
        if self.export_worker.isInterruptionRequested():details='已停止，未处理文件可再次导出。\n'+details
        QMessageBox.information(self,'批量导出结果',f'成功 {done} 份，失败 {len(failed)} 份。每份文件独立使用原模板。\n'+details)
    def settings(self):
        if self.busy():QMessageBox.information(self,'正在处理','请等待当前任务结束后修改设置。'); return
        dlg=QDialog(self); dlg.setWindowTitle('采集模板与本地模型'); dlg.resize(620,680); layout=QVBoxLayout(dlg)
        layout.addWidget(label('导出格式','section'))
        mode=QComboBox();mode.addItems(['原标准模板（保留工作表、表头和下拉字典）','自定义核对工作簿']);mode.setCurrentIndex(0 if self.use_template else 1);layout.addWidget(mode)
        path_edit=QLineEdit(self.template_path);path_edit.setReadOnly(True);layout.addWidget(path_edit)
        sheets=QComboBox();layout.addWidget(sheets)
        edit=QPlainTextEdit('\n'.join(self.fields));layout.addWidget(edit)
        def sync_fields():
            if mode.currentIndex()==0 and sheets.currentText():
                meta=inspect_template(path_edit.text(),sheets.currentText());edit.setPlainText('\n'.join(meta['headers']))
            edit.setReadOnly(mode.currentIndex()==0)
        def load_template(path,selected=None):
            meta=inspect_template(path,selected);path_edit.setText(path);sheets.blockSignals(True);sheets.clear();sheets.addItems(meta['sheets']);sheets.setCurrentText(meta['sheet']);sheets.blockSignals(False);sync_fields()
        def choose_template():
            path,_=QFileDialog.getOpenFileName(dlg,'选择标准导出模板','','Excel (*.xlsx)')
            if not path:return
            try:load_template(path)
            except Exception as e:QMessageBox.warning(dlg,'模板读取失败',str(e))
        layout.addWidget(button('选择其他标准 Excel 模板',choose_template))
        sheets.currentTextChanged.connect(sync_fields);mode.currentIndexChanged.connect(sync_fields)
        try:load_template(self.template_path,self.template_sheet)
        except Exception:mode.setCurrentIndex(1)
        layout.addWidget(label('可选：本机 Ollama 模型','section'));model=QLineEdit(self.model);model.setPlaceholderText('留空使用离线 OCR 与规则');layout.addWidget(model)
        note=label('标准模式只填选中的目录表，其他目录表和字典保留。\n日期按有效年月日写入，字典字段从下拉项选择。\n本地模型仅连接127.0.0.1；通用模型需提前安装。\n切换表头后，已有同名字段保留，新增字段重新分析并进入待核对。','subtitle');note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);layout.addWidget(buttons)
        if dlg.exec()!=QDialog.Accepted:return
        use_template=mode.currentIndex()==0
        fields=list(dict.fromkeys(line.strip() for line in edit.toPlainText().splitlines() if line.strip()))
        if not fields or len(fields)>60 or any(len(f)>80 for f in fields):QMessageBox.warning(self,'字段无效','请设置1—60个字段，每个字段最多80个字符。');return
        try:
            if use_template:
                import hashlib,shutil
                incoming=Path(path_edit.text());dest=self.state_path.parent/'templates'/(hashlib.sha256(incoming.read_bytes()).hexdigest()[:16]+'.xlsx');dest.parent.mkdir(parents=True,exist_ok=True)
                if incoming.resolve()!=dest.resolve():shutil.copy2(incoming,dest)
                self.template_path=str(dest);self.template_sheet=sheets.currentText();meta=inspect_template(dest,self.template_sheet);fields=meta['headers'];self.choices=meta['choices']
            else:self.choices={}
        except Exception as e:QMessageBox.warning(self,'模板保存失败',str(e));return
        self.use_template=use_template
        if fields!=self.fields:
            self.fields=fields
            for record in self.records:
                old=record.get('values',{});record['values']={k:v for k,v in old.items() if k in fields}
                if record.get('text'):
                    candidates,evidence,warnings=extract_details(record['text'],fields,record.get('pages',0),rows=record.get('ocr_rows') or None)
                    for k,v in candidates.items():record['values'].setdefault(k,v)
                    record['evidence']=evidence;record['status']='待核对';record['warning']='；'.join(warnings)
        for record in self.records:link_record(record,self.choices.get('归档单位',[]) if self.use_template else [],self.auto_unit)
        self.build_form();self.model=model.text().strip();self.dirty=True;self.load_record();self.save()
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'image'):QTimer.singleShot(100,self.preview)
    def closeEvent(self,event):
        if self.busy():
            self.stop(); QMessageBox.information(self,'正在停止','停止请求已提交。当前运算完成后请再次关闭窗口。'); event.ignore(); return
        self.save()
        if self.dirty and QMessageBox.question(self,'尚未保存','本地保存失败，关闭会丢失最新修改。仍要关闭？')!=QMessageBox.Yes:event.ignore(); return
        event.accept()

def main():
    app=QApplication(sys.argv); app.setStyle('Fusion'); app.setStyleSheet(STYLE); app.setFont(QFont('Microsoft YaHei UI',10))
    window=Window(); window.show(); sys.exit(app.exec())

if __name__=='__main__':main()
