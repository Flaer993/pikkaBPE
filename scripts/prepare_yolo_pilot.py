"""Create reviewable foreground boxes for single-object catalog illustrations only."""
import json
from pathlib import Path
import sys
import random
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pikkabpe.store import Store
from pikkabpe.yolo_data import save_annotation


def main():
    rows=Store(ROOT/'datasets/energy-catalog/pilot/warehouse.db').rows('SELECT * FROM labels ORDER BY barcode')
    tiles=[]; objects=[]
    for index,row in enumerate(rows):
        frame=cv2.imdecode(np.fromfile(row['image'],dtype=np.uint8),cv2.IMREAD_COLOR)
        mask=(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)<230).astype('uint8')*255
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        contour=max(contours,key=cv2.contourArea);x,y,w,h=cv2.boundingRect(contour)
        ih,iw=frame.shape[:2]; margin=6
        x0=max(0,x-margin);y0=max(0,y-margin);x1=min(iw,x+w+margin);y1=min(ih,y+h+margin)
        boxes=[{'barcode':row['barcode'],'xywh':[x0/iw,y0/ih,(x1-x0)/iw,(y1-y0)/ih]}]
        objects.append((row['barcode'],frame[y0:y1,x0:x1].copy()))
        save_annotation(ROOT/'datasets/energy-yolo-pilot',frame,boxes,'catalog-source-intellectual-energy',row['source'])
        preview=frame.copy();cv2.rectangle(preview,(x0,y0),(x1,y1),(0,180,0),4)
        preview=cv2.resize(preview,(300,300));cv2.putText(preview,str(index+1),(10,25),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,0),2);tiles.append(preview)
    montage=np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)])
    cv2.imwrite(str(ROOT/'tmp/yolo-pilot-annotation-review.png'),montage)
    # Synthetic compositions diversify position, scale and object count; never a validation set.
    rng=random.Random(42)
    for index in range(32):
        scene=np.full((640,640,3),rng.randint(205,255),dtype=np.uint8); boxes=[]; previews=[]
        slots=[(10,10),(330,10),(10,330),(330,330)];rng.shuffle(slots)
        for x,y in slots[:rng.randint(1,4)]:
            code,crop=rng.choice(objects);height,width=crop.shape[:2]
            scale=rng.randint(170,285)/max(height,width)
            crop=cv2.resize(crop,None,fx=scale,fy=scale);height,width=crop.shape[:2]
            x+=rng.randint(0,15);y+=rng.randint(0,15)
            mask=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)<245
            tile=scene[y:y+height,x:x+width];tile[mask]=crop[mask]
            boxes.append({'barcode':code,'xywh':[x/640,y/640,width/640,height/640]})
        save_annotation(ROOT/'datasets/energy-yolo-pilot',scene,boxes,'catalog-source-intellectual-energy','Synthetic composition of catalog images; not independent evidence')
    print('Prepared',len(rows),'catalog boxes. Review tmp/yolo-pilot-annotation-review.png before training.')

if __name__=='__main__': main()
