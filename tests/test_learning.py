import pytest
from pikkabpe.train import split_sessions

def test_session_isolation(tmp_path):
    rows=[]
    for session in ['home-a','home-b','home-c','home-d']:
        for code in ['battery','wire']:
            p=tmp_path/f'{session}-{code}'; p.write_bytes(f'{session}-{code}'.encode())
            rows.append({'session':session,'barcode':code,'image':str(p)})
    train,val,classes=split_sessions(rows)
    assert not set(r['session'] for r in train)&set(r['session'] for r in val)
    assert classes==['battery','wire']

def test_single_session_rejected():
    with pytest.raises(ValueError): split_sessions([{'session':'a','barcode':x} for x in ['1','2']])

def test_duplicate_image_leak_rejected(tmp_path):
    path=tmp_path/'same'; path.write_bytes(b'same')
    rows=[{'session':s,'barcode':c,'image':str(path)} for s in ['a','b'] for c in ['1','2']]
    with pytest.raises(ValueError,match='Одинаковые'): split_sessions(rows)
