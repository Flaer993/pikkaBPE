"""Download a small licensed exploration set, separate from operational inventory.
Run --approve-reviewed only after reviewing contact-sheet.jpg. Never auto-promotes a model.
"""
import argparse
import html
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
from PIL import Image,ImageOps,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pikkabpe.store import Store

FILES={
 'DEMO-BATTERY': ['AA-Akku spezial.jpg','Akku AA LR6 Mignon.jpg','Akku NiZn AAA AA by NicoJenner.jpg','Amazon Basics Rechargeable AA Battery.jpg','BAUHAUS NiMH AA 2300mAh.JPG','Early 2000s Rechargeable Batteries.jpg'],
 'DEMO-RESISTOR': ['0.5 ohm power resistor.jpg','25 ohm power resistors.jpg','A mountain of resistors.jpg','Carbon and ceramic resistors of different power ratings.jpg','Electronic component resistors.jpg']
}

def request(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'pikkaBPE-prototype/0.1 (https://github.com/Flaer993/pikkaBPE)'}),timeout=30)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--approve-reviewed',action='store_true'); args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]; root=project/'datasets'/'internet-pilot'; root.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for code,titles in FILES.items():
        for index,title in enumerate(titles):
            import hashlib
            path=root/f'{code}-{hashlib.sha256(title.encode()).hexdigest()[:12]}.jpg'
            query=urllib.parse.urlencode({'action':'query','format':'json','titles':'File:'+title,'prop':'imageinfo','iiprop':'url|extmetadata','iiurlwidth':'640'})
            response=json.load(request('https://commons.wikimedia.org/w/api.php?'+query))
            page=next(iter(response['query']['pages'].values())); info=page['imageinfo'][0]; meta=info['extmetadata']
            clean=lambda key: html.unescape(re.sub('<[^>]+>','',meta.get(key,{}).get('value','')))
            license=clean('LicenseShortName')
            if not any(term in license for term in ('CC BY','CC0','Public domain')):
                print('SKIPPED: license needs separate review:',title,license,flush=True)
                continue
            if not path.exists():
                path.write_bytes(request(info.get('thumburl',info['url'])).read())
                with Image.open(path) as image: image.convert('RGB').save(path,quality=92)
            manifest.append({'image':str(path),'barcode':code,'session':f'commons-{page["pageid"]}','source':info['descriptionurl'],'license':license,'author':clean('Artist'),'license_url':clean('LicenseUrl'),'title':title,'review':'assistant visual review required; demo classes only'})
            print(title,license,flush=True)
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(1200,800),'#20262d'); draw=ImageDraw.Draw(sheet)
    for i,row in enumerate(manifest):
        with Image.open(row['image']) as source: image=ImageOps.contain(source.convert('RGB'),(280,220))
        x=(i%4)*300; y=(i//4)*266
        sheet.paste(image,(x+(300-image.width)//2,y)); draw.text((x+8,y+225),f'{i+1:02d} {row["barcode"]}',fill='white')
    sheet.save(root/'contact-sheet.jpg')
    if args.approve_reviewed:
        db=Store(root/'warehouse.db')
        for code in FILES: db.catalog('products',code,code)
        for row in manifest:
            if not db.rows('SELECT id FROM labels WHERE image=?',(row['image'],)):
                db.label(row['image'],row['barcode'],row['session'],row['source']+' / '+row['license']+' / assistant-reviewed broad category pilot')
        public=[{k:v for k,v in row.items() if k!='image'} for row in manifest]
        (project/'docs'/'seed-sources.json').write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Contact sheet:',root/'contact-sheet.jpg')

if __name__=='__main__': main()
