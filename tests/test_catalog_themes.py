import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pikkabpe.store import Store
from pikkabpe.catalog import import_catalog


def test_catalog_repeat_keeps_user_names_and_stock(tmp_path):
    store=Store(tmp_path/'db.sqlite')
    assert import_catalog(store)==26
    product=store.rows('SELECT * FROM products')[0]
    store.catalog('products',product['barcode'],'My local name')
    assert import_catalog(store)==0
    assert store.rows('SELECT name FROM products WHERE barcode=?',(product['barcode'],))[0]['name']=='My local name'
    assert not store.rows('SELECT * FROM stock')


def test_theme_preference_navigation_and_search(tmp_path,monkeypatch):
    monkeypatch.setenv('PIKKABPE_DATA',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from pikkabpe.app import Window
    app=QApplication.instance() or QApplication([])
    w=Window(); import_catalog(w.db); w.refresh()
    w.theme_combo.setCurrentIndex(w.theme_combo.findData('light'))
    w.operator.setText('Operator'); w.save_preferences()
    w.tabs.setCurrentIndex(4)
    assert w.nav_buttons[4].isChecked()
    w.catalog_search.setText('ER9V')
    assert sum(not w.products_table.isRowHidden(i) for i in range(w.products_table.rowCount()))==1
    assert w.metric_labels['products'].text()=='26'
    w.close(); app.processEvents()
    w=Window()
    assert w.theme_combo.currentData()=='light' and w.operator.text()=='Operator'
    w.close(); app.processEvents()
