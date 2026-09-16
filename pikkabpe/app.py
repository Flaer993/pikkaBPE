import json
import os
import sys
import time
import uuid
import subprocess
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRect, QProcess, QProcessEnvironment
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QFormLayout, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QMessageBox, QFileDialog, QCheckBox, QSplitter, QTextEdit, QInputDialog)

from . import __version__
from .paths import data_root
from .store import Store
from .motion import Motion
from .serial_link import Link


STYLE = '''
QMainWindow,QWidget {background:#171b20;color:#ecedef;font-family:Segoe UI;font-size:13px;}
QLabel#brand {font-size:30px;font-weight:700;color:#ff8a32;}
QLabel#subtitle {color:#a0a8b1;font-size:12px;}
QPushButton {background:#303740;border:1px solid #46505b;padding:10px 15px;border-radius:6px;}
QPushButton:hover {border-color:#ff8a32;background:#3e4146;}
QPushButton#primary {background:#f5822b;color:#171b20;font-weight:700;border:none;}
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QTextEdit {background:#232931;border:1px solid #3d4650;padding:7px;border-radius:4px;}
QTabWidget::pane {border:1px solid #353e47;}
QTabBar::tab {background:#252b33;padding:12px 20px;}
QTabBar::tab:selected {color:#ff8a32;border-bottom:2px solid #ff8a32;}
QHeaderView::section {background:#303740;color:#dce0e4;padding:8px;border:0;}
QTableWidget {background:#20262d;gridline-color:#333c46;selection-background-color:#75451f;}
'''


class Video(QLabel):
    def __init__(self):
        super().__init__('КАМЕРА ОТКЛЮЧЕНА\nПодключите C920 или откройте видео')
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(640, 360)
        self.frame = None
        self.roi = None
        self.start = None
        self.end = None
        self.setStyleSheet('background:#101419;border:1px solid #39434e;color:#7f8995;')

    def display_rect(self):
        if self.frame is None:
            return QRect()
        h, w = self.frame.shape[:2]
        scale = min(self.width()/w, self.height()/h)
        rw, rh = round(w*scale), round(h*scale)
        return QRect((self.width()-rw)//2, (self.height()-rh)//2, rw, rh)

    def mousePressEvent(self, event):
        if self.frame is not None and self.display_rect().contains(event.position().toPoint()):
            self.start = event.position().toPoint()
            self.end = self.start

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start is None:
            return
        rect = QRect(self.start, event.position().toPoint()).normalized().intersected(self.display_rect())
        view = self.display_rect()
        if rect.width() > 8 and rect.height() > 8:
            self.roi = ((rect.x()-view.x())/view.width(), (rect.y()-view.y())/view.height(), rect.width()/view.width(), rect.height()/view.height())
        self.start = self.end = None
        self.update()

    def paintEvent(self, event):
        if self.frame is None:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888)
        view = self.display_rect()
        painter.drawImage(view, image)
        painter.setPen(QPen(Qt.GlobalColor.darkYellow, 2))
        if self.roi:
            x,y,w,h = self.roi
            painter.drawRect(QRect(view.x()+round(x*view.width()), view.y()+round(y*view.height()), round(w*view.width()), round(h*view.height())))
        if self.start is not None and self.end is not None:
            painter.drawRect(QRect(self.start, self.end).normalized())


class Capture(QThread):
    frame = Signal(object)
    error = Signal(str)
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.keep = True
        self.pending = False

    def run(self):
        cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW if isinstance(self.source, int) and os.name == 'nt' else cv2.CAP_ANY)
        if not cap.isOpened():
            self.error.emit('Источник видео недоступен')
            return
        if isinstance(self.source, int):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_FPS, 30)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        while self.keep:
            ok, frame = cap.read()
            if not ok:
                self.error.emit('Видео завершено или камера отключилась')
                break
            if not self.pending:
                self.pending = True
                self.frame.emit(frame)
            if not isinstance(self.source, int):
                self.msleep(round(1000/min(60, max(1, fps))))
        cap.release()


