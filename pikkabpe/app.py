import json
import os
import sys
import time
import uuid
import subprocess
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRect, QProcess, QProcessEnvironment
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QFormLayout, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QMessageBox, QFileDialog, QCheckBox, QSplitter, QTextEdit, QInputDialog,
    QFrame, QScrollArea, QGridLayout, QHeaderView)

from . import __version__
from .paths import data_root
from .store import Store
from .motion import Motion
from .serial_link import Link
from .themes import stylesheet


STYLE = stylesheet('dark')


class Video(QLabel):
    def __init__(self):
        super().__init__('КАМЕРА ОТКЛЮЧЕНА\nПодключите C920 или откройте видео')
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(640, 360)
        self.frame = None
        self.roi = None
        self.start = None
        self.end = None
        self.recognition_text=''
        self.recognition_roi=None
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
        if self.recognition_text:
            if self.recognition_roi and self.recognition_roi!=(0,0,1,1):
                x,y,w,h=self.recognition_roi
                painter.setPen(QPen(Qt.green,2)); painter.drawRect(QRect(view.x()+round(x*view.width()),view.y()+round(y*view.height()),round(w*view.width()),round(h*view.height())))
            text_rect=QRect(view.x()+8,view.y()+8,max(1,view.width()-16),64)
            painter.fillRect(text_rect,Qt.black); painter.setPen(Qt.white)
            painter.drawText(text_rect.adjusted(8,4,-8,-4),Qt.AlignLeft|Qt.AlignVCenter|Qt.TextWordWrap,self.recognition_text)


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
        try: self.preferences=json.loads((self.root/'preferences.json').read_text(encoding='utf-8'))
        except (OSError,ValueError): self.preferences={}
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
        from .recognition import Recognition
        self.recognition=Recognition(self)
        self.recognition.result.connect(self.recognition_result)
        self.recognition.message.connect(self.recognition_message)
        self.recognition_generation=0; self.manual_request=None; self.last_inferred_frame=-1
        self.last_inference=0; self.result_until=0; self.inference_roi=None
        self.setWindowTitle(f'pikkāBPE / операторская станция {__version__}')
        self.logo_path=Path(__file__).parent/'assets'/'logo.svg'
        self.setWindowIcon(QIcon(str(self.logo_path)))
        self.resize(1400, 900)
        base = QWidget(); base.setObjectName('workspace'); self.setCentralWidget(base); shell=QHBoxLayout(base); shell.setContentsMargins(16,16,16,16); shell.setSpacing(20)
        sidebar=QWidget(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(196); side=QVBoxLayout(sidebar); side.setContentsMargins(14,20,14,18); side.setSpacing(8); shell.addWidget(sidebar)
        logo=QLabel(); logo.setPixmap(QIcon(str(self.logo_path)).pixmap(52,52)); side.addWidget(logo)
        brand=QLabel('pikkāBPE'); brand.setObjectName('brand'); side.addWidget(brand)
        subtitle=QLabel('WAREHOUSE VISION'); subtitle.setObjectName('muted'); side.addWidget(subtitle); side.addSpacing(28)
        self.nav_buttons={}
        for index,title in [(5,'Обзор склада'),(0,'Камера'),(1,'События и остатки'),(4,'Товары и команда'),(2,'Обучение'),(3,'Настройки')]:
            button=self.button(title,lambda i=index:self.tabs.setCurrentIndex(i)); button.setObjectName('nav'); button.setCheckable(True); side.addWidget(button); self.nav_buttons[index]=button
        side.addStretch(); side.addWidget(QLabel('Одна зона · 7 стеллажей'))
        self.theme_combo=QComboBox(); self.theme_combo.addItem('Тёмная тема','dark'); self.theme_combo.addItem('Светлая тема','light'); side.addWidget(self.theme_combo)
        side.addWidget(QLabel('Версия '+__version__))
        content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(0,0,0,0); layout.setSpacing(16); shell.addWidget(content,1)
        header=QHBoxLayout(); layout.addLayout(header)
        self.page_title=QLabel('Обзор склада'); self.page_title.setObjectName('pageTitle'); header.addWidget(self.page_title); header.addStretch()
        header.addWidget(QLabel('Оператор'))
        self.operator=QLineEdit(self.preferences.get('operator','')); self.operator.setPlaceholderText('Ваше имя'); self.operator.setMaximumWidth(220); header.addWidget(self.operator)
        self.operator.editingFinished.connect(self.save_preferences)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.build_camera(); self.build_inventory(); self.build_training(); self.build_updates(); self.build_catalogs(); self.build_dashboard()
        for index in range(self.tabs.count()):
            page=self.tabs.widget(index); title=self.tabs.tabText(index); self.tabs.removeTab(index)
            scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page); self.tabs.insertTab(index,scroll,title)
        self.tabs.tabBar().hide(); self.tabs.currentChanged.connect(self.navigate)
        self.status = QLabel('Готово к работе'); self.status.setObjectName('muted'); layout.addWidget(self.status)
        self.theme_combo.setCurrentIndex(max(0,self.theme_combo.findData(self.preferences.get('theme','dark'))))
        self.theme_combo.currentIndexChanged.connect(self.apply_theme); self.apply_theme()
        self.tabs.setCurrentIndex(5); self.navigate(5)
        self.refresh()
        self.timer = QTimer(self); self.timer.timeout.connect(self.send_target); self.timer.start(100)
        self.inference_timer=QTimer(self); self.inference_timer.timeout.connect(self.pump_recognition); self.inference_timer.start(200)

    def button(self, text, fn, primary=False):
        b=QPushButton(text); b.clicked.connect(lambda: self.guard(fn))
        if primary: b.setObjectName('primary')
        return b

    def save_preferences(self):
        self.preferences.update(operator=self.operator.text(),theme=self.theme_combo.currentData())
        (self.root/'preferences.json').write_text(json.dumps(self.preferences,ensure_ascii=False),encoding='utf-8')

    def apply_theme(self):
        self.setStyleSheet(stylesheet(self.theme_combo.currentData())); self.save_preferences()

    def navigate(self,index):
        for i,button in self.nav_buttons.items(): button.setChecked(i==index)
        self.page_title.setText(self.nav_buttons[index].text())

    def card(self,title,parent):
        frame=QFrame(); frame.setObjectName('card'); box=QVBoxLayout(frame); box.setContentsMargins(20,18,20,18); box.setSpacing(12)
        if title:
            label=QLabel(title); label.setObjectName('sectionTitle'); label.setWordWrap(True); box.addWidget(label)
        parent.addWidget(frame)
        return box

    def build_dashboard(self):
        page=QWidget(); self.tabs.addTab(page,'Обзор'); box=QVBoxLayout(page); box.setSpacing(18)
        intro=QLabel('Всё, что нужно для работы со складом, — на одном экране.'); intro.setObjectName('muted'); box.addWidget(intro)
        metrics=QHBoxLayout(); metrics.setSpacing(14); box.addLayout(metrics); self.metric_labels={}
        for key,title in [('products','Товаров в каталоге'),('pending','Ждут проверки'),('stock','Единиц на складе'),('photos','Фото для обучения')]:
            card=self.card(title,metrics); value=QLabel('0'); value.setObjectName('statValue'); card.addWidget(value); self.metric_labels[key]=value
        row=QHBoxLayout(); row.setSpacing(18); box.addLayout(row)
        quick=self.card('Начать работу',row)
        for title,index in [('Открыть камеру',0),('Проверить события',1),('Добавить товар или сотрудника',4),('Добавить фото и обучить',2)]: quick.addWidget(self.button(title,lambda i=index:self.tabs.setCurrentIndex(i),index==0))
        health=self.card('Готовность системы',row)
        self.dashboard_health=QLabel(''); self.dashboard_health.setWordWrap(True); health.addWidget(self.dashboard_health); health.addStretch()
        health.addWidget(self.button('Обновить обзор',self.refresh))
        latest=self.card('Последние события',box)
        self.recent_events=QTableWidget(); latest.addWidget(self.recent_events)
        empty=QLabel('Начните с каталога, затем добавьте поступление и подтвердите размещение на складе.'); empty.setWordWrap(True); empty.setObjectName('muted'); box.addWidget(empty)

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
        self.live_recognition=QCheckBox('Распознавать предмет на видео'); left.addWidget(self.live_recognition)
        self.live_recognition.toggled.connect(lambda checked:self.guard(lambda:self.toggle_recognition(checked)))
        options=QHBoxLayout(); left.addLayout(options)
        options.addWidget(QLabel('Порог оценки модели'))
        self.recognition_threshold=QDoubleSpinBox(); self.recognition_threshold.setRange(.0,1.0); self.recognition_threshold.setSingleStep(.05); self.recognition_threshold.setValue(.7); options.addWidget(self.recognition_threshold)
        options.addWidget(self.button('Весь кадр',lambda:setattr(self.video,'roi',None)))
        self.recognition_note=QLabel('Выделите предмет рамкой. Без рамки оценивается весь кадр; это не поиск нескольких объектов.'); self.recognition_note.setWordWrap(True); left.addWidget(self.recognition_note)
        panel=self.card('',row); form=QFormLayout(); panel.addLayout(form)
        panel.insertWidget(0,QLabel('НОВОЕ СОБЫТИЕ'))
        self.barcode=QLineEdit(); self.barcode.setPlaceholderText('Штрихкод со сканера'); form.addRow('Товар',self.barcode)
        self.product_picker=QComboBox(); form.addRow('Из каталога',self.product_picker)
        self.product_picker.activated.connect(self.choose_product)
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
        toggle=QCheckBox('Управление подвесом'); panel.addWidget(toggle)
        hardware=QWidget(); hw=QVBoxLayout(hardware); hw.setContentsMargins(0,0,0,0); panel.addWidget(hardware); hardware.hide(); toggle.toggled.connect(hardware.setVisible)
        self.com=QLineEdit(); self.com.setPlaceholderText('COM3'); hw.addWidget(self.com)
        hw.addWidget(self.button('Подключить контроллер',lambda:self.link.open(self.com.text())))
        self.pan=QDoubleSpinBox(); self.pan.setRange(-60,60); self.pan.setSuffix('°'); form2=QFormLayout(); hw.addLayout(form2); form2.addRow('Поворот',self.pan)
        self.tilt=QDoubleSpinBox(); self.tilt.setRange(-45,45); self.tilt.setSuffix('°'); form2.addRow('Наклон',self.tilt)
        self.pan.valueChanged.connect(self.motion.camera_moved); self.tilt.valueChanged.connect(self.motion.camera_moved)
        self.follow=QCheckBox('Сопровождать движение'); hw.addWidget(self.follow)
        hw.addWidget(self.button('Остановить сопровождение',lambda:self.follow.setChecked(False)))
        self.link_state=QLabel('Контроллер не подключён'); panel.addWidget(self.link_state)
        panel.addStretch()

    def build_inventory(self):
        page=QWidget(); self.tabs.addTab(page,'События и остатки'); box=QVBoxLayout(page)
        buttons=QHBoxLayout(); box.addLayout(buttons)
        for title, fn in [('Подтвердить',lambda:self.review(True)),('Отклонить',lambda:self.review(False)),('Открыть кадр',self.show_evidence),('Новое поступление',self.add_receipt)]: buttons.addWidget(self.button(title,fn,title=='Подтвердить'))
        tools=QHBoxLayout(); box.addLayout(tools)
        self.event_search=QLineEdit(); self.event_search.setPlaceholderText('Поиск по товару, сотруднику или месту'); self.event_search.textChanged.connect(self.filter_events); tools.addWidget(self.event_search)
        for title, fn in [('Новое место',lambda:self.add_catalog('locations')),('Экспорт CSV',self.export),('Обновить',self.refresh)]: tools.addWidget(self.button(title,fn))
        self.events=QTableWidget(); self.events.setSelectionBehavior(QTableWidget.SelectRows); box.addWidget(self.events,3)
        box.addWidget(self.button('Удалить выбранное событие',self.delete_event))
        box.addWidget(QLabel('ПОДТВЕРЖДЁННЫЕ ОСТАТКИ / ОЖИДАЕМЫЕ ПОСТУПЛЕНИЯ'))
        lower=QHBoxLayout(); box.addLayout(lower,2)
        self.stock=QTableWidget(); lower.addWidget(self.stock)
        self.receipts=QTableWidget(); lower.addWidget(self.receipts)

    def build_training(self):
        page=QWidget(); self.tabs.addTab(page,'Обучение'); box=QVBoxLayout(page)
        note=QLabel('Научите камеру узнавать ваши товары. Добавляйте крупные снимки одного предмета с разных ракурсов.'); note.setWordWrap(True); note.setObjectName('muted'); box.addWidget(note)
        step=self.card('01  ·  Выберите товар и добавьте фотографии',box)
        form=QFormLayout(); step.addLayout(form)
        self.training_product=QComboBox(); form.addRow('Товар на фотографиях',self.training_product)
        photos=QHBoxLayout(); step.addLayout(photos)
        photos.addWidget(self.button('Добавить фотографии товара',self.add_photos,True))
        photos.addWidget(self.button('Новая съёмка',lambda:self.session.setText(time.strftime('%Y-%m-%d-%H%M%S'))))
        self.photo_summary=QLabel(''); self.photo_summary.setWordWrap(True); step.addWidget(self.photo_summary)
        second=self.card('02  ·  Проверьте данные и запустите обучение',box)
        self.training_hint=QLabel(''); self.training_hint.setWordWrap(True); second.addWidget(self.training_hint)
        self.session=QLineEdit(time.strftime('%Y-%m-%d')+'-home-01'); form.addRow('Сессия съёмки',self.session)
        self.source=QLineEdit('Собственная съёмка'); form.addRow('Источник / права',self.source)
        advanced=QWidget(); advanced_form=QFormLayout(advanced); advanced_form.setContentsMargins(0,0,0,0)
        show_advanced=QCheckBox('Параметры обучения'); second.addWidget(show_advanced); second.addWidget(advanced); advanced.hide(); show_advanced.toggled.connect(advanced.setVisible)
        self.epochs=QSpinBox(); self.epochs.setRange(1,100); self.epochs.setValue(10); advanced_form.addRow('Проходов по данным',self.epochs)
        local_python=Path('D:/pikkaBPE/.venv/Scripts/python.exe')
        self.train_python=QLineEdit(str(Path(sys.executable)) if not getattr(sys,'frozen',False) else (str(local_python) if local_python.exists() else '')); advanced_form.addRow('Python для NVIDIA',self.train_python)
        crop=QHBoxLayout(); step.addLayout(crop); crop.addWidget(self.button('Открыть фото для выделения',self.import_image)); crop.addWidget(self.button('Сохранить выделенный пример',self.save_label))
        row=QHBoxLayout(); second.addLayout(row)
        row.addWidget(self.button('Обучить на NVIDIA',self.train,True))
        row.addWidget(self.button('Остановить обучение',self.stop_training))
        third=self.card('03  ·  Проверьте и включите модель',box)
        self.models_note=QLabel(''); self.models_note.setWordWrap(True); self.models_note.setObjectName('muted'); third.addWidget(self.models_note)
        row=QHBoxLayout(); third.addLayout(row)
        row.addWidget(self.button('Активировать модель',self.promote))
        row.addWidget(self.button('Распознать выделенный предмет',self.predict))
        row.addWidget(self.button('Папка моделей',lambda:os.startfile(self.root/'models')))
        self.train_log=QTextEdit(); self.train_log.setReadOnly(True); box.addWidget(self.train_log)

    def build_catalogs(self):
        page=QWidget(); self.tabs.addTab(page,'Сотрудники и товары'); box=QVBoxLayout(page)
        box.addWidget(QLabel('СОТРУДНИКИ — добавьте имя или выберите строку для изменения'))
        row=QHBoxLayout(); box.addLayout(row)
        self.employee_name=QLineEdit(); self.employee_name.setPlaceholderText('ФИО сотрудника'); row.addWidget(self.employee_name)
        row.addWidget(self.button('Добавить сотрудника',self.add_employee,True))
        row.addWidget(self.button('Сохранить имя выбранного',self.rename_employee))
        self.employees_table=QTableWidget(); self.employees_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.employees_table.itemSelectionChanged.connect(self.select_employee); box.addWidget(self.employees_table)
        box.addWidget(QLabel('ТОВАРЫ — для нового предмета без кода штрихкод создаётся автоматически'))
        self.catalog_search=QLineEdit(); self.catalog_search.setPlaceholderText('Поиск товара по названию или штрихкоду'); self.catalog_search.textChanged.connect(self.filter_catalog); box.addWidget(self.catalog_search)
        box.addWidget(self.button('Добавить товары из каталога ИНТЭР',self.import_energy_catalog))
        row=QHBoxLayout(); box.addLayout(row)
        self.new_product_name=QLineEdit(); self.new_product_name.setPlaceholderText('Название нового предмета'); row.addWidget(self.new_product_name)
        self.new_product_code=QLineEdit(); self.new_product_code.setPlaceholderText('Существующий штрихкод (необязательно)'); row.addWidget(self.new_product_code)
        row.addWidget(self.button('Добавить товар и штрихкод',self.add_product,True))
        row.addWidget(self.button('Открыть штрихкод выбранного',self.open_barcode))
        self.products_table=QTableWidget(); self.products_table.setSelectionBehavior(QTableWidget.SelectRows); box.addWidget(self.products_table)

    def filter_catalog(self):
        self.filter_table(self.products_table,self.catalog_search.text())

    def import_energy_catalog(self):
        from .catalog import import_catalog
        self.backup(silent=True)
        count=import_catalog(self.db); self.refresh(); self.status.setText(f'Добавлено товаров из каталога ИНТЭР: {count}. Остатки не менялись.')

    def filter_events(self):
        self.filter_table(self.events,self.event_search.text())

    @staticmethod
    def filter_table(table,text):
        text=text.strip().casefold()
        for row in range(table.rowCount()):
            table.setRowHidden(row,bool(text) and not any(text in table.item(row,c).text().casefold() for c in range(table.columnCount()) if table.item(row,c)))

    def add_employee(self):
        key='EMP-'+uuid.uuid4().hex[:12]
        self.db.catalog('employees',key,self.employee_name.text())
        self.employee_name.clear(); self.refresh()
        self.employee.setCurrentIndex(self.employee.findData(key))

    def select_employee(self):
        row=self.employees_table.currentRow()
        if row>=0 and self.employees_table.item(row,1): self.employee_name.setText(self.employees_table.item(row,1).text())

    def rename_employee(self):
        row=self.employees_table.currentRow()
        if row<0: raise ValueError('Выберите сотрудника в таблице')
        self.db.catalog('employees',self.employees_table.item(row,0).text(),self.employee_name.text()); self.refresh()

    def add_product(self):
        from .labels import new_code, barcode_label
        name=self.new_product_name.text().strip()
        if not name: raise ValueError('Введите название предмета')
        code=self.new_product_code.text().strip() or new_code()
        if self.db.rows('SELECT 1 FROM products WHERE barcode=?',(code,)): raise ValueError('Товар с таким кодом уже существует')
        path=barcode_label(self.root,code)
        self.db.catalog('products',code,name)
        self.barcode.setText(code); self.product_name.setText(name)
        self.new_product_name.clear(); self.new_product_code.clear(); self.refresh()
        self.training_product.setCurrentIndex(self.training_product.findData(code))
        self.status.setText(f'Товар добавлен. Штрихкод для печати: {path}')

    def open_barcode(self):
        from .labels import barcode_label
        row=self.products_table.currentRow()
        if row<0: raise ValueError('Выберите товар в таблице')
        os.startfile(barcode_label(self.root,self.products_table.item(row,0).text()))

    def add_photos(self):
        from .labels import import_photos
        code=self.training_product.currentData()
        if not code: raise ValueError('Добавьте и выберите товар')
        paths,_=QFileDialog.getOpenFileNames(self,'Выберите фотографии одного товара','','Изображения (*.jpg *.jpeg *.png *.bmp *.webp)')
        if not paths: return
        added,errors=import_photos(self.db,self.root,paths,code,self.session.text(),self.source.text())
        self.train_log.append(f'Добавлено фотографий: {added}. Товар: {self.training_product.currentText()}')
        for error in errors: self.train_log.append(error)
        self.refresh()

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
        self.live_recognition.setChecked(False)
        self.stop_recognition()
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
            from .labels import barcode_label
            try:
                path=barcode_label(self.root,code); self.status.setText(f'Штрихкод создан: {path}')
            except ValueError as exc:
                self.status.setText(f'Товар сохранён. {exc}')
            self.refresh()
        self.product_name.setText(rows[0]['name'])

    def choose_product(self):
        code=self.product_picker.currentData()
        if code: self.barcode.setText(code); self.lookup()

    def add_catalog(self,table):
        code,ok=QInputDialog.getText(self,'Справочник','Код:')
        if not ok: return
        name,ok=QInputDialog.getText(self,'Справочник','Имя / название:')
        if ok: self.db.catalog(table,code,name); self.refresh()

    def add_receipt(self):
        products=self.db.rows('SELECT * FROM products ORDER BY name')
        if not products: raise ValueError('Сначала добавьте товар в разделе «Товары и команда»')
        options=[f"{p['name']} · {p['barcode']}" for p in products]
        chosen,ok=QInputDialog.getItem(self,'Новое поступление','Выберите товар:',options,0,False)
        if not ok: return
        code=products[options.index(chosen)]['barcode']
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

    def delete_event(self):
        row=self.events.currentRow()
        if row<0: raise ValueError('Выберите событие')
        if QMessageBox.question(self,'Удаление события','Удалить событие? Его влияние на остаток и поступление будет отменено. Запись об удалении останется в журнале.')!=QMessageBox.Yes: return
        self.db.delete_event(self.events.item(row,0).text(),self.operator.text()); self.refresh()

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
            for c,(key,_) in enumerate(columns):
                value=row.get(key)
                if key=='kind': value={'take':'Взятие','return':'Возврат','place':'Размещение'}.get(value,value)
                if key=='status': value={'pending':'На проверке','confirmed':'Подтверждено','rejected':'Отклонено'}.get(value,value)
                table.setItem(r,c,QTableWidgetItem('' if value is None else str(value)))
        table.resizeColumnsToContents()
        table.setAlternatingRowColors(True); table.verticalHeader().hide(); table.verticalHeader().setDefaultSectionSize(42)
        table.horizontalHeader().setStretchLastSection(True)

    def refresh(self):
        self.fill(self.events,self.db.rows('SELECT e.*,p.name,emp.name AS employee_name FROM events e JOIN products p ON p.barcode=e.barcode LEFT JOIN employees emp ON emp.id=e.employee WHERE e.deleted IS NULL ORDER BY e.created DESC LIMIT 500'), [('id','ID'),('created','UTC'),('kind','Операция'),('name','Товар'),('quantity','Кол-во'),('location','Место'),('employee_name','Сотрудник'),('status','Статус')])
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
        self.employees_table.blockSignals(True)
        self.fill(self.employees_table,self.db.rows('SELECT * FROM employees ORDER BY name'),[('id','Код'),('name','Имя')])
        self.employees_table.blockSignals(False)
        products=self.db.rows('SELECT * FROM products ORDER BY name')
        self.fill(self.products_table,products,[('barcode','Штрихкод'),('name','Товар')])
        old=self.training_product.currentData(); self.training_product.clear()
        for p in products: self.training_product.addItem(p['name'],p['barcode'])
        index=self.training_product.findData(old)
        if index>=0: self.training_product.setCurrentIndex(index)
        selected=self.product_picker.currentData(); self.product_picker.clear(); self.product_picker.addItem('Выберите товар',None)
        for p in products: self.product_picker.addItem(p['name'],p['barcode'])
        index=self.product_picker.findData(selected)
        if index>=0: self.product_picker.setCurrentIndex(index)
        summary=self.db.rows('SELECT p.name,COUNT(*) AS n,COUNT(DISTINCT l.session) AS sessions FROM labels l JOIN products p ON p.barcode=l.barcode GROUP BY l.barcode ORDER BY p.name')
        self.photo_summary.setText('Примеры: '+('; '.join(f"{r['name']}: {r['n']} фото, съёмок {r['sessions']}" for r in summary) or 'пока нет фотографий'))
        from .train import training_guidance
        self.training_hint.setText(training_guidance(self.db.rows('SELECT * FROM labels')) or 'Данные собраны. Перед запуском будут проверены разделение съёмок и дубликаты.')
        count=len(list((self.root/'models').glob('*.pt')))
        self.models_note.setText(f'Папка моделей: {self.root / "models"}\nСохранено моделей: {count}. Файл .pt появляется только после успешного обучения; импорт фото сохраняет примеры, а не модель.')
        values={'products':len(products),'pending':self.db.rows("SELECT COUNT(*) AS n FROM events WHERE deleted IS NULL AND status='pending'")[0]['n'],'stock':self.db.rows('SELECT COALESCE(SUM(quantity),0) AS n FROM stock')[0]['n'],'photos':sum(r['n'] for r in summary)}
        for key,value in values.items(): self.metric_labels[key].setText(str(value))
        active=(self.root/'models'/'active.json').exists()
        self.dashboard_health.setText(f'Модель: {"активирована" if active else "нужно обучить и активировать"}\nСотрудников: {self.employee.count()-1}\nФотографии: {values["photos"]}\n\nУчёт изменяется после подтверждения оператора.\nИнтернет-фото подходят для первого знакомства модели; проверяйте её на реальном складе.')
        self.fill(self.recent_events,self.db.rows('SELECT e.kind,e.status,e.quantity,p.name FROM events e JOIN products p ON p.barcode=e.barcode WHERE e.deleted IS NULL ORDER BY e.created DESC LIMIT 8'),[('name','Товар'),('kind','Действие'),('quantity','Количество'),('status','Статус')])
        self.filter_catalog(); self.filter_events()

    def save_label(self):
        code=self.barcode.text().strip()
        if not self.db.rows('SELECT 1 FROM products WHERE barcode=?',(code,)): raise ValueError('Сначала добавьте товар')
        path=self.evidence(crop=True); self.db.label(path,code,self.session.text(),self.source.text())
        self.train_log.append(f'Пример сохранён: {code}; {self.session.text()}')
        self.refresh()

    def import_image(self):
        path,_=QFileDialog.getOpenFileName(self,'Изображение из разрешённого набора','','Изображения (*.jpg *.png *.jpeg)')
        if path:
            if self.training_product.currentData():
                self.barcode.setText(self.training_product.currentData()); self.lookup()
            import numpy as np
            frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
            if frame is None: raise ValueError('Изображение не прочитано')
            self.stop_capture(); self.video.frame=frame; self.video.roi=None; self.video.update(); self.tabs.setCurrentIndex(0)

    def train(self):
        if self.training and self.training.state()!=QProcess.NotRunning: raise ValueError('Обучение уже запущено')
        from .train import split_sessions, training_guidance
        rows=self.db.rows('SELECT * FROM labels')
        guidance=training_guidance(rows)
        if guidance:
            self.train_log.append(guidance)
            raise ValueError(guidance)
        split_sessions(rows)
        self.training=QProcess(self); self.training.setProcessChannelMode(QProcess.MergedChannels)
        environment=QProcessEnvironment.systemEnvironment(); environment.insert('PYTHONIOENCODING','utf-8')
        self.training.setProcessEnvironment(environment)
        self.training.readyReadStandardOutput.connect(lambda:self.train_log.append(bytes(self.training.readAllStandardOutput()).decode('utf-8',errors='replace')))
        self.training.errorOccurred.connect(lambda e:self.train_log.append('Ошибка запуска: '+self.training.errorString()))
        self.training.finished.connect(self.training_finished)
        self.training.start(self.train_python.text(),['-u','-m','pikkabpe.train','--data',str(self.root),'--epochs',str(self.epochs.value())])

    def training_finished(self,code):
        self.train_log.append(f'Модель сохранена в {self.root / "models"}. Проверьте отчёт и активируйте модель.' if code==0 else f'Обучение не завершено (код {code}). Модель этого запуска не создана. Причина указана выше в журнале.')
        self.refresh()

    def stop_training(self):
        if self.training: self.training.terminate()

    def promote(self):
        path,_=QFileDialog.getOpenFileName(self,'Проверенная модель',str(self.root/'models'),'Модель (*.pt)')
        if not path: return
        metrics=Path(path).with_suffix('.json')
        if not metrics.exists(): raise ValueError('Нет отчёта проверки рядом с моделью')
        report=json.loads(metrics.read_text(encoding='utf-8'))
        accuracy=report.get('accuracy')
        summary=(f'Модель: {Path(path).name}\nТоваров: {len(report.get("classes",[]))}\n'
                 f'Учебных фото: {report.get("train_samples",0)}\nПроверочных фото: {report.get("validation_samples",0)}\n'
                 f'Результат проверки: {format(accuracy,".1%") if accuracy is not None else "независимая проверка не проводилась"}\n')
        if report.get('kind')=='catalog_pilot_unvalidated': summary+='\nКаталожный эксперимент: по одному интернет-фото на товар. Нужна проверка на ваших предметах.\n'
        if QMessageBox.question(self,'Включить модель?',summary+'\nИспользовать для подсказок оператору?')!=QMessageBox.Yes: return
        self.live_recognition.setChecked(False); self.stop_recognition()
        (self.root/'models'/'active.json').write_text(json.dumps({'path':path,'report':report},ensure_ascii=False),encoding='utf-8')
        self.predictor=None; self.train_log.append('Модель активирована для подсказок; автоматический учёт выключен.')

    def predict(self):
        if self.video.frame is None or not self.video.roi: raise ValueError('Откройте фото или видео и выделите предмет рамкой')
        self.ensure_recognition()
        self.manual_request=(self.video.frame.copy(),self.video.roi)
        self.train_log.append('Распознаём выделенный предмет…')

    def ensure_recognition(self):
        if self.recognition.process is not None: return
        path=self.root/'models'/'active.json'
        if not path.exists(): raise ValueError('Сначала обучите и активируйте модель на вкладке «Обучение»')
        active=json.loads(path.read_text(encoding='utf-8'))
        self.recognition.start(self.train_python.text(),active['path'])

    def toggle_recognition(self,checked):
        if not checked: self.stop_recognition(); return
        try: self.ensure_recognition()
        except Exception:
            self.live_recognition.blockSignals(True); self.live_recognition.setChecked(False); self.live_recognition.blockSignals(False)
            raise

    def stop_recognition(self):
        self.recognition_generation+=1; self.manual_request=None; self.recognition.stop()
        self.video.recognition_text=''; self.video.recognition_roi=None; self.video.update()
        self.last_inferred_frame=-1; self.inference_roi=None

    def recognition_message(self,text):
        self.recognition_note.setText(text)
        if self.recognition.process is None:
            self.live_recognition.blockSignals(True); self.live_recognition.setChecked(False); self.live_recognition.blockSignals(False)
            self.manual_request=None; self.video.recognition_text=''; self.video.update(); self.train_log.append(text)

    def pump_recognition(self):
        now=time.monotonic()
        roi=self.video.roi or (0,0,1,1)
        if roi!=self.inference_roi:
            self.inference_roi=roi; self.recognition_generation+=1
            self.video.recognition_text=''; self.video.update(); self.last_inferred_frame=-1
        if self.result_until and now>self.result_until:
            self.video.recognition_text=''; self.result_until=0; self.video.update()
        if not self.recognition.ready or self.recognition.pending: return
        if self.manual_request:
            frame,area=self.manual_request
            if self.recognition.submit(frame,area,self.recognition_generation,manual=True): self.manual_request=None
        elif self.live_recognition.isChecked() and self.video.frame is not None and self.frame_count!=self.last_inferred_frame and now-self.last_inference>=.4:
            if self.recognition.submit(self.video.frame,roi,self.recognition_generation):
                self.last_inferred_frame=self.frame_count; self.last_inference=now

    def recognition_result(self,result):
        if result['generation']!=self.recognition_generation: return
        if result['roi']!=(self.video.roi or (0,0,1,1)): return
        if result.get('error'):
            self.recognition_note.setText('Ошибка распознавания: '+result['error']); return
        if not result['manual'] and time.monotonic()-result['submitted']>2: return
        from .recognition import describe
        text=describe(self.db,result['barcode'],result['score'],self.recognition_threshold.value())
        self.video.recognition_text=text; self.video.recognition_roi=result['roi']; self.video.update()
        self.result_until=time.monotonic()+(10 if result['manual'] else 2)
        self.recognition_note.setText(text+' · подсказка модели, требуется проверка')
        if result['manual']: self.train_log.append('Подсказка: '+text+'. Требуется проверка оператором.')

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
    app=QApplication(sys.argv); app.setStyle('Fusion')
    window=Window(); window.show()
    if '--smoke-test' in sys.argv:
        QTimer.singleShot(800,lambda:window.grab().save(str(window.root/'client-preview.png')))
        QTimer.singleShot(1200,window.close)
    sys.exit(app.exec())


if __name__=='__main__': main()
