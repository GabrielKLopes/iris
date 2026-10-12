$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -e ".[build]"
if ($LASTEXITCODE -ne 0) { throw "Failed to install dependencies" }

Push-Location frontend
if (-not (Test-Path node_modules)) { npm install }
npm run build
$frontendExit = $LASTEXITCODE
Pop-Location
if ($frontendExit -ne 0) { throw "Frontend build failed" }

function Build-Exe($name, $entry, $extraArgs) {
    & .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed `
        --name $name --paths src @extraArgs $entry 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for $name" }
}

$voice = @('--collect-all', 'vosk', '--collect-all', 'sounddevice')
$app = @(
    '--collect-all', 'webview',
    '--hidden-import', 'pyttsx3.drivers.sapi5',
    '--hidden-import', 'keyring.backends.Windows',
    '--add-data', 'src\iris\agent\prompts;iris\agent\prompts',
    '--add-data', 'src\iris\ui\web;iris\ui\web'
) + $voice

Build-Exe 'iris' 'src\iris\__main__.py' $app
Build-Exe 'iris-listener' 'src\iris\listener.py' $voice

Write-Host "Executables: $root\dist\iris.exe and $root\dist\iris-listener.exe"
