$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BuildDir = Join-Path $Root "dist\windows\build"
$PackageDir = Join-Path $BuildDir "VideoNotes-windows-x86_64"
$PyAppVersion = "0.29.0"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Не найден Python 3.13+" }
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "Не найден Cargo. Установите Rust: https://rustup.rs" }

Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$BuildDir\wheel", $PackageDir | Out-Null

Push-Location $Root
python -c "from setuptools.build_meta import build_wheel; print(build_wheel(r'$BuildDir\wheel', {}))"
Pop-Location
$Wheel = Get-ChildItem "$BuildDir\wheel\videonotes-*.whl" | Select-Object -First 1
if ($null -eq $Wheel) { throw "Wheel VideoNotes не собран" }

$PyAppSource = Join-Path $BuildDir "pyapp-source"
New-Item -ItemType Directory -Force $PyAppSource | Out-Null
$Archive = Join-Path $BuildDir "pyapp-source.tar.gz"
Invoke-WebRequest "https://github.com/ofek/pyapp/releases/download/v$PyAppVersion/source.tar.gz" -OutFile $Archive
tar -xzf $Archive -C $PyAppSource --strip-components=1
Copy-Item $Wheel.FullName (Join-Path $PyAppSource $Wheel.Name)

Push-Location $PyAppSource
$env:PYAPP_PROJECT_PATH = $Wheel.Name
$env:PYAPP_EXEC_MODULE = "videonotes.desktop"
$env:PYAPP_IS_GUI = "1"
$env:PYAPP_PYTHON_VERSION = "3.13"
# PyPI отдаёт для Windows CPU-сборку torch; берём CUDA-билд из индекса PyTorch
$env:PYAPP_PIP_EXTRA_ARGS = "--extra-index-url https://download.pytorch.org/whl/cu130"
cargo build --release
Pop-Location

Copy-Item "$PyAppSource\target\release\pyapp.exe" "$PackageDir\videonotes.exe"
Copy-Item "$Root\scripts\windows\install-pyapp.ps1" "$PackageDir\install.ps1"
Copy-Item "$Root\scripts\windows\README-pyapp.md" "$PackageDir\README.md"

New-Item -ItemType Directory -Force "$Root\dist" | Out-Null
Compress-Archive -Path $PackageDir -DestinationPath "$Root\dist\VideoNotes-windows-x86_64.zip" -Force
Write-Host "Готово: $Root\dist\VideoNotes-windows-x86_64.zip"
