"""SQLite inventory ledger. Only explicit confirmation changes stock."""
import csv
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO meta VALUES('schema_version','1');
                CREATE TABLE IF NOT EXISTS products(barcode TEXT PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'шт');
                CREATE TABLE IF NOT EXISTS employees(id TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS locations(id TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, barcode TEXT NOT NULL REFERENCES products(barcode), quantity INTEGER NOT NULL CHECK(quantity>0), placed INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS stock(barcode TEXT NOT NULL REFERENCES products(barcode), location TEXT NOT NULL REFERENCES locations(id), quantity INTEGER NOT NULL CHECK(quantity>=0), PRIMARY KEY(barcode,location));
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('take','return','place')), barcode TEXT NOT NULL REFERENCES products(barcode), quantity INTEGER NOT NULL CHECK(quantity>0), location TEXT NOT NULL REFERENCES locations(id), employee TEXT REFERENCES employees(id), receipt TEXT REFERENCES receipts(id), evidence TEXT, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','rejected')), operator TEXT, confirmed TEXT);
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, created TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS labels(id TEXT PRIMARY KEY, image TEXT NOT NULL, barcode TEXT NOT NULL REFERENCES products(barcode), session TEXT NOT NULL, source TEXT NOT NULL, created TEXT NOT NULL);
            ''')
            if 'deleted' not in {r['name'] for r in db.execute('PRAGMA table_info(events)')}:
                db.execute('ALTER TABLE events ADD COLUMN deleted TEXT')
            for i in range(1, 8):
                db.execute('INSERT OR IGNORE INTO locations VALUES(?,?)', (f'R{i}', f'Стеллаж {i}'))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    @staticmethod
    def audit(db, action, payload):
        db.execute('INSERT INTO audit(created,action,payload) VALUES(?,?,?)', (now(), action, json.dumps(payload, ensure_ascii=False)))

    def catalog(self, table, key, name):
        if table not in ('products', 'employees', 'locations') or not key.strip() or not name.strip():
            raise ValueError('Нужны код и название')
        field = 'barcode' if table == 'products' else 'id'
        with self.connect() as db:
            db.execute(f'INSERT INTO {table}({field},name) VALUES(?,?) ON CONFLICT({field}) DO UPDATE SET name=excluded.name', (key.strip(), name.strip()))
            self.audit(db, 'catalog', {'table': table, 'key': key, 'name': name})

    def receipt(self, barcode, quantity):
        if type(quantity) is not int or quantity <= 0:
            raise ValueError('Количество должно быть целым положительным числом')
        rid = str(uuid.uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO receipts VALUES(?,?,?,0,?)', (rid, barcode, quantity, now()))
            self.audit(db, 'receipt_expected', {'id': rid, 'quantity': quantity})
        return rid

    def propose(self, kind, barcode, quantity, location, employee=None, receipt=None, evidence=None):
        if type(quantity) is not int or quantity <= 0:
            raise ValueError('Количество должно быть целым положительным числом')
        if kind == 'place' and not receipt:
            raise ValueError('Для размещения выберите ожидаемое поступление')
        if kind != 'place' and receipt:
            raise ValueError('Поступление привязывается только к размещению')
        eid = str(uuid.uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO events(id,created,kind,barcode,quantity,location,employee,receipt,evidence) VALUES(?,?,?,?,?,?,?,?,?)', (eid, now(), kind, barcode, quantity, location, employee, receipt, evidence))
            self.audit(db, 'event_proposed', {'id': eid})
        return eid

    def review(self, eid, operator, accept):
        if not operator.strip():
            raise ValueError('Укажите оператора')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM events WHERE id=?', (eid,)).fetchone()
            if not row:
                raise ValueError('Событие не найдено')
            if row['deleted'] or row['status'] != 'pending':
                raise ValueError('Событие уже рассмотрено')
            if accept:
                old = db.execute('SELECT quantity FROM stock WHERE barcode=? AND location=?', (row['barcode'], row['location'])).fetchone()
                quantity = (old[0] if old else 0) + (-row['quantity'] if row['kind'] == 'take' else row['quantity'])
                if quantity < 0:
                    raise ValueError('Недостаточный остаток. Проверьте место и начальное поступление.')
                if row['receipt']:
                    receipt = db.execute('SELECT * FROM receipts WHERE id=?', (row['receipt'],)).fetchone()
                    if receipt['barcode'] != row['barcode'] or receipt['placed'] + row['quantity'] > receipt['quantity']:
                        raise ValueError('Размещение не соответствует поступлению')
                    db.execute('UPDATE receipts SET placed=placed+? WHERE id=?', (row['quantity'], row['receipt']))
                db.execute('INSERT INTO stock VALUES(?,?,?) ON CONFLICT(barcode,location) DO UPDATE SET quantity=excluded.quantity', (row['barcode'], row['location'], quantity))
            db.execute('UPDATE events SET status=?,operator=?,confirmed=? WHERE id=?', ('confirmed' if accept else 'rejected', operator, now(), eid))
            self.audit(db, 'event_reviewed', {'id': eid, 'operator': operator, 'accepted': accept})

    def delete_event(self, eid, operator):
        if not operator.strip():
            raise ValueError('Укажите оператора на вкладке «Наблюдение»')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM events WHERE id=?', (eid,)).fetchone()
            if not row or row['deleted']:
                raise ValueError('Событие не найдено или уже удалено')
            if row['status'] == 'confirmed':
                old = db.execute('SELECT quantity FROM stock WHERE barcode=? AND location=?', (row['barcode'], row['location'])).fetchone()
                quantity = (old[0] if old else 0) + (row['quantity'] if row['kind'] == 'take' else -row['quantity'])
                if quantity < 0:
                    raise ValueError('Удаление создаст отрицательный остаток. Сначала отмените связанные последующие взятия.')
                db.execute('INSERT INTO stock VALUES(?,?,?) ON CONFLICT(barcode,location) DO UPDATE SET quantity=excluded.quantity', (row['barcode'], row['location'], quantity))
                if row['receipt']:
                    db.execute('UPDATE receipts SET placed=placed-? WHERE id=?', (row['quantity'], row['receipt']))
            db.execute('UPDATE events SET deleted=? WHERE id=?', (now(), eid))
            self.audit(db, 'event_deleted', {'event': dict(row), 'operator': operator.strip()})

    def label(self, image, barcode, session, source):
        if not session.strip() or not source.strip():
            raise ValueError('Укажите сессию съёмки и источник')
        with self.connect() as db:
            db.execute('INSERT INTO labels VALUES(?,?,?,?,?,?)', (str(uuid.uuid4()), str(image), barcode, session, source, now()))
            self.audit(db, 'label_added', {'image': str(image), 'barcode': barcode, 'session': session})

    def export(self, path):
        rows = self.rows("SELECT * FROM events WHERE status='confirmed' AND deleted IS NULL ORDER BY created")
        fields = ['id','created','kind','barcode','quantity','location','employee','receipt','operator','confirmed']
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fields, extrasaction='ignore')
            writer.writeheader()
            for row in rows:
                # Spreadsheet formula injection guard; raw data stays unchanged in SQLite.
                writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v for k, v in row.items()})

    def backup(self, path):
        with self.connect() as source, sqlite3.connect(path) as dest:
            source.backup(dest)
