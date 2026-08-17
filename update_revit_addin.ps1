$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$installer = Join-Path $root "install_or_update.ps1"

Write-Host "SC REVIT: full DLL + GUI update" -ForegroundColor Cyan
Write-Host "Compatibility entry point: $($MyInvocation.MyCommand.Name)"
Write-Host "Canonical installer: $installer"

& powershell -NoProfile -ExecutionPolicy Bypass -File $installer
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
