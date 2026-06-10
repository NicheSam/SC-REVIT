$ErrorActionPreference = "Stop"

$addinRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $addinRoot
$updateScript = Join-Path $projectRoot "update_revit_addin.ps1"

if (-not (Test-Path -LiteralPath $updateScript)) {
  throw "找不到新版部署腳本：$updateScript"
}

Write-Host "revit_addin\install.ps1 is a compatibility entrypoint. Running project-level update_revit_addin.ps1."
& powershell -NoProfile -ExecutionPolicy Bypass -File $updateScript
