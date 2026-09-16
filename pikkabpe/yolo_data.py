"""Reviewed full-image annotations and session-isolated YOLO dataset export."""
import hashlib
import json
import math
import random
import shutil
from pathlib import Path


def validate_boxes(boxes):
    if not boxes: raise ValueError('Добавьте хотя бы одну рамку')
    for box in boxes:
        x,y,w,h=box['xywh']
        if not box['barcode'] or not all(math.isfinite(v) for v in (x,y,w,h)) or min(x,y)<0 or min(w,h)<=0 or x+w>1.000001 or y+h>1.000001:
            raise ValueError('Некорректная рамка предмета')


def save_annotation(root,frame,boxes,session,source):
    import cv2
    validate_boxes(boxes)
    if not session.strip() or not source.strip(): raise ValueError('Укажите съёмку и источник')
    root=Path(root)/'detection'; (root/'images').mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(frame.tobytes()+str(frame.shape).encode()).hexdigest()
    path=root/'annotations.json'; rows=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    previous=next((r for r in rows if r['id']==digest),None)
    if previous and previous['session']!=session.strip(): raise ValueError('Этот кадр уже относится к другой съёмке. Используйте новый снимок.')
    image=root/'images'/(digest+'.png')
    ok,encoded=cv2.imencode('.png',frame)
    if not ok: raise ValueError('Не удалось сохранить кадр')
    image.write_bytes(encoded.tobytes())
    record={'id':digest,'image':str(image.resolve()),'boxes':boxes,'session':session.strip(),'source':source.strip()}
    rows=[r for r in rows if r['id']!=digest]+[record]
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return record


def split_annotations(rows):
    classes={b['barcode'] for r in rows for b in r['boxes']}
    sessions=sorted({r['session'] for r in rows})
    if not classes or len(sessions)<2: raise ValueError('YOLO нужны размеченные кадры минимум из двух независимых съёмок. Допускается один товар.')
    rng=random.Random(42)
    for _ in range(500):
        rng.shuffle(sessions); chosen=set(sessions[:max(1,round(len(sessions)*.25))])
        train=[r for r in rows if r['session'] not in chosen]; val=[r for r in rows if r['session'] in chosen]
        if {b['barcode'] for r in train for b in r['boxes']}==classes=={b['barcode'] for r in val for b in r['boxes']}:
            hashes={hashlib.sha256(Path(r['image']).read_bytes()).digest() for r in train}
            if any(hashlib.sha256(Path(r['image']).read_bytes()).digest() in hashes for r in val): raise ValueError('Одинаковые кадры в обучении и проверке')
            return train,val,sorted(classes)
    raise ValueError('Разметьте каждый товар в разных съёмках для обучения и проверки')


def export_dataset(root,pilot=False):
    root=Path(root).resolve(); path=root/'detection'/'annotations.json'
    if not path.exists(): raise ValueError('Сначала добавьте рамки и сохраните разметку кадров для YOLO')
    rows=json.loads(path.read_text(encoding='utf-8'))
    for row in rows: validate_boxes(row['boxes'])
    if pilot:
        if not rows: raise ValueError('Нет размеченных кадров')
        train=rows; val=rows; classes=sorted({b['barcode'] for r in rows for b in r['boxes']})
    else: train,val,classes=split_annotations(rows)
    # Unique directory prevents obsolete training files entering a later export.
    import uuid
    out=root/'detection'/'exports'/uuid.uuid4().hex; out.mkdir(parents=True)
    for split,items in [('train',train),('val',val)]:
        (out/'images'/split).mkdir(parents=True); (out/'labels'/split).mkdir(parents=True)
        for row in items:
            shutil.copy2(row['image'],out/'images'/split/(row['id']+'.png'))
            lines=[]
            for b in row['boxes']:
                x,y,w,h=b['xywh'];lines.append(f'{classes.index(b["barcode"])} {x+w/2:.8f} {y+h/2:.8f} {w:.8f} {h:.8f}')
            (out/'labels'/split/(row['id']+'.txt')).write_text('\n'.join(lines)+'\n')
    # JSON is a YAML subset accepted by Ultralytics, no YAML import in the GUI.
    (out/'data.yaml').write_text(json.dumps({'path':str(out),'train':'images/train','val':'images/val','names':classes}),encoding='utf-8')
    return out/'data.yaml',train,([] if pilot else val),classes
