import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import cv2
import numpy as np
from PySide6.QtWidgets import QApplication
from pikkabpe.app import Window


def test_operator_inventory_and_crop(tmp_path,monkeypatch):
    monkeypatch.setenv('PIKKABPE_DATA',str(tmp_path))
    app=QApplication.instance() or QApplication([])
    window=Window(); window.timer.stop()
    window.db.catalog('products','TEST-001','Тестовый аккумулятор')
    rid=window.db.receipt('TEST-001',10)
    window.refresh(); window.barcode.setText('TEST-001'); window.operator.setText('Test operator')
    window.video.frame=np.zeros((480,640,3),dtype=np.uint8)
    window.kind.setCurrentIndex(window.kind.findData('place'))
    window.receipt_combo.setCurrentIndex(window.receipt_combo.findData(rid))
    window.quantity.setValue(10); window.propose(); window.events.selectRow(0); window.review(True)
    window.kind.setCurrentIndex(window.kind.findData('take'))
    window.quantity.setValue(2); window.propose(); window.events.selectRow(0); window.review(True)
    window.kind.setCurrentIndex(window.kind.findData('return'))
    window.quantity.setValue(1); window.propose(); window.events.selectRow(0); window.review(True)
    assert window.db.rows('SELECT quantity FROM stock')[0]['quantity']==9
    window.video.roi=(.25,.25,.5,.5); window.save_label()
    label=window.db.rows('SELECT * FROM labels')[0]
    crop=cv2.imdecode(np.fromfile(label['image'],dtype=np.uint8),cv2.IMREAD_COLOR)
    assert crop.shape[:2]==(240,320)
    window.pan.setValue(10); window.tilt.setValue(-10)
    assert window.motion.settled_after>0
    window.close(); app.processEvents()
