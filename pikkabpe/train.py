"""Supervised lightweight object classifier. Never trains on its own predictions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import time

from .store import Store


def training_guidance(rows):
    classes={r['barcode'] for r in rows}
    if not rows:
        return 'Добавьте фотографии минимум двух разных товаров. Для каждого нужны две независимые съёмки: обучение и проверка.'
    if len(classes)<2:
        return (f'Добавлено {len(rows)} фото одного товара. Это один класс, независимо от числа снимков. '
                'Добавьте фотографии второго товара. Затем отдельно снимите оба товара ещё раз, нажмите «Новая съёмка» и добавьте новые фото. '
                'Пока обучение не запущено, файл модели не создаётся.')
    missing=[code for code in sorted(classes) if len({r['session'] for r in rows if r['barcode']==code})<2]
    if missing:
        return ('Нужна отдельная проверочная съёмка для товаров: '+', '.join(missing)+'. '
                'Снимите их заново, нажмите «Новая съёмка» и добавьте новые фото. Не загружайте копии прежних снимков.')
    return ''


def split_sessions(rows, seed=42):
    classes=sorted({r['barcode'] for r in rows})
    if len(classes)<2: raise ValueError(training_guidance(rows))
    sessions=sorted({r['session'] for r in rows})
    if len(sessions)<2: raise ValueError('Нужны минимум две независимые сессии съёмки')
    # Search a group split with every class present on both sides.
    rng=random.Random(seed)
    for _ in range(500):
        rng.shuffle(sessions)
        validation=set(sessions[:max(1,round(len(sessions)*.25))])
        train=[r for r in rows if r['session'] not in validation]
        val=[r for r in rows if r['session'] in validation]
        if set(r['barcode'] for r in train)==set(classes)==set(r['barcode'] for r in val):
            train_hashes={hashlib.sha256(Path(r['image']).read_bytes()).digest() for r in train}
            if any(hashlib.sha256(Path(r['image']).read_bytes()).digest() in train_hashes for r in val):
                raise ValueError('Одинаковые изображения в обучении и проверке. Удалите дубликаты.')
            return train,val,classes
    raise ValueError('Каждый класс должен быть снят в разных сессиях для независимой проверки')


def transforms_for(train=False):
    from torchvision import transforms
    ops=[transforms.Resize((224,224))]
    if train: ops.extend([transforms.ColorJitter(.12,.12,.1),transforms.RandomHorizontalFlip()])
    return transforms.Compose(ops+[transforms.ToTensor(),transforms.Normalize([.485,.456,.406],[.229,.224,.225])])


def train_model(root,epochs,pretrained=True,catalog_pilot=False):
    import torch
    from torch import nn
    from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
    from PIL import Image
    if not torch.cuda.is_available(): raise RuntimeError('CUDA недоступна. Установите PyTorch cu118 и драйвер NVIDIA.')
    random.seed(42); torch.manual_seed(42)
    root=Path(root); os.environ.setdefault('TORCH_HOME',str(root/'models'/'cache'))
    rows=Store(root/'warehouse.db').rows('SELECT * FROM labels ORDER BY id')
    if catalog_pilot:
        training=rows; validation=[]; classes=sorted({r['barcode'] for r in rows})
        if len(classes)<2: raise ValueError('Для каталожного пилота нужны хотя бы два товара')
        print('CATALOG PILOT: no independent validation; do not use for autonomous inventory.',flush=True)
    else: training,validation,classes=split_sessions(rows)
    class Dataset(torch.utils.data.Dataset):
        def __init__(self,items,augment): self.items=items; self.transform=transforms_for(augment)
        def __len__(self): return len(self.items)
        def __getitem__(self,i):
            row=self.items[i]
            with Image.open(row['image']) as image: tensor=self.transform(image.convert('RGB'))
            return tensor, classes.index(row['barcode'])
    model=mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT if pretrained else None)
    # Freeze feature extractor for the initial small dataset and legacy P4000.
    for p in model.parameters(): p.requires_grad=False
    model.classifier[-1]=nn.Linear(model.classifier[-1].in_features,len(classes))
    model=model.cuda()
    optimizer=torch.optim.AdamW(model.classifier[-1].parameters(),lr=.002)
    train_loader=torch.utils.data.DataLoader(Dataset(training,True),batch_size=16,shuffle=True,num_workers=0)
    val_loader=torch.utils.data.DataLoader(Dataset(validation,False),batch_size=16,num_workers=0)
    print(f'GPU: {torch.cuda.get_device_name(0)}; train={len(training)}, validation={len(validation)}; classes={classes}',flush=True)
    for epoch in range(epochs):
        model.eval()  # Keep frozen batchnorm statistics; train only last linear layer.
        loss_sum=0
        for inputs,labels in train_loader:
            optimizer.zero_grad(); logits=model(inputs.cuda()); loss=nn.functional.cross_entropy(logits,labels.cuda()); loss.backward(); optimizer.step(); loss_sum+=loss.item()*len(labels)
        print(f'epoch {epoch+1}/{epochs}; loss={loss_sum/len(training):.4f}',flush=True)
    matrix=torch.zeros((len(classes),len(classes)),dtype=torch.int64)
    model.eval()
    with torch.inference_mode():
        for inputs,labels in val_loader:
            predicted=model(inputs.cuda()).argmax(1).cpu()
            for actual,pred in zip(labels,predicted): matrix[actual,pred]+=1
    report={'kind':'catalog_pilot_unvalidated' if catalog_pilot else 'object_crop_classifier','gpu':torch.cuda.get_device_name(0),'train_samples':len(training),'validation_samples':len(validation),'validation_sessions':sorted({r['session'] for r in validation}),'classes':classes,'accuracy':matrix.diag().sum().item()/len(validation) if validation else None,'confusion_matrix':matrix.tolist() if validation else None,'epochs':epochs,'autonomous_stock_enabled':False,'note':'No independent validation. Catalog-only prototype; operator review required.' if catalog_pilot else 'Small pilot metrics do not establish warehouse accuracy.'}
    out=root/'models'/f'candidate-{time.strftime("%Y%m%d-%H%M%S")}.pt'; out.parent.mkdir(parents=True,exist_ok=True)
    torch.save({'state_dict':{k:v.cpu() for k,v in model.state_dict().items()},'classes':classes,'architecture':'mobilenet_v3_small'},out)
    out.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True); print(f'Candidate: {out}',flush=True)
    return out


class Predictor:
    def __init__(self,path):
        import torch
        from torchvision.models import mobilenet_v3_small
        checkpoint=torch.load(path,map_location='cpu',weights_only=True)
        self.classes=checkpoint['classes']; self.device='cuda' if torch.cuda.is_available() else 'cpu'
        self.model=mobilenet_v3_small(weights=None)
        self.model.classifier[-1]=torch.nn.Linear(self.model.classifier[-1].in_features,len(self.classes))
        self.model.load_state_dict(checkpoint['state_dict']); self.model.to(self.device).eval()
    def predict(self,path):
        from PIL import Image
        with Image.open(path) as image: return self.predict_image(image)

    def predict_image(self,image):
        import torch
        tensor=transforms_for()(image.convert('RGB')).unsqueeze(0).to(self.device)
        with torch.inference_mode(): prob=self.model(tensor).softmax(1)[0]
        index=int(prob.argmax()); return self.classes[index],float(prob[index])


def serve(model):
    import sys, base64, io
    from PIL import Image
    predictor=Predictor(model)
    print(json.dumps({'ready':True,'device':predictor.device}),flush=True)
    for line in sys.stdin:
        request={}
        try:
            request=json.loads(line)
            with Image.open(io.BytesIO(base64.b64decode(request['image'],validate=True))) as image:
                code,score=predictor.predict_image(image)
            result={'id':request['id'],'barcode':code,'score':score}
        except Exception as exc:
            result={'id':request.get('id'),'error':str(exc)}
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--data'); parser.add_argument('--epochs',type=int,default=10)
    parser.add_argument('--predict'); parser.add_argument('--model')
    parser.add_argument('--serve',action='store_true')
    parser.add_argument('--catalog-pilot',action='store_true',help='Explicit unvalidated catalog experiment; never used by normal UI training')
    args=parser.parse_args()
    if args.serve:
        if not args.model: parser.error('--model is required')
        serve(args.model)
    elif args.predict:
        if not args.model: parser.error('--model is required for prediction')
        code,score=Predictor(args.model).predict(args.predict); print(f'{code}: {score:.1%}')
    elif args.data: train_model(args.data,args.epochs,catalog_pilot=args.catalog_pilot)
    else: parser.error('--data is required for training')
