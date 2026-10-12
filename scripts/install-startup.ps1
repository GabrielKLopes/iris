$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "Virtual environment not found: $pythonw" }

$shell = New-Object -ComObject WScript.Shell

function New-IrisShortcut([string]$Path, [string]$Arguments, [string]$Description) {
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = $Description
    $shortcut.IconLocation = (Join-Path $root 'assets\iris.ico')
    $shortcut.Save()
    Write-Host "Shortcut: $Path"
}

$programs = [Environment]::GetFolderPath('Programs')
$desktop = [Environment]::GetFolderPath('Desktop')
$startup = [Environment]::GetFolderPath('Startup')

New-IrisShortcut (Join-Path $desktop 'Iris.lnk') '-m iris' 'Open Iris'
New-IrisShortcut (Join-Path $programs 'Iris.lnk') '-m iris' 'Open Iris'
New-IrisShortcut (Join-Path $startup 'Iris.lnk') '-m iris --hidden' 'Iris listens for her name in the background'

$legacy = Join-Path $startup 'Iris Listener.lnk'
if (Test-Path $legacy) { Remove-Item $legacy; Write-Host "Removed legacy listener shortcut" }
