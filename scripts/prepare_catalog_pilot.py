"""Prepare an isolated unvalidated experiment; exclude photos shared by SKUs."""
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pikkabpe.store import Store


def main():
    root=ROOT/'datasets'/'energy-catalog'
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    counts=Counter(i['sha256_pixels'] for p in manifest['products'] for i in p['images'])
    store=Store(root/'pilot'/'warehouse.db'); excluded=[]
    for product in manifest['products']:
        images=[i for i in product['images'] if counts[i['sha256_pixels']]==1]
        if not images: excluded.append(product['name']); continue
        store.catalog('products',product['barcode'],product['name'])
        for image in images:
            file=root/'images'/(image['sha256_pixels']+'.png')
            if not store.rows('SELECT 1 FROM labels WHERE image=?',(str(file),)):
                store.label(file,product['barcode'],'catalog-source-intellectual-energy',product['url'])
    (root/'pilot-preparation.json').write_text(json.dumps({'excluded_shared_images':excluded,'independent_validation':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Prepared images:',len(store.rows('SELECT * FROM labels')))

if __name__=='__main__': main()
