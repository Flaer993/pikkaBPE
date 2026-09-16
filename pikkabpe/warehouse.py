"""Warehouse YOLOv8 ONNX inference. No remote Python code is executed."""
import json
import hashlib
from pathlib import Path

import cv2
import numpy as np


class WarehousePredictor:
    def __init__(self, path):
        path = Path(path)
        report = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if report.get('engine') != 'warehouse_onnx' or report.get('output_format') != 'yolov8_raw':
            raise ValueError('Нужен ONNX WarehouseLogistics с отчётом загрузчика')
        model_bytes = path.read_bytes()
        if hashlib.sha256(model_bytes).hexdigest() != report.get('model_sha256'):
            raise ValueError('Контрольная сумма ONNX не совпала с отчётом')
        self.classes = report['classes']
        self.size = int(report.get('image_size', 640))
        # OpenCV's native filename loader fails on Cyrillic Windows paths.
        self.net = cv2.dnn.readNetFromONNX(np.frombuffer(model_bytes, dtype=np.uint8))
        self.device = 'cpu / OpenCV ONNX'

    def predict_image(self, image, confidence=.35):
        # Same letterbox convention as the upstream Ultralytics inference wrapper.
        rgb = np.asarray(image.convert('RGB'))
        h, w = rgb.shape[:2]
        ratio = min(self.size / w, self.size / h)
        nw, nh = round(w * ratio), round(h * ratio)
        left, top = (self.size - nw) // 2, (self.size - nh) // 2
        canvas = np.full((self.size, self.size, 3), 114, dtype=np.uint8)
        canvas[top:top + nh, left:left + nw] = cv2.resize(rgb, (nw, nh))
        self.net.setInput(cv2.dnn.blobFromImage(canvas, 1 / 255., swapRB=False))
        raw = self.net.forward()
        if raw.ndim != 3 or raw.shape[0] != 1 or raw.shape[1] != 4 + len(self.classes):
            raise ValueError(f'Неизвестный выход ONNX: {raw.shape}')
        return decode_output(raw[0].T, self.classes, (w, h), ratio, left, top, confidence)


def decode_output(rows, classes, size, ratio, left, top, confidence):
    """Class-aware NMS preserves nested objects such as a person and their vest."""
    width, height = size
    ids = rows[:, 4:].argmax(axis=1)
    scores = rows[np.arange(len(rows)), ids + 4]
    candidates = []
    for row, class_id, score in zip(rows, ids, scores):
        if not np.isfinite(row).all() or score < confidence:
            continue
        cx, cy, bw, bh = row[:4]
        x1 = float(np.clip((cx - bw / 2 - left) / ratio, 0, width))
        y1 = float(np.clip((cy - bh / 2 - top) / ratio, 0, height))
        x2 = float(np.clip((cx + bw / 2 - left) / ratio, 0, width))
        y2 = float(np.clip((cy + bh / 2 - top) / ratio, 0, height))
        if x2 > x1 and y2 > y1:
            candidates.append((int(class_id), float(score), [x1, y1, x2-x1, y2-y1]))
    detections = []
    for class_id in sorted({c[0] for c in candidates}):
        group = [c for c in candidates if c[0] == class_id]
        keep = cv2.dnn.NMSBoxes([c[2] for c in group], [c[1] for c in group], confidence, .5)
        for index in np.asarray(keep).reshape(-1):
            _, score, (x, y, w, h) = group[int(index)]
            detections.append({'label': classes[class_id], 'barcode': classes[class_id],
                               'kind': 'general', 'score': score,
                               'xyxy': [x/width, y/height, (x+w)/width, (y+h)/height]})
    return sorted(detections, key=lambda d: d['score'], reverse=True)[:300]
