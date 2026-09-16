import base64
import json
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import cv2
import numpy as np
import pytest
from PIL import Image

from pikkabpe.barcodes import decode_barcodes
from pikkabpe.warehouse import decode_output


@pytest.mark.parametrize('format_name,text', [
    ('Code128', 'INTER-ER14505-001'), ('EAN13', '5901234123457'),
    ('QRCode', 'INTER:ER14505'), ('DataMatrix', 'INTER:ER34615'),
])
def test_exact_payload_and_coordinates_in_full_frame(format_name, text):
    import zxingcpp
    bitmap = zxingcpp.write_barcode(getattr(zxingcpp.BarcodeFormat, format_name), text, 400, 150)
    patch = Image.fromarray(np.asarray(bitmap)).convert('RGB')
    image = Image.new('RGB', (1800, 1000), 'white')
    image.paste(patch, (700, 300))
    boxes = [{'label': 'barcode', 'xyxy': [700/1800, .3, (700+patch.width)/1800, (300+patch.height)/1000]}]
    decoded = decode_barcodes(image, boxes)
    assert len(decoded) == 1  # Whole-frame and crop reads must not duplicate it.
    assert decoded[0]['text'] == text
    x1, y1, x2, y2 = decoded[0]['xyxy']
    assert 700/1800 <= x1 < x2 <= (700+patch.width)/1800
    assert .3 <= y1 < y2 <= (300+patch.height)/1000


def test_identical_codes_on_two_labels_remain_two_detections():
    import zxingcpp
    patch = Image.fromarray(np.asarray(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.Code128, 'INTER001', 400, 120)))
    image = Image.new('RGB', (1200, 600), 'white')
    image.paste(patch, (50, 50)); image.paste(patch, (650, 350))
    assert len(decode_barcodes(image)) == 2
    assert decode_barcodes(Image.new('RGB', (300, 200), 'white')) == []


def test_letterbox_coordinates_and_class_aware_nms():
    # 1280x720 image becomes 640x360 plus 140px top padding.
    raw = np.array([[320, 320, 200, 100, .9, .1], [320, 320, 200, 100, .8, .1],
                    [320, 320, 200, 100, .1, .85]], dtype=np.float32)
    result = decode_output(raw, ['person', 'safety vest'], (1280, 720), .5, 0, 140, .35)
    assert len(result) == 2
    assert {r['label'] for r in result} == {'person', 'safety vest'}
    assert result[0]['xyxy'] == pytest.approx([440/1280, 260/720, 840/1280, 460/720])


