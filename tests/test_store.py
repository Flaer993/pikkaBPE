import sqlite3
import csv
import pytest
from pikkabpe.store import Store

@pytest.fixture
def db(tmp_path):
    result=Store(tmp_path/'stock.db'); result.catalog('products','123','Аккумулятор'); return result

def place(db,qty=5):
    rid=db.receipt('123',qty); event=db.propose('place','123',qty,'R1',receipt=rid); db.review(event,'operator',True); return rid,event

def test_pending_does_not_change_stock(db):
    db.propose('return','123',1,'R1'); assert db.rows('SELECT * FROM stock')==[]

def test_confirm_exactly_once(db):
    _,event=place(db)
    with pytest.raises(ValueError): db.review(event,'operator',True)
    assert db.rows('SELECT quantity FROM stock')[0]['quantity']==5

def test_negative_stock_rollback(db):
    place(db); event=db.propose('take','123',6,'R1')
    with pytest.raises(ValueError): db.review(event,'op',True)
    assert db.rows('SELECT quantity FROM stock')[0]['quantity']==5
    assert db.rows('SELECT status FROM events WHERE id=?',(event,))[0]['status']=='pending'

def test_receipt_overplacement_rejected(db):
    rid,_=place(db); event=db.propose('place','123',1,'R2',receipt=rid)
    with pytest.raises(ValueError): db.review(event,'op',True)
    assert db.rows('SELECT placed FROM receipts')[0]['placed']==5

def test_take_return_and_reject(db):
    place(db); event=db.propose('take','123',2,'R1'); db.review(event,'op',True)
    event=db.propose('return','123',1,'R1'); db.review(event,'op',True)
    event=db.propose('take','123',1,'R1'); db.review(event,'op',False)
    assert db.rows('SELECT quantity FROM stock')[0]['quantity']==4

def test_backup_and_export(db,tmp_path):
    _,confirmed=place(db)
    pending=db.propose('take','123',1,'R1')
    db.backup(tmp_path/'backup.db'); db.export(tmp_path/'events.csv')
    assert Store(tmp_path/'backup.db').rows('SELECT quantity FROM stock')[0]['quantity']==5
    with (tmp_path/'events.csv').open(encoding='utf-8-sig') as stream: rows=list(csv.DictReader(stream))
    assert len(rows)==1 and rows[0]['id']==confirmed
    assert pending not in [r['id'] for r in rows]

def test_bad_foreign_keys_and_quantity(db):
    with pytest.raises(sqlite3.IntegrityError): db.propose('return','missing',1,'R1')
    with pytest.raises(ValueError): db.propose('return','123',0,'R1')
    with pytest.raises(ValueError): db.propose('return','123',1.5,'R1')
