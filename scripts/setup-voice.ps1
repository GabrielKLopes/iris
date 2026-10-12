$ErrorActionPreference = 'Stop'
$modelName = 'vosk-model-small-pt-0.3'
$modelsDir = Join-Path $env:LOCALAPPDATA 'iris\models'
$target = Join-Path $modelsDir $modelName

if (Test-Path $target) {
    Write-Host "Model already installed: $target"
    exit 0
}

New-Item -ItemType Directory -Force $modelsDir | Out-Null
$zip = Join-Path $env:TEMP "$modelName.zip"
Write-Host "Downloading $modelName..."
Invoke-WebRequest -Uri "https://alphacephei.com/vosk/models/$modelName.zip" -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $modelsDir -Force
Remove-Item $zip
Write-Host "Model installed: $target"
