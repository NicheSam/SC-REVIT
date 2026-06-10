$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "SC REVIT: update Revit addin" -ForegroundColor Cyan
Write-Host "Project root: $root"

$revitProcess = Get-Process -Name "Revit" -ErrorAction SilentlyContinue
if ($revitProcess) {
  Write-Host ""
  Write-Host "Revit is currently running." -ForegroundColor Yellow
  Write-Host "This script updates the DLL used on the next Revit startup. A running Revit session will not hot-reload the addin."
}

Write-Host ""
Write-Host "[1/3] Build Revit DLL..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "revit_addin\build.ps1")

Write-Host ""
Write-Host "[2/3] Update AppData deployment DLL and .addin manifest..."
python (Join-Path $root "addin_installer.py")

Write-Host ""
Write-Host "[3/3] Verify manifest points to the latest DLL..."
$addinPath = Join-Path $env:APPDATA "Autodesk\Revit\Addins\2024\RfaMetadataAddin.addin"
[xml]$addinXml = Get-Content -LiteralPath $addinPath -Encoding UTF8
$assemblyPath = @($addinXml.RevitAddIns.AddIn | ForEach-Object { $_.Assembly } | Select-Object -Unique)[0]
$sourceDll = Join-Path $root "revit_addin\bin\RfaMetadataAddin.dll"
$sourceHash = (Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash
$deployHash = (Get-FileHash -LiteralPath $assemblyPath -Algorithm SHA256).Hash

if ($sourceHash -ne $deployHash) {
  throw "Deploy DLL hash does not match source DLL.`nSource: $sourceDll`nDeploy: $assemblyPath"
}

Write-Host "Manifest: $addinPath"
Write-Host "Assembly: $assemblyPath"
Write-Host "Hash: $deployHash"
Write-Host ""
Write-Host "Done: manifest points to the latest DLL." -ForegroundColor Green

if ($revitProcess) {
  Write-Host "Restart Revit to load this updated addin." -ForegroundColor Yellow
}
