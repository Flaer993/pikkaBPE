"""Supervised lightweight object classifier. Never trains on its own predictions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import time

from .store import Store


def split_sessions(rows, seed=42):
    classes=sorted({r['barcode'] for r in rows})
    if len(classes)<2: raise ValueError('Нужны минимум два класса товаров')
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


def train_model(root,epochs,pretrained=True):
    import torch
    from torch import nn
    from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
    from PIL import Image
    if not torch.cuda.is_available(): raise RuntimeError('CUDA недоступна. Установите PyTorch cu118 и драйвер NVIDIA.')
    random.seed(42); torch.manual_seed(42)
    root=Path(root); os.environ.setdefault('TORCH_HOME',str(root/'models'/'cache'))
    rows=Store(root/'warehouse.db').rows('SELECT * FROM labels ORDER BY id')
    training,validation,classes=split_sessions(rows)
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
    report={'kind':'object_crop_classifier','gpu':torch.cuda.get_device_name(0),'train_samples':len(training),'validation_samples':len(validation),'validation_sessions':sorted({r['session'] for r in validation}),'classes':classes,'accuracy':matrix.diag().sum().item()/len(validation),'confusion_matrix':matrix.tolist(),'epochs':epochs,'autonomous_stock_enabled':False,'note':'Small pilot metrics do not establish warehouse accuracy.'}
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
        import torch
        from PIL import Image
        with Image.open(path) as image: tensor=transforms_for()(image.convert('RGB')).unsqueeze(0).to(self.device)
        with torch.inference_mode(): prob=self.model(tensor).softmax(1)[0]
        index=int(prob.argmax()); return self.classes[index],float(prob[index])


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--data'); parser.add_argument('--epochs',type=int,default=10)
    parser.add_argument('--predict'); parser.add_argument('--model')
    args=parser.parse_args()
    if args.predict:
        if not args.model: parser.error('--model is required for prediction')
        code,score=Predictor(args.model).predict(args.predict); print(f'{code}: {score:.1%}')
    elif args.data: train_model(args.data,args.epochs)
    else: parser.error('--data is required for training')