class Work(QThread):
    done = Signal(object)
    error = Signal(str)
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.error.emit(str(exc))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.root = data_root()
        self.db = Store(self.root/'warehouse.db')
        self.motion = Motion()
        self.link = Link()
        self.capture = None
        self.workers = []
        self.training = None
        self.frame_count = 0
        self.last_candidate = 0
        self.last_follow = 0
        self.predictor = None
        self.setWindowTitle(f'pikkāBPE / операторская станция {__version__}')
        self.resize(1400, 900)
        base = QWidget(); self.setCentralWidget(base); layout = QVBoxLayout(base)
        brand = QLabel('pikkāBPE   /   VISION CONTROL'); brand.setObjectName('brand'); layout.addWidget(brand)
        sub = QLabel('ОДНА ЗОНА   •   ОБУЧЕНИЕ С ОПЕРАТОРОМ   •   ЛОКАЛЬНЫЙ УЧЁТ'); sub.setObjectName('subtitle'); layout.addWidget(sub)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.build_camera(); self.build_inventory(); self.build_training(); self.build_updates()
        self.status = QLabel(f'Данные: {self.root}'); layout.addWidget(self.status)
        self.refresh()
        self.timer = QTimer(self); self.timer.timeout.connect(self.send_target); self.timer.start(100)

    def button(self, text, fn, primary=False):
        b=QPushButton(text); b.clicked.connect(lambda: self.guard(fn))
        if primary: b.setObjectName('primary')
        return b

    def guard(self, fn):
        try: fn()
        except Exception as exc:
            QMessageBox.warning(self, 'pikkāBPE', str(exc))

    def build_camera(self):
        page=QWidget(); self.tabs.addTab(page,'Наблюдение'); row=QHBoxLayout(page)
        left=QVBoxLayout(); row.addLayout(left, 3)
        self.video=Video(); left.addWidget(self.video,1)
        buttons=QHBoxLayout(); left.addLayout(buttons)
        self.camera_id=QSpinBox(); self.camera_id.setRange(0,10); buttons.addWidget(self.camera_id)
        buttons.addWidget(self.button('Включить камеру',lambda:self.start_capture(self.camera_id.value()),True))
        buttons.addWidget(self.button('Открыть видео',self.open_video))
        buttons.addWidget(self.button('Стоп',self.stop_capture))
        self.motion_note=QLabel('Движение создаёт подсказку. Остатки меняются после подтверждения.'); self.motion_note.setWordWrap(True); left.addWidget(self.motion_note)
        panel=QVBoxLayout(); row.addLayout(panel,1); form=QFormLayout(); panel.addLayout(form)
        self.operator=QLineEdit(); self.operator.setPlaceholderText('Имя оператора'); form.addRow('Оператор',self.operator)
        self.barcode=QLineEdit(); self.barcode.setPlaceholderText('Штрихкод со сканера'); form.addRow('Товар',self.barcode)
        self.barcode.returnPressed.connect(self.lookup)
        self.product_name=QLabel('Введите код товара'); self.product_name.setWordWrap(True); form.addRow('',self.product_name)
        panel.addWidget(self.button('Найти / добавить товар',self.lookup))
        self.employee=QComboBox(); form.addRow('Сотрудник',self.employee)
        self.location=QComboBox(); form.addRow('Размещение',self.location)
        self.kind=QComboBox()
        for title, key in [('Взятие','take'),('Возврат','return'),('Размещение поступления','place')]: self.kind.addItem(title,key)
        form.addRow('Операция',self.kind)
        self.quantity=QSpinBox(); self.quantity.setRange(1,100000); form.addRow('Количество, шт',self.quantity)
        self.receipt_combo=QComboBox(); form.addRow('Поступление',self.receipt_combo)
        panel.addWidget(self.button('В очередь подтверждения',self.propose,True))
        panel.addWidget(QLabel('ПОДВЕС / USB–UART'))
        self.com=QLineEdit(); self.com.setPlaceholderText('COM3'); panel.addWidget(self.com)
        panel.addWidget(self.button('Подключить контроллер',lambda:self.link.open(self.com.text())))
        self.pan=QDoubleSpinBox(); self.pan.setRange(-60,60); self.pan.setSuffix('°'); form2=QFormLayout(); panel.addLayout(form2); form2.addRow('Поворот',self.pan)
        self.tilt=QDoubleSpinBox(); self.tilt.setRange(-45,45); self.tilt.setSuffix('°'); form2.addRow('Наклон',self.tilt)
        self.pan.valueChanged.connect(self.motion.camera_moved); self.tilt.valueChanged.connect(self.motion.camera_moved)
        self.follow=QCheckBox('Сопровождать движение'); panel.addWidget(self.follow)
        panel.addWidget(self.button('Остановить сопровождение',lambda:self.follow.setChecked(False)))
        self.link_state=QLabel('Контроллер не подключён'); panel.addWidget(self.link_state)
        panel.addStretch()

    def build_inventory(self):
        page=QWidget(); self.tabs.addTab(page,'События и остатки'); box=QVBoxLayout(page)
        buttons=QHBoxLayout(); box.addLayout(buttons)
        for title, fn in [('Подтвердить',lambda:self.review(True)),('Отклонить',lambda:self.review(False)),('Кадр',self.show_evidence),('Поступление',self.add_receipt),('Сотрудник',lambda:self.add_catalog('employees')),('Новое место',lambda:self.add_catalog('locations')),('Экспорт CSV',self.export),('Резервная копия',self.backup),('Обновить',self.refresh)]: buttons.addWidget(self.button(title,fn))
        self.events=QTableWidget(); self.events.setSelectionBehavior(QTableWidget.SelectRows); box.addWidget(self.events,3)
        box.addWidget(QLabel('ПОДТВЕРЖДЁННЫЕ ОСТАТКИ / ОЖИДАЕМЫЕ ПОСТУПЛЕНИЯ'))
        lower=QHBoxLayout(); box.addLayout(lower,2)
        self.stock=QTableWidget(); lower.addWidget(self.stock)
        self.receipts=QTableWidget(); lower.addWidget(self.receipts)

    def build_training(self):
        page=QWidget(); self.tabs.addTab(page,'Обучение'); box=QVBoxLayout(page)
        note=QLabel('Выделите предмет рамкой на вкладке «Наблюдение». Укажите его штрихкод.\nДля обучения нужны разные сессии съёмки: проверочные сессии не попадают в обучение.\nМодель классифицирует выделенный предмет; сотрудника и складскую операцию подтверждает оператор.'); note.setWordWrap(True); box.addWidget(note)
        form=QFormLayout(); box.addLayout(form)
        self.session=QLineEdit(time.strftime('%Y-%m-%d')+'-home-01'); form.addRow('Сессия съёмки',self.session)
        self.source=QLineEdit('Собственная съёмка'); form.addRow('Источник / права',self.source)
        self.epochs=QSpinBox(); self.epochs.setRange(1,100); self.epochs.setValue(10); form.addRow('Эпохи',self.epochs)
        local_python=Path('D:/pikkaBPE/.venv/Scripts/python.exe')
        self.train_python=QLineEdit(str(Path(sys.executable)) if not getattr(sys,'frozen',False) else (str(local_python) if local_python.exists() else '')); form.addRow('Python окружения обучения',self.train_python)
        row=QHBoxLayout(); box.addLayout(row)
        row.addWidget(self.button('Сохранить выделенный пример',self.save_label,True))
        row.addWidget(self.button('Импортировать изображение',self.import_image))
        row.addWidget(self.button('Обучить на NVIDIA',self.train))
        row.addWidget(self.button('Остановить обучение',self.stop_training))
        row.addWidget(self.button('Активировать модель',self.promote))
        row.addWidget(self.button('Распознать выделенный предмет',self.predict))
        self.train_log=QTextEdit(); self.train_log.setReadOnly(True); box.addWidget(self.train_log)

    def build_updates(self):
        page=QWidget(); self.tabs.addTab(page,'Система'); box=QVBoxLayout(page)
        note=QLabel('pikkāBPE '+__version__+'\nОбновления из приватного GitHub: Flaer993/pikkaBPE\nУстановка только после подтверждения. Данные хранятся отдельно от приложения.\nВ этой версии обновление прошивки выполняется через ST-Link после проверки платы.'); note.setWordWrap(True); box.addWidget(note)
        box.addWidget(self.button('Проверить обновления клиента',self.check_updates,True))
        box.addWidget(self.button('Открыть папку данных',lambda:os.startfile(self.root)))
        box.addWidget(self.button('Открыть журнал аудита',self.show_audit))
        self.update_note=QLabel(''); self.update_note.setWordWrap(True); box.addWidget(self.update_note); box.addStretch()

    def start_capture(self, source):
        self.stop_capture()
        self.video.roi=None
        self.motion.camera_moved()
        self.capture=Capture(source)
        self.capture.frame.connect(self.on_frame)
        self.capture.error.connect(self.status.setText)
        self.capture.start()

    def stop_capture(self):
        self.follow.setChecked(False)
        if self.capture:
            self.capture.keep=False
            if not self.capture.wait(3000):
                raise RuntimeError('Камера ещё завершает чтение. Повторите остановку.')
            self.capture=None

    def open_video(self):
        path,_=QFileDialog.getOpenFileName(self,'Видео','','Видео (*.mp4 *.avi *.mkv *.mov)')
        if path: self.start_capture(path)

    def on_frame(self,frame):
        self.video.frame=frame; self.video.update()
        if self.capture: self.capture.pending=False
        self.frame_count+=1
        if self.frame_count%3: return
        roi=self.motion.detect(frame)
        if roi:
            self.motion_note.setText('Обнаружено движение. Проверьте товар, сотрудника и операцию.')
            if time.monotonic()-self.last_candidate>10:
                self.last_candidate=time.monotonic()
                with self.db.connect() as db: self.db.audit(db,'motion_observed',{'pan_command':self.pan.value(),'tilt_command':self.tilt.value()})
            if self.follow.isChecked() and self.link.port and time.monotonic()-self.last_follow>.4:
                self.last_follow=time.monotonic()
                x,y,w,h=roi; dx=x+w/2-.5; dy=y+h/2-.5
                if abs(dx)>.12: self.pan.setValue(self.pan.value()+max(-2,min(2,dx*6)))
                if abs(dy)>.12: self.tilt.setValue(self.tilt.value()+max(-2,min(2,dy*4)))

    def send_target(self):
        try: self.link.send(self.pan.value(),self.tilt.value())
        except Exception as exc:
            self.follow.setChecked(False); self.link.close(); self.status.setText(str(exc))
        self.link_state.setText(self.link.status)

    def lookup(self):
        code=self.barcode.text().strip()
        if not code: return
        rows=self.db.rows('SELECT name FROM products WHERE barcode=?',(code,))
        if not rows:
            name,ok=QInputDialog.getText(self,'Новый товар',f'Название для {code}:')
            if not ok: return
            self.db.catalog('products',code,name); rows=[{'name':name}]
        self.product_name.setText(rows[0]['name'])

    def add_catalog(self,table):
        code,ok=QInputDialog.getText(self,'Справочник','Код:')
        if not ok: return
        name,ok=QInputDialog.getText(self,'Справочник','Имя / название:')
        if ok: self.db.catalog(table,code,name); self.refresh()

    def add_receipt(self):
        code,ok=QInputDialog.getText(self,'Поступление','Штрихкод существующего товара:')
        if not ok: return
        quantity,ok=QInputDialog.getInt(self,'Поступление','Ожидаемое количество:',1,1,100000)
        if ok: self.db.receipt(code,quantity); self.refresh()

    def evidence(self, crop=False):
        if self.video.frame is None: raise ValueError('Нет кадра')
        frame=self.video.frame.copy()
        if crop:
            if not self.video.roi: raise ValueError('Выделите предмет мышью на изображении')
            x,y,w,h=self.video.roi; height,width=frame.shape[:2]
            frame=frame[int(y*height):min(height,int((y+h)*height)),int(x*width):min(width,int((x+w)*width))]
            if frame.size==0: raise ValueError('Пустая область')
        if sum(p.stat().st_size for p in (self.root/'evidence').glob('*.jpg'))>100*1024**3:
            raise ValueError('Лимит снимков 100 ГБ. Архивируйте данные.')
        path=self.root/'evidence'/f'{uuid.uuid4()}.jpg'
        ok, encoded=cv2.imencode('.jpg',frame)
        if not ok: raise ValueError('Не удалось сохранить кадр')
        path.write_bytes(encoded.tobytes())
        return path

    def propose(self):
        code=self.barcode.text().strip()
        rid=self.receipt_combo.currentData() if self.kind.currentData()=='place' else None
        path=self.evidence() if self.video.frame is not None else None
        self.db.propose(self.kind.currentData(),code,self.quantity.value(),self.location.currentData(),self.employee.currentData(),rid,str(path) if path else None)
        self.refresh(); self.tabs.setCurrentIndex(1)

    def review(self,accept):
        row=self.events.currentRow()
        if row<0: raise ValueError('Выберите событие')
        self.db.review(self.events.item(row,0).text(),self.operator.text(),accept); self.refresh()

    def show_evidence(self):
        row=self.events.currentRow()
        if row<0: raise ValueError('Выберите событие')
        rows=self.db.rows('SELECT evidence FROM events WHERE id=?',(self.events.item(row,0).text(),))
        path=rows[0]['evidence']
        if not path or not Path(path).exists(): raise ValueError('Снимок отсутствует')
        os.startfile(path)

    @staticmethod
    def fill(table,rows,columns):
        table.setColumnCount(len(columns)); table.setHorizontalHeaderLabels([label for _,label in columns]); table.setRowCount(len(rows))
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        for r,row in enumerate(rows):
            for c,(key,_) in enumerate(columns): table.setItem(r,c,QTableWidgetItem(str(row.get(key) or '')))
        table.resizeColumnsToContents()

    def refresh(self):
        self.fill(self.events,self.db.rows('SELECT e.*,p.name FROM events e JOIN products p ON p.barcode=e.barcode ORDER BY created DESC LIMIT 500'), [('id','ID'),('created','UTC'),('kind','Операция'),('name','Товар'),('quantity','Кол-во'),('location','Место'),('employee','Сотрудник'),('status','Статус')])
        self.events.setColumnHidden(0,True)
        self.fill(self.stock,self.db.rows('SELECT s.*,p.name FROM stock s JOIN products p ON p.barcode=s.barcode'), [('barcode','Код'),('name','Товар'),('location','Место'),('quantity','Остаток')])
        receipts=self.db.rows('SELECT r.*,p.name FROM receipts r JOIN products p ON p.barcode=r.barcode ORDER BY created DESC')
        self.fill(self.receipts,receipts,[('name','Поступление'),('quantity','Ожидается'),('placed','Размещено')])
        for combo,table in [(self.employee,'employees'),(self.location,'locations')]:
            old=combo.currentData(); combo.clear()
            if table=='employees': combo.addItem('Не указан',None)
            for row in self.db.rows(f'SELECT * FROM {table} ORDER BY id'): combo.addItem(row['name'],row['id'])
            index=combo.findData(old)
            if index>=0: combo.setCurrentIndex(index)
        self.receipt_combo.clear(); self.receipt_combo.addItem('Выберите поступление',None)
        for r in receipts:
            if r['placed']<r['quantity']: self.receipt_combo.addItem(f"{r['name']} / осталось {r['quantity']-r['placed']}",r['id'])

    def save_label(self):
        code=self.barcode.text().strip()
        if not self.db.rows('SELECT 1 FROM products WHERE barcode=?',(code,)): raise ValueError('Сначала добавьте товар')
        path=self.evidence(crop=True); self.db.label(path,code,self.session.text(),self.source.text())
        self.train_log.append(f'Пример сохранён: {code}; {self.session.text()}')

    def import_image(self):
        path,_=QFileDialog.getOpenFileName(self,'Изображение из разрешённого набора','','Изображения (*.jpg *.png *.jpeg)')
        if path:
            import numpy as np
            frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
            if frame is None: raise ValueError('Изображение не прочитано')
            self.stop_capture(); self.video.frame=frame; self.video.roi=None; self.video.update(); self.tabs.setCurrentIndex(0)

    def train(self):
        if self.training and self.training.state()!=QProcess.NotRunning: raise ValueError('Обучение уже запущено')
        self.training=QProcess(self); self.training.setProcessChannelMode(QProcess.MergedChannels)
        environment=QProcessEnvironment.systemEnvironment(); environment.insert('PYTHONIOENCODING','utf-8')
        self.training.setProcessEnvironment(environment)
        self.training.readyReadStandardOutput.connect(lambda:self.train_log.append(bytes(self.training.readAllStandardOutput()).decode('utf-8',errors='replace')))
        self.training.errorOccurred.connect(lambda e:self.train_log.append('Ошибка запуска: '+self.training.errorString()))
        self.training.finished.connect(lambda code:self.train_log.append(f'Обучение завершено, код {code}. Для применения выберите модель и проверьте метрики.'))
        self.training.start(self.train_python.text(),['-u','-m','pikkabpe.train','--data',str(self.root),'--epochs',str(self.epochs.value())])

    def stop_training(self):
        if self.training: self.training.terminate()

    def promote(self):
        path,_=QFileDialog.getOpenFileName(self,'Проверенная модель',str(self.root/'models'),'Модель (*.pt)')
        if not path: return
        metrics=Path(path).with_suffix('.json')
        if not metrics.exists(): raise ValueError('Нет отчёта проверки рядом с моделью')
        report=json.loads(metrics.read_text(encoding='utf-8'))
        if QMessageBox.question(self,'Активация модели',json.dumps(report,ensure_ascii=False,indent=2)+'\nИспользовать для подсказок оператору?')!=QMessageBox.Yes: return
        (self.root/'models'/'active.json').write_text(json.dumps({'path':path,'report':report},ensure_ascii=False),encoding='utf-8')
        self.predictor=None; self.train_log.append('Модель активирована для подсказок; автоматический учёт выключен.')

    def predict(self):
        if getattr(sys,'frozen',False):
            active=json.loads((self.root/'models'/'active.json').read_text(encoding='utf-8'))
            path=self.evidence(crop=True)
            def run():
                result=subprocess.run([self.train_python.text(),'-m','pikkabpe.train','--predict',str(path),'--model',active['path']],capture_output=True,text=True,encoding='utf-8',timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env={**os.environ,'PYTHONIOENCODING':'utf-8'})
                if result.returncode: raise RuntimeError(result.stderr)
                return result.stdout
            self.background(run,self.train_log.append)
            return
        from .train import Predictor
        if self.predictor is None:
            active=json.loads((self.root/'models'/'active.json').read_text(encoding='utf-8')); self.predictor=Predictor(active['path'])
        path=self.evidence(crop=True)
        code,confidence=self.predictor.predict(path)
        self.train_log.append(f'Подсказка: {code}; оценка модели {confidence:.1%}. Требуется проверка оператором.')

    def background(self,fn,done):
        worker=Work(fn); self.workers.append(worker); worker.done.connect(done)
        worker.error.connect(lambda text:QMessageBox.warning(self,'Система',text)); worker.start()

    def check_updates(self):
        from .updates import latest
        self.update_note.setText('Проверяем GitHub…')
        self.background(latest,self.offer_update)

    def offer_update(self,release):
        if release is None: self.update_note.setText('Новых выпусков нет.'); return
        self.update_note.setText(f"Доступен {release['tag_name']}")
        if QMessageBox.question(self,'Обновление',f"Скачать {release['tag_name']} и подготовить установку?")!=QMessageBox.Yes: return
        from .updates import stage
        self.background(lambda:stage(release,self.root/'updates'),self.install_update)

    def install_update(self,path):
        if not getattr(sys,'frozen',False): self.update_note.setText(f'Обновление проверено: {path}. Для установки запустите EXE из папки.'); return
        if QMessageBox.question(self,'Установка','Закрыть клиент и установить проверенное обновление?')!=QMessageBox.Yes: return
        from .updates import install
        self.stop_capture(); self.stop_training(); self.backup(silent=True)
        install(Path(path),Path(sys.executable).parent,os.getpid()); self.close()

    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Экспорт подтверждённых операций','events.csv','CSV (*.csv)')
        if path: self.db.export(path)

    def backup(self,silent=False):
        path=self.root/'backups'/f'warehouse-{time.strftime("%Y%m%d-%H%M%S")}.db'; self.db.backup(path)
        if not silent: self.status.setText(f'Копия БД: {path}')

    def show_audit(self):
        self.train_log.setPlainText('\n'.join(json.dumps(x,ensure_ascii=False) for x in self.db.rows('SELECT * FROM audit ORDER BY id DESC LIMIT 200'))); self.tabs.setCurrentIndex(2)

    def closeEvent(self,event):
        try: self.stop_capture()
        except RuntimeError: event.ignore(); return
        if any(w.isRunning() for w in self.workers):
            QMessageBox.information(self,'Система','Дождитесь завершения загрузки / проверки.'); event.ignore(); return
        if self.training and self.training.state()!=QProcess.NotRunning:
            self.training.terminate()
            if not self.training.waitForFinished(3000): self.training.kill(); self.training.waitForFinished(3000)
        self.link.close(); event.accept()


def main():
    app=QApplication(sys.argv); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    window=Window(); window.show()
    if '--smoke-test' in sys.argv:
        QTimer.singleShot(800,lambda:window.grab().save(str(window.root/'client-preview.png')))
        QTimer.singleShot(1200,window.close)
    sys.exit(app.exec())


if __name__=='__main__': main()
