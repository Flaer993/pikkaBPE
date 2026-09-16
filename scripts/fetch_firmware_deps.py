"""Fetch fixed upstream commits; no unpinned source is used by firmware builds."""
import concurrent.futures
import json
import os
from pathlib import Path
import urllib.request
import zipfile
import hashlib
import io

DEPENDENCIES={
    'tinyusb': ('hathach/tinyusb','7b787daa2ae461d7fdd01a6367be51e0e025b5db'),
    'device': ('STMicroelectronics/cmsis-device-h5','884b8dc78e41cbfca008363342b17f4a9e8641f7'),
    'hal': ('STMicroelectronics/stm32h5xx-hal-driver','ba20038d938ecc31399e49d60fa6bcc8e82db5da'),
    'cmsis': ('ARM-software/CMSIS_5','55b19837f5703e418ca37894d5745b1dc05e4c91'),
}
HASHES={
 'tinyusb':'4c2483551cc91784bd2863e69fcec7ffca96d34181b22ac1ac4e6543043d2203',
 'device':'f9d3677f663a53e85538d24b9ba6f1737f37a53c386576daab980aa692edb1e4',
 'hal':'879b2b92f7f54f86e7382d1973d81e7e28a3359f795d5223e6c77c451617798e',
 'cmsis':'cd7b9746a997cabd221cf007338636c41e4e66bfd5475449c967c0413221ee02',
}

def fetch(item,root):
    name,(repo,commit)=item
    dest=root/name
    stamp=dest/'.pikka-commit'
    if stamp.exists() and stamp.read_text()==commit: return {'name':name,'commit':commit,'cached':True}
    if dest.exists(): raise RuntimeError(f'{dest} exists with different or incomplete contents')
    url=f'https://codeload.github.com/{repo}/zip/{commit}'
    with urllib.request.urlopen(url,timeout=120) as response: data=response.read()
    if hashlib.sha256(data).hexdigest()!=HASHES[name]: raise RuntimeError('Dependency checksum mismatch: '+name)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            parts=Path(entry.filename).parts[1:]
            if not parts: continue
            target=dest.joinpath(*parts).resolve()
            if not target.is_relative_to(dest.resolve()): raise RuntimeError('Invalid archive path')
            if entry.is_dir(): target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(archive.read(entry))
    stamp.write_text(commit)
    return {'name':name,'repo':repo,'commit':commit,'archive_sha256':hashlib.sha256(data).hexdigest()}

if __name__=='__main__':
    root=Path(os.environ.get('PIKKABPE_DEPS',Path(__file__).resolve().parents[1]/'build'/'firmware-deps'))
    root.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        reports=list(pool.map(lambda item:fetch(item,root),DEPENDENCIES.items()))
    (root/'fetch-report.json').write_text(json.dumps(reports,indent=2))
    print(json.dumps(reports,indent=2))
