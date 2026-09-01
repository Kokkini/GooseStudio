$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $Root "build\windows-sidecar-build"
$Stage = Join-Path $Root "build\windows-sidecar"
$Venv = Join-Path $BuildRoot "venv"
$Python = Join-Path $Venv "Scripts\python.exe"

Remove-Item $BuildRoot, $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item $BuildRoot, $Stage -ItemType Directory -Force | Out-Null

python -m venv $Venv
# Keep the release build on public PyPI. The workstation may have a system-wide
# extra index configured for unrelated CUDA package builds; inheriting it makes
# this small sidecar build wait through unreachable-index retries.
& $Python -m pip config --site set global.index-url "https://pypi.org/simple"
& $Python -m pip config --site set global.extra-index-url ""
& $Python -m pip install --disable-pip-version-check -r (Join-Path $Root "requirements-setup.txt")

$Common = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--workpath", (Join-Path $BuildRoot "work"),
    "--specpath", (Join-Path $BuildRoot "spec")
)

& $Python -m PyInstaller @Common `
    --name "goose-studio-setup" `
    --distpath (Join-Path $BuildRoot "dist") `
    (Join-Path $Root "scripts\install.py")

& $Python -m PyInstaller @Common `
    --name "modal-cli" `
    --distpath (Join-Path $BuildRoot "dist") `
    --collect-all modal `
    --collect-all modal_proto `
    --collect-all modal_version `
    --collect-all synchronicity `
    (Join-Path $Root "scripts\modal-cli.py")

$Directories = @("setup", "modal-cli", "app\modal", "app\assets", "app\tools")
$Directories | ForEach-Object { New-Item (Join-Path $Stage $_) -ItemType Directory -Force | Out-Null }
Copy-Item -Path (Join-Path $BuildRoot "dist\goose-studio-setup\*") -Destination (Join-Path $Stage "setup") -Recurse
Copy-Item -Path (Join-Path $BuildRoot "dist\modal-cli\*") -Destination (Join-Path $Stage "modal-cli") -Recurse
Copy-Item -Path @(
    (Join-Path $Root "modal\bootstrap.py"),
    (Join-Path $Root "modal\goose_studio_executor.py"),
    (Join-Path $Root "scripts\download_hunyuan3d_assets.py")
) -Destination (Join-Path $Stage "app\modal")
Copy-Item -Path @((Join-Path $Root "assets\models.json"), (Join-Path $Root "assets\allowed-node-classes.json")) -Destination (Join-Path $Stage "app\assets")
Copy-Item -Path (Join-Path $Root "tools\voxelize_glb.py") -Destination (Join-Path $Stage "app\tools")

Write-Host "Windows sidecar staged at $Stage"
