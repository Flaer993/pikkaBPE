"""Compose general detection, catalog detection and exact barcode decoding."""
import json
from pathlib import Path


def load_detector(path):
    path = Path(path)
    report = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if report.get('engine') == 'warehouse_onnx':
        from .warehouse import WarehousePredictor
        return WarehousePredictor(path), 'general'
    if report.get('engine') == 'yolo':
        from .yolo_backend import YoloPredictor
        return YoloPredictor(path), 'general' if report.get('generic') else 'product'
    raise ValueError('Совместный обзор требует детектор YOLO, а не классификатор одного предмета')


class VisionPipeline:
    def __init__(self, model=None, warehouse=None, decode=False):
        self.detectors = []
        paths = []
        for path in (model, warehouse):
            if path and Path(path).resolve() not in paths:
                paths.append(Path(path).resolve())
                self.detectors.append(load_detector(path))
        self.decode = decode
        if decode:
            import zxingcpp  # Fail at startup with a useful error, not silently on every frame.
        self.device = ' + '.join(d.device for d, _ in self.detectors) or 'cpu'

    def predict_image(self, image, confidence=.35):
        detections = []
        for detector, kind in self.detectors:
            detections.extend({**d, 'kind': kind} for d in detector.predict_image(image, confidence))
        from .barcodes import decode_barcodes
        codes = decode_barcodes(image, detections) if self.decode else []
        return {'detections': detections, 'barcodes': codes}
