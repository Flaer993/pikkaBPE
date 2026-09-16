"""Ultralytics lives in the external CUDA environment, never inside the GUI EXE."""
import json
from pathlib import Path
import shutil
import time


def class_metrics(metrics):
    # Ultralytics includes NumPy integer counts; plain json.dumps rejects them.
    return [{key: value.item() if hasattr(value,'item') else value for key,value in row.items()}
            for row in metrics.summary()]


class YoloPredictor:
    def __init__(self,path):
        from ultralytics import YOLO
        import torch
        self.device='cuda:0' if torch.cuda.is_available() else 'cpu'
        self.model=YOLO(str(path))
        if self.model.task!='detect': raise ValueError('Нужна модель YOLO Detect, не классификатор или сегментация')

    def predict_image(self,image,confidence=.35):
        result=self.model.predict(image,imgsz=640,conf=max(.01,min(1,float(confidence))),device=self.device,verbose=False,max_det=300,agnostic_nms=False,iou=.5)[0]
        if result.boxes is None: return []
        return [{'barcode':str(self.model.names[int(cls)]),'score':float(score),'xyxy':[float(x) for x in box]}
                for box,score,cls in zip(result.boxes.xyxyn.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist())]


def train_yolo(root,epochs,weights,pilot=False):
    if Path(weights).suffix.lower()!='.pt': raise ValueError('Для дообучения нужны исходные веса .pt. ONNX предназначен для распознавания.')
    from ultralytics import YOLO
    from .yolo_data import export_dataset
    import torch
    if not torch.cuda.is_available(): raise ValueError('CUDA недоступна в выбранном окружении Python')
    root=Path(root).resolve()
    yaml,train,val,classes=export_dataset(root,pilot)
    model=YOLO(str(weights))
    if model.task!='detect': raise ValueError('Для рамок нужен checkpoint YOLO Detect')
    initial_checkpoint=Path(model.ckpt_path).resolve()
    architecture=Path(model.model.yaml.get('yaml_file','yolo-detect')).stem
    stamp=time.strftime('%Y%m%d-%H%M%S')
    model.train(data=str(yaml),epochs=epochs,imgsz=640,batch=4,device=0,workers=0,amp=False,
                project=str(root/'detection'/'runs'),name=stamp,exist_ok=False,plots=False,cache=False,
                val=not pilot,seed=42,deterministic=True,close_mosaic=0,
                mosaic=0.0 if pilot else 1.0,scale=.2 if pilot else .5)
    output=root/'models'/f'yolo-{stamp}.pt';output.parent.mkdir(parents=True,exist_ok=True)
    # Last checkpoint avoids selecting on training images in unvalidated pilot mode.
    checkpoint=model.trainer.last if pilot else model.trainer.best
    shutil.copy2(checkpoint,output)
    metrics={str(k):float(v) for k,v in model.trainer.metrics.items()} if not pilot else None
    report={'kind':'yolo_detector','engine':'yolo','architecture':'YOLOv8n','classes':classes,'epochs':epochs,'train_samples':len(train),'validation_samples':len(val),'accuracy':None,'detection_metrics':metrics,'unvalidated':pilot,'gpu':torch.cuda.get_device_name(0),'note':'Catalog pilot; no independent validation.' if pilot else 'Session-isolated validation; check per-class results on warehouse scenes.'}
    import hashlib
    source=initial_checkpoint
    report.update({'architecture':architecture,'initial_weights':str(weights),'initial_weights_resolved':str(source),
                   'initial_weights_sha256':hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None,
                   'model_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                   'validation_sessions':sorted({r['session'] for r in val}),
                   'train_sessions':sorted({r['session'] for r in train}),
                   'per_class_metrics':class_metrics(model.trainer.validator.metrics) if not pilot else None})
    output.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('YOLO saved:',output,flush=True)
    return output
