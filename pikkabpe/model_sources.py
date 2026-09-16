"""Download a pinned data-only model bundle and preserve its provenance."""
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.request import urlopen

WAREHOUSE_REPO = 'MTerryJack/Element-Detect-WarehouseLogistics'
WAREHOUSE_REVISION = '4b37c4f133cc0b5e13007d272fcfd209700d6615'
WAREHOUSE_SHA256 = 'f695550212d2dd2059928f543f3550690527bc0ed7071dca040e5f12c849e432'
WAREHOUSE_CLASSES = ['barcode', 'car', 'cardboard box', 'fire', 'forklift', 'freight container',
                     'gloves', 'helmet', 'ladder', 'license plate', 'person', 'qr code',
                     'road sign', 'safety vest', 'smoke', 'traffic cone', 'traffic light',
                     'truck', 'van', 'wood pallet']


def fetch_warehouse(root):
    destination = Path(root) / 'models' / ('warehouse-' + WAREHOUSE_REVISION[:12])
    destination.mkdir(parents=True, exist_ok=True)
    # The upstream environment file is deliberately not needed or downloaded.
    with tempfile.TemporaryDirectory(dir=destination) as staging:
        staging = Path(staging)
        for name in ('weights.onnx', 'class_names.txt', 'README.md'):
            url = f'https://huggingface.co/{WAREHOUSE_REPO}/resolve/{WAREHOUSE_REVISION}/{name}'
            with urlopen(url, timeout=60) as response, (staging / name).open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        classes = (staging / 'class_names.txt').read_text(encoding='utf-8').splitlines()
        if classes != WAREHOUSE_CLASSES:
            raise ValueError('Неожиданный список классов WarehouseLogistics')
        digest = hashlib.sha256((staging / 'weights.onnx').read_bytes()).hexdigest()
        if digest != WAREHOUSE_SHA256:
            raise ValueError('Контрольная сумма WarehouseLogistics не совпала')
        report = {'engine': 'warehouse_onnx', 'kind': 'general_detector', 'generic': True,
                  'architecture': 'YOLOv8n', 'output_format': 'yolov8_raw', 'image_size': 640,
                  'classes': classes, 'source': f'https://huggingface.co/{WAREHOUSE_REPO}',
                  'revision': WAREHOUSE_REVISION, 'model_sha256': digest,
                  'trainable': False, 'unvalidated': True, 'validation_samples': 0,
                  'license': 'AGPL-3.0 (declared in ONNX metadata)',
                  'license_status': 'Model card has no separate license field; ONNX declares Ultralytics AGPL-3.0.',
                  'note': 'Upstream synthetic benchmark is not independent warehouse validation. No SKU recognition.'}
        (staging / 'weights.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        for file in staging.iterdir():
            file.replace(destination / file.name)
    return destination / 'weights.onnx'


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    args = parser.parse_args()
    print(fetch_warehouse(args.data))
