$ErrorActionPreference = 'Stop'
python -m PyInstaller --noconfirm --clean --windowed --name pikkaBPE --icon pikkabpe/assets/app.ico --add-data "pikkabpe/assets;pikkabpe/assets" --exclude-module torch --exclude-module torchvision launch.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
Compress-Archive -Path dist\pikkaBPE -DestinationPath dist\pikkaBPE-windows-x64.zip -Force
$digest = (Get-FileHash dist\pikkaBPE-windows-x64.zip -Algorithm SHA256).Hash.ToLower()
"$digest  pikkaBPE-windows-x64.zip" | Set-Content dist\SHA256SUMS.txt -Encoding ascii
