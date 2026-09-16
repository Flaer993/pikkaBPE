import binascii
import zipfile
import pytest
from pikkabpe.serial_link import packet
from pikkabpe.updates import safe_extract,version

def test_crc_and_range():
    body,crc=packet(3,12.25,-30).strip().split(b'*')
    assert body==b'P1,3,1225,-3000'
    assert int(crc,16)==binascii.crc_hqx(body,0xffff)
    with pytest.raises(ValueError): packet(1,91,0)

@pytest.mark.parametrize('name',['../escape.exe','C:/escape.exe','/absolute.exe','..\\escape.exe'])
def test_zip_slip_rejected(tmp_path,name):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z: z.writestr(name,'bad')
    with pytest.raises(ValueError): safe_extract(archive,tmp_path/'unpack')

def test_version_order():
    assert version('v0.10.0')>version('0.9.0')
    with pytest.raises(ValueError): version('v0.1.0-rc1')
