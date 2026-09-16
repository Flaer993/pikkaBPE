"""Decode exact barcode payloads at source resolution; never infer a SKU from stripes."""
import math

import numpy as np


def decode_barcodes(image, detections=()):
    import zxingcpp
    width, height = image.size
    # A whole-frame pass also works when the general detector misses a barcode.
    regions = [(0, 0, width, height)]
    for d in detections:
        if d.get('label', d.get('barcode', '')).lower() not in ('barcode', 'qr code'):
            continue
        x1, y1, x2, y2 = d['xyxy']
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
            continue
        px, py = max(16, (x2-x1)*width*.15), max(16, (y2-y1)*height*.15)
        regions.append((max(0, int(x1*width-px)), max(0, int(y1*height-py)),
                        min(width, math.ceil(x2*width+px)), min(height, math.ceil(y2*height+py))))
    results = []
    for x1, y1, x2, y2 in regions[:31]:
        if x2 <= x1 or y2 <= y1:
            continue
        gray = np.asarray(image.crop((x1, y1, x2, y2)).convert('L'))
        for code in zxingcpp.read_barcodes(gray, try_rotate=True, try_downscale=True, text_mode=zxingcpp.TextMode.Plain):
            if not code.valid or not code.text:
                continue
            points = [code.position.top_left, code.position.top_right,
                      code.position.bottom_right, code.position.bottom_left]
            box = [(min(p.x for p in points)+x1)/width, (min(p.y for p in points)+y1)/height,
                   (max(p.x for p in points)+x1)/width, (max(p.y for p in points)+y1)/height]
            box = [float(np.clip(v, 0, 1)) for v in box]
            # Deduplicate repeated crop reads, but retain distinct physical labels.
            if any(r['text'] == code.text and overlap(r['xyxy'], box) > .5 for r in results):
                continue
            results.append({'text': code.text, 'format': str(code.format).removeprefix('BarcodeFormat.'), 'xyxy': box})
    return results


def overlap(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0
