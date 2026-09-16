"""Printable internal Code 128 labels and operator-selected photo imports."""
import hashlib
import uuid
from pathlib import Path
from PIL import Image, ImageOps
from barcode import Code128
from barcode.writer import SVGWriter


def new_code():
    return 'PB' + uuid.uuid4().hex[:16].upper()


def barcode_label(root, code):
    if not code or any(not 32 <= ord(c) <= 126 for c in code):
        raise ValueError('Для Code 128 используйте цифры и латинские символы ASCII')
    folder = Path(root) / 'barcodes'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (hashlib.sha256(code.encode()).hexdigest()[:24] + '.svg')
    with path.open('wb') as stream:
        Code128(code, writer=SVGWriter()).write(stream, options={'module_width': 0.3, 'module_height': 18, 'quiet_zone': 6})
    return path


def import_photos(store, root, paths, code, session, source):
    if not store.rows('SELECT 1 FROM products WHERE barcode=?', (code,)):
        raise ValueError('Выберите товар для фотографий')
    if not session.strip() or not source.strip():
        raise ValueError('Укажите съёмку и источник фотографий')
    folder = Path(root) / 'evidence'
    folder.mkdir(parents=True, exist_ok=True)
    added, errors = 0, []
    for filename in paths:
        target = folder / f'{uuid.uuid4()}.png'
        try:
            with Image.open(filename) as image:
                ImageOps.exif_transpose(image).convert('RGB').save(target)
            store.label(target, code, session.strip(), source.strip())
            added += 1
        except Exception as exc:
            target.unlink(missing_ok=True)
            errors.append(f'{Path(filename).name}: {exc}')
    return added, errors
