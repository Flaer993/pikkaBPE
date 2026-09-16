"""Idempotent import of the reviewed public catalog snapshot."""
import json
from pathlib import Path


def import_catalog(store,path=None):
    path=Path(path) if path else Path(__file__).parent/'assets'/'energy-catalog.json'
    snapshot=json.loads(path.read_text(encoding='utf-8'))
    added=0
    with store.connect() as db:
        for item in snapshot['products']:
            cursor=db.execute('INSERT OR IGNORE INTO products(barcode,name) VALUES(?,?)',(item['barcode'],item['name']))
            added+=cursor.rowcount
        store.audit(db,'catalog_import',{'source':snapshot['source'],'fetched':snapshot['fetched'],'added':added})
    return added
