import csv
import json
import sqlite3
import pytest
from PIL import Image
from pikkabpe.store import Store
from pikkabpe.labels import barcode_label, import_photos


def setup_stock(tmp_path):
    db=Store(tmp_path/'warehouse.db')
    db.catalog('products','PB001','Battery')
    rid=db.receipt('PB001',10)
    eid=db.propose('place','PB001',10,'R1',receipt=rid)
    db.review(eid,'Operator',True)
    return db,rid,eid


def test_delete_reverses_stock_receipt_export_and_retains_audit(tmp_path):
    db,rid,eid=setup_stock(tmp_path)
    take=db.propose('take','PB001',3,'R1'); db.review(take,'Operator',True)
    with pytest.raises(ValueError,match='отрицательный'):
        db.delete_event(eid,'Operator')
    assert db.rows('SELECT placed FROM receipts')[0]['placed']==10
    db.delete_event(take,'Operator')
    assert db.rows('SELECT quantity FROM stock')[0]['quantity']==10
    db.delete_event(eid,'Operator')
    assert db.rows('SELECT quantity FROM stock')[0]['quantity']==0
    assert db.rows('SELECT placed FROM receipts')[0]['placed']==0
    with pytest.raises(ValueError): db.delete_event(eid,'Operator')
    db.export(tmp_path/'events.csv')
    with (tmp_path/'events.csv').open(encoding='utf-8-sig') as stream: assert list(csv.DictReader(stream))==[]
    log=db.rows("SELECT payload FROM audit WHERE action='event_deleted'")
    assert json.loads(log[-1]['payload'])['event']['id']==eid
    pending=db.propose('return','PB001',2,'R1'); db.delete_event(pending,'Operator')
    with pytest.raises(ValueError): db.review(pending,'Operator',True)
    assert db.rows('SELECT quantity FROM stock')[0]['quantity']==0


def test_legacy_database_migration(tmp_path):
    db,rid,eid=setup_stock(tmp_path)
    with sqlite3.connect(db.path) as conn: conn.execute('ALTER TABLE events DROP COLUMN deleted')
    migrated=Store(db.path)
    assert migrated.rows('SELECT * FROM events')[0]['deleted'] is None
    migrated.delete_event(eid,'Operator')


def test_photos_unicode_paths_bad_file_and_barcode(tmp_path):
    db,_,_=setup_stock(tmp_path)
    photo=tmp_path/'фото.png'; Image.new('RGB',(120,80),'orange').save(photo)
    bad=tmp_path/'bad.jpg'; bad.write_text('broken')
    count,errors=import_photos(db,tmp_path,[photo,bad],'PB001','home-1','Own')
    assert count==1 and len(errors)==1
    row=db.rows('SELECT * FROM labels')[0]
    assert row['session']=='home-1' and row['barcode']=='PB001'
    assert Image.open(row['image']).size==(120,80)
    path=barcode_label(tmp_path,'PB001')
    assert '<svg' in path.read_text() and 'PB001' in path.read_text()
    with pytest.raises(ValueError): barcode_label(tmp_path,'Батарея')


def test_ui_employee_product_and_photo_workflow(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen'); monkeypatch.setenv('PIKKABPE_DATA',str(tmp_path))
    from PySide6.QtWidgets import QApplication, QFileDialog
    from pikkabpe.app import Window
    app=QApplication.instance() or QApplication([])
    window=Window(); window.timer.stop()
    window.employee_name.setText('Иван Петров'); window.add_employee()
    employee=window.employee.currentData()
    window.employees_table.selectRow(0); window.employee_name.setText('Иван Сидоров'); window.rename_employee()
    assert window.db.rows('SELECT * FROM employees')[0]=={'id':employee,'name':'Иван Сидоров'}
    window.new_product_name.setText('Аккумулятор'); window.add_product()
    code=window.training_product.currentData()
    assert code.startswith('PB') and list((tmp_path/'barcodes').glob('*.svg'))
    photo=tmp_path/'sample.jpg'; Image.new('RGB',(100,100),'red').save(photo)
    monkeypatch.setattr(QFileDialog,'getOpenFileNames',lambda *a,**k:([str(photo)],''))
    window.add_photos()
    assert window.db.rows('SELECT barcode FROM labels')[0]['barcode']==code
    window.close(); app.processEvents()
