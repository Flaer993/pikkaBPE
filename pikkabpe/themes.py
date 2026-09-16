"""Reference-inspired graphite and porcelain desktop themes."""
def stylesheet(theme='dark'):
    dark=theme=='dark'
    bg,panel,card,text,muted,line,field,selected=(
        ('#131519','#1b1e24','#22262d','#f3f4f6','#a7afb9','#303640','#292e37','#493122') if dark else
        ('#f1f2f5','#ffffff','#ffffff','#20252c','#626c78','#dce1e8','#f4f6f8','#ffeadc'))
    return f'''
QWidget {{font-family:Segoe UI;font-size:13px;color:{text};}}
QMainWindow,QWidget#workspace {{background:{bg};}}
QWidget#sidebar,QFrame#card {{background:{panel};border:1px solid {line};border-radius:18px;}}
QLabel {{background:transparent;border:0;}}
QLabel#brand {{font-size:23px;font-weight:700;}}
QLabel#pageTitle {{font-size:27px;font-weight:600;}}
QLabel#subtitle,QLabel#muted {{color:{muted};}}
QLabel#statValue {{font-size:32px;font-weight:600;color:{text};}}
QLabel#sectionTitle {{font-size:18px;font-weight:600;}}
QPushButton {{background:{field};border:1px solid {line};padding:9px 13px;border-radius:10px;}}
QPushButton:hover {{border-color:#ee894e;background:{selected};}}
QPushButton:disabled {{color:{muted};}}
QPushButton#primary {{background:#f68749;border:1px solid #f68749;color:#181818;font-weight:600;}}
QPushButton#nav {{text-align:left;padding:13px 16px;border:0;background:transparent;color:{muted};}}
QPushButton#nav:checked {{background:{selected};color:{text};border-left:3px solid #f68749;}}
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QTextEdit {{background:{field};border:1px solid {line};padding:7px;border-radius:8px;selection-background-color:#c06531;}}
QComboBox QAbstractItemView {{background:{panel};color:{text};selection-background-color:{selected};}}
QTabWidget::pane {{border:0;background:{bg};}}
QScrollArea {{border:0;background:transparent;}}
QScrollArea>QWidget>QWidget {{background:{bg};}}
QHeaderView::section {{background:{field};color:{muted};padding:10px;border:0;font-weight:600;}}
QTableWidget {{background:{card};alternate-background-color:{field};gridline-color:{line};border:1px solid {line};border-radius:12px;selection-background-color:{selected};selection-color:{text};}}
QTableWidget::item {{padding:7px;}}
QGroupBox {{border:1px solid {line};border-radius:12px;margin-top:18px;padding:12px;background:{panel};}}
QGroupBox::title {{subcontrol-origin:margin;left:12px;color:{muted};}}
QCheckBox {{spacing:8px;}}
QToolTip {{background:{panel};color:{text};border:1px solid {line};padding:6px;}}
QMessageBox,QDialog {{background:{bg};}}
QProgressBar {{background:{field};border:0;border-radius:5px;text-align:center;}}
QProgressBar::chunk {{background:#f68749;border-radius:5px;}}
'''
