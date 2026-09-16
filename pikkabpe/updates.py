"""Private GitHub Releases via locally authenticated gh; credentials never stored here."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile
from . import __version__

REPO='Flaer993/pikkaBPE'


def gh():
    path=shutil.which('gh')
    fallback=Path('D:/pikkaBPE-tools/gh/bin/gh.exe')
    if not path and fallback.exists(): path=str(fallback)
    if not path: raise RuntimeError('Установите GitHub CLI и выполните gh auth login для доступа к приватному репозиторию.')
    return path


def command(args):
    result=subprocess.run([gh(),*args],capture_output=True,text=True,encoding='utf-8',timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode: raise RuntimeError(result.stderr.strip() or 'Ошибка GitHub CLI')
    return result.stdout


def version(tag):
    match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)',tag)
    if not match: raise ValueError('Неподдерживаемая версия')
    return tuple(map(int,match.groups()))


def latest():
    releases=json.loads(command(['api',f'repos/{REPO}/releases']))
    candidates=[]
    for release in releases:
        if release['draft'] or release['prerelease']: continue
        try:
            if version(release['tag_name'])>version(__version__): candidates.append(release)
        except ValueError: continue
    return max(candidates,key=lambda r:version(r['tag_name'])) if candidates else None


def safe_extract(archive,destination):
    destination=Path(destination).resolve()
    with zipfile.ZipFile(archive) as z:
        if sum(info.file_size for info in z.infolist())>2*1024**3: raise ValueError('Архив превышает лимит 2 ГБ')
        for info in z.infolist():
            name=info.filename.replace('\\','/')
            parts=PurePosixPath(name).parts
            if not parts or '..' in parts or ':' in name or name.startswith('/') or ((info.external_attr>>16)&0o170000)==0o120000:
                raise ValueError('Недопустимый путь в архиве')
            target=(destination/name).resolve()
            if not target.is_relative_to(destination): raise ValueError('Путь вне каталога обновления')
        z.extractall(destination)


def stage(release,root):
    tag=release['tag_name']; version(tag)
    folder=Path(tempfile.mkdtemp(prefix=tag+'-',dir=root))
    command(['release','download',tag,'--repo',REPO,'--pattern','pikkaBPE-windows-x64.zip','--pattern','SHA256SUMS.txt','--dir',str(folder)])
    archive=folder/'pikkaBPE-windows-x64.zip'
    checks=(folder/'SHA256SUMS.txt').read_text(encoding='utf-8-sig')
    expected=None
    for line in checks.splitlines():
        fields=line.split()
        if len(fields)==2 and fields[1].lstrip('*')==archive.name: expected=fields[0].lower()
    if not expected or hashlib.sha256(archive.read_bytes()).hexdigest()!=expected: raise ValueError('Контрольная сумма обновления не совпадает')
    safe_extract(archive,folder/'unpacked')
    path=folder/'unpacked'/'pikkaBPE'
    if not (path/'pikkaBPE.exe').is_file(): raise ValueError('В архиве нет клиента')
    return path


def install(source,target,pid):
    source=Path(source).resolve(); target=Path(target).resolve()
    if source==target or target in source.parents or source in target.parents: raise ValueError('Каталоги установки пересекаются')
    if not (source/'pikkaBPE.exe').is_file() or not (target/'pikkaBPE.exe').is_file(): raise ValueError('Не найден исполняемый файл клиента')
    backup=target.with_name(target.name+'.backup-'+next(tempfile._get_candidate_names()))
    def quote(value): return "'"+str(value).replace("'","''")+"'"
    script=source.parent/'install.ps1'
    script.write_text(f'''$ErrorActionPreference = 'Stop'
$processToWait = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue
if ($processToWait) {{ $processToWait.WaitForExit() }}
$installTarget = {quote(target)}
$installSource = {quote(source)}
$rollbackPath = {quote(backup)}
try {{
    Move-Item -LiteralPath $installTarget -Destination $rollbackPath
    Copy-Item -LiteralPath $installSource -Destination $installTarget -Recurse
    Start-Process -FilePath (Join-Path $installTarget 'pikkaBPE.exe') -WindowStyle Hidden
}} catch {{
    if (Test-Path -LiteralPath $rollbackPath) {{
        if (Test-Path -LiteralPath $installTarget) {{
            Move-Item -LiteralPath $installTarget -Destination ($installTarget + '.failed-' + [guid]::NewGuid().ToString('N'))
        }}
        Move-Item -LiteralPath $rollbackPath -Destination $installTarget
    }}
    $_ | Out-File -LiteralPath (Join-Path {quote(source.parent)} 'install-error.txt')
}}
''',encoding='utf-8-sig')
    subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',str(script)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=str(source.parent))
