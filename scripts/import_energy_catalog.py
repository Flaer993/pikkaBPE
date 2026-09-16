"""Fetch public product cards and images. Run explicitly, never during UI startup."""
import concurrent.futures
import hashlib
import io
import json
import re
import sys
import urllib.request
from pathlib import Path
from datetime import datetime,timezone
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'datasets'/'energy-catalog'
BASE='https://intellectual.energy'

def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'pikkaBPE catalog research/0.2'}),timeout=30).read()

def card(url):
    try:
        doc=BeautifulSoup(fetch(url),'html.parser')
        photos=doc.select('.productDetail-slider-block-image img')
        if not doc.h1 or not photos: return {'url':url,'skipped':'not a product card'}
        name=doc.h1.get_text(' ',strip=True)
        code='IE'+hashlib.sha256(url.encode()).hexdigest()[:16].upper()
        images=[]
        for image in photos:
            src=image.get('srcset','').split()[0] if image.get('srcset') else image.get('src')
            if not src: continue
            source=urllib.parse.urljoin(BASE,src)
            if urllib.parse.urlparse(source).hostname!='intellectual.energy': continue
            raw=fetch(source)
            with Image.open(io.BytesIO(raw)) as im:
                im=im.convert('RGB'); im.thumbnail((1200,1200))
                digest=hashlib.sha256(im.tobytes()+str(im.size).encode()).hexdigest()
                file=OUT/'images'/(digest+'.png')
                im.save(file)
            if not any(x['sha256_pixels']==digest for x in images):
                images.append({'url':source,'file':str(file),'sha256_pixels':digest})
        return {'barcode':code,'name':name,'url':url,'images':images}
    except Exception as exc: return {'url':url,'skipped':str(exc)}

def main():
    (OUT/'images').mkdir(parents=True,exist_ok=True)
    sitemap=fetch(BASE+'/sitemap.xml').decode()
    urls=sorted(set(u for u in re.findall(r'<loc>(.*?)</loc>',sitemap) if '/catalog/' in u and len(urllib.parse.urlparse(u).path.strip('/').split('/'))>=3))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows=[]
        for row in pool.map(card,urls):
            rows.append(row);print(len(rows),len(urls),row.get('name',row.get('skipped')),flush=True)
    report={'source':BASE+'/catalog/','fetched':datetime.now(timezone.utc).isoformat(),'products':[x for x in rows if 'barcode' in x],'skipped':[x for x in rows if 'skipped' in x],'image_license':'No open license verified; source retained, local supervised pilot only.'}
    (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Imported cards:',len(report['products']))

if __name__=='__main__':main()
