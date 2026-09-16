import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import time
import numpy as np
from PySide6.QtWidgets import QApplication
from pikkabpe.recognition import Recognition,describe
from pikkabpe.store import Store


def test_product_name_and_uncertain_prediction(tmp_path):
    db=Store(tmp_path/'db.sqlite'); db.catalog('products','PB123','ТХ-Э')
    assert describe(db,'PB123',.9,.7)=='ТХ-Э · 90%'
    assert 'Не уверен' in describe(db,'PB123',.6,.7)
    assert 'PB123' not in describe(db,'PB123',.6,.7)
    assert 'отсутствует' in describe(db,'missing',.99,.7)


def test_one_frame_in_flight_and_fragmented_responses():
    app=QApplication.instance() or QApplication([])
    class Process:
        data=b''
        def write(self,data): self.request=json.loads(data)
        def readAllStandardOutput(self): data=self.data; self.data=b''; return data
    worker=Recognition(); fake=Process(); worker.process=fake; worker.ready=True
    results=[]; worker.result.connect(results.append)
    frame=np.zeros((100,100,3),dtype=np.uint8)
    assert worker.submit(frame,(0,0,1,1),3)
    assert not worker.submit(frame,(0,0,1,1),3)
    reply=json.dumps({'id':fake.request['id'],'barcode':'PB1','score':.8}).encode()+b'\n'
    fake.data=reply[:8]; worker.read(); assert not results
    fake.data=reply[8:]; worker.read()
    assert results[0]['generation']==3 and worker.pending is None
    worker.process=None; worker.watch.stop()


def test_stale_predictions_ignored_and_manual_names(tmp_path,monkeypatch):
    monkeypatch.setenv('PIKKABPE_DATA',str(tmp_path))
    from pikkabpe.app import Window
    app=QApplication.instance() or QApplication([])
    w=Window(); w.timer.stop(); w.inference_timer.stop()
    w.db.catalog('products','PB123','ТХ-Э'); w.video.roi=(.1,.1,.5,.5)
    result={'generation':w.recognition_generation,'roi':w.video.roi,'barcode':'PB123','score':.9,'manual':True,'submitted':time.monotonic()}
    w.recognition_result(result)
    assert 'ТХ-Э' in w.video.recognition_text and 'PB123' not in w.train_log.toPlainText()
    w.stop_recognition(); w.recognition_result(result)
    assert w.video.recognition_text==''
    w.close(); app.processEvents()
