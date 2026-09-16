import json
import time
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pytest
from pikkabpe.yolo_data import save_annotation,export_dataset,validate_boxes


def test_yolo_one_class_session_split_and_box_coordinates(tmp_path):
    box={'barcode':'PB1','xywh':[.1,.2,.4,.6]}
    save_annotation(tmp_path,np.zeros((30,40,3),dtype=np.uint8),[box],'session-a','Own')
    save_annotation(tmp_path,np.full((30,40,3),100,dtype=np.uint8),[box],'session-b','Own')
    yaml,train,val,classes=export_dataset(tmp_path)
    assert len(train)==len(val)==1 and classes==['PB1']
    config=json.loads(yaml.read_text()); assert config['names']==['PB1']
    label=next((yaml.parent/'labels'/'train').glob('*.txt')).read_text().split()
    assert list(map(float,label))==pytest.approx([0,.3,.5,.4,.6])


def test_annotations_reject_duplicates_across_sessions_and_invalid_boxes(tmp_path):
    frame=np.zeros((30,40,3),dtype=np.uint8)
    box={'barcode':'PB1','xywh':[0,0,1,1]}
    save_annotation(tmp_path,frame,[box],'a','Own')
    with pytest.raises(ValueError,match='другой'): save_annotation(tmp_path,frame,[box],'b','Own')
    with pytest.raises(ValueError): validate_boxes([{'barcode':'x','xywh':[.9,0,.2,1]}])
    with pytest.raises(ValueError): export_dataset(tmp_path)


def test_multiple_yolo_boxes_show_names_and_clear_on_empty_result(tmp_path,monkeypatch):
    monkeypatch.setenv('PIKKABPE_DATA',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from pikkabpe.app import Window
    app=QApplication.instance() or QApplication([])
    w=Window();w.timer.stop();w.inference_timer.stop()
    w.db.catalog('products','PB1','Батарейка');w.recognition_threshold.setValue(.35)
    result={'id':1,'generation':w.recognition_generation,'roi':(0,0,1,1),'manual':True,'submitted':time.monotonic(),
            'detections':[{'barcode':'PB1','score':.8,'xyxy':[.1,.1,.3,.3]},{'barcode':'PB1','score':.7,'xyxy':[.6,.6,.8,.9]}]}
    w.recognition_result(result)
    assert len(w.video.detections)==2 and 'Батарейка' in w.video.detections[0]['text']
    result['detections']=[];w.recognition_result(result)
    assert not w.video.detections and '0' in w.video.recognition_text
    w.close();app.processEvents()


def test_yolo_annotation_ui_preserves_full_frame(tmp_path,monkeypatch):
    monkeypatch.setenv('PIKKABPE_DATA',str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from pikkabpe.app import Window
    app=QApplication.instance() or QApplication([])
    w=Window();w.db.catalog('products','PB1','Батарейка');w.refresh()
    w.video.frame=np.zeros((300,400,3),dtype=np.uint8);w.video.roi=(.1,.1,.3,.3)
    w.add_yolo_box();w.video.roi=(.6,.5,.3,.4);w.add_yolo_box();w.save_yolo_frame()
    records=json.loads((tmp_path/'detection'/'annotations.json').read_text(encoding='utf-8'))
    assert len(records)==1 and len(records[0]['boxes'])==2
    from PIL import Image
    assert Image.open(records[0]['image']).size==(400,300)
    w.close();app.processEvents()