def test_barcode_transport_preserves_source_pixels():
    from PySide6.QtWidgets import QApplication
    from pikkabpe.recognition import Recognition
    app = QApplication.instance() or QApplication([])
    class Process:
        def write(self, data): self.request = json.loads(data)
    worker = Recognition(); worker.process = Process(); worker.ready = True; worker.decode_barcodes = True
    frame = np.random.default_rng(42).integers(0, 256, (900, 1600, 3), dtype=np.uint8)
    assert worker.submit(frame, (0, 0, 1, 1), 1)
    restored = cv2.imdecode(np.frombuffer(base64.b64decode(worker.process.request['image']), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert np.array_equal(restored, frame)
    worker.process = None; worker.watch.stop()


@pytest.fixture
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from pikkabpe.app import Window
    monkeypatch.setenv('PIKKABPE_DATA', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    w = Window(); w.timer.stop(); w.inference_timer.stop()
    yield w
    w.close(); app.processEvents()


def result_for(w, **extra):
    return {'generation': w.recognition_generation, 'roi': (0, 0, 1, 1),
            'manual': True, 'submitted': time.monotonic(), 'detections': [], **extra}


def test_decoded_codes_require_operator_selection_and_never_change_stock(window):
    w = window; w.db.catalog('products', '000123', 'Батарейка')
    w.barcode.setText('KEEP')
    w.recognition_result(result_for(w, barcodes=[{'text': '000123', 'format': 'Code128', 'xyxy': [0, 0, .5, .5]}]))
    assert w.barcode.text() == 'KEEP'
    assert w.decoded_codes.currentData() == '000123'
    w.use_decoded_code()
    assert w.barcode.text() == '000123'  # Leading zeros survive catalog lookup.
    assert w.db.rows('SELECT * FROM events') == []
    assert w.db.rows('SELECT * FROM stock') == []
    w.recognition_result(result_for(w, barcodes=[]))
    assert w.decoded_codes.currentData() is None


def test_general_class_cannot_masquerade_as_catalog_code(window):
    w = window; w.db.catalog('products', 'person', 'Не сотрудник: тестовый товар')
    w.recognition_result(result_for(w, detections=[{'barcode': 'person', 'kind': 'general', 'score': .9, 'xyxy': [0, 0, 1, 1]}]))
    assert w.video.detections[0]['text'].startswith('Общий класс: person')


def test_preannotations_only_saved_after_review_and_allow_box_correction(window):
    w = window; w.db.catalog('products', 'PB1', 'Батарейка'); w.refresh()
    w.video.frame = np.zeros((300, 400, 3), dtype=np.uint8)
    w.annotation_frame = w.video.frame.copy(); w.preannotation_pending = True
    w.recognition_result(result_for(w, detections=[{'barcode': 'cardboard box', 'kind': 'general', 'score': .9, 'xyxy': [.1, .1, .5, .5]}]))
    assert not (w.root/'detection'/'annotations.json').exists()
    assert w.annotation_boxes == []
    w.proposals_table.selectRow(0)
    assert w.training_product.currentData() is None  # General labels require SKU assignment.
    w.training_product.setCurrentIndex(w.training_product.findData('PB1'))
    w.video.roi = (.2, .2, .3, .4)  # Operator corrected the proposed box.
    w.accept_proposal()
    assert not (w.root/'detection'/'annotations.json').exists()
    w.save_yolo_frame()
    rows = json.loads((w.root/'detection'/'annotations.json').read_text(encoding='utf-8'))
    assert rows[0]['boxes'] == [{'barcode': 'PB1', 'xywh': [.2, .2, .3, .4]}]


def test_onnx_rejected_for_training_before_loading_ml_runtime(tmp_path):
    from pikkabpe.yolo_backend import train_yolo
    with pytest.raises(ValueError, match='ONNX'):
        train_yolo(tmp_path, 1, 'warehouse.onnx')


def test_training_passes_selected_checkpoint_without_promoting_it(window, monkeypatch):
    from PySide6.QtCore import QProcess
    from pikkabpe.yolo_data import save_annotation
    w = window
    for index in range(2):
        save_annotation(w.root, np.full((30, 40, 3), index*100, dtype=np.uint8),
                        [{'barcode': 'PB1', 'xywh': [0, 0, 1, 1]}], str(index), 'fixture')
    weights = w.root/'models'/'previous.pt'; weights.write_bytes(b'checkpoint stand-in')
    w.training_weights.setText(str(weights))
    started = []
    monkeypatch.setattr(QProcess, 'start', lambda self, python, args: started.append(args))
    w.train()
    assert started[0][started[0].index('--weights')+1] == str(weights)
    assert not (w.root/'models'/'active.json').exists()


def test_per_class_report_serializes_numpy_counts():
    from pikkabpe.yolo_backend import class_metrics
    class Metrics:
        def summary(self): return [{'Class': 'PB1', 'Images': np.int64(3), 'mAP50': np.float64(.5)}]
    result = json.loads(json.dumps(class_metrics(Metrics())))
    assert result == [{'Class': 'PB1', 'Images': 3, 'mAP50': .5}]


def test_onnx_loader_uses_verified_bytes_for_unicode_windows_paths(tmp_path, monkeypatch):
    import hashlib
    from pikkabpe.warehouse import WarehousePredictor
    path = tmp_path/'модель склада.onnx'; path.write_bytes(b'onnx-test-fixture')
    report = {'engine': 'warehouse_onnx', 'output_format': 'yolov8_raw', 'classes': ['person'],
              'model_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    path.with_suffix('.json').write_text(json.dumps(report), encoding='utf-8')
    loaded = []
    monkeypatch.setattr(cv2.dnn, 'readNetFromONNX', lambda buffer: loaded.append(buffer))
    WarehousePredictor(path)
    assert isinstance(loaded[0], np.ndarray) and loaded[0].tobytes() == path.read_bytes()
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='Контрольная сумма'):
        WarehousePredictor(path)
