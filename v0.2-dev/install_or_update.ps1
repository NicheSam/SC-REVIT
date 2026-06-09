$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "SC REVIT: install / update" -ForegroundColor Cyan
Write-Host "Project root: $root"

$revitProcess = Get-Process -Name "Revit" -ErrorAction SilentlyContinue
if ($revitProcess) {
  Write-Host ""
  Write-Host "Revit is currently running." -ForegroundColor Yellow
  Write-Host "Revit addin DLL changes require restarting Revit."
  Write-Host "GUI and project files will still be updated."
}

Write-Host ""
Write-Host "[1/3] Build Revit addin DLL..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "revit_addin\build.ps1")

Write-Host ""
Write-Host "[2/3] Build GUI executable..."
$runningGui = Get-Process -Name "RevitFamilyClassifier" -ErrorAction SilentlyContinue
if ($runningGui) {
  Write-Host "Closing running GUI to avoid locked files..."
  $runningGui | Stop-Process -Force
}
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "build_gui_exe.ps1")

Write-Host ""
Write-Host "[3/3] Install / update Revit addin manifest..."
python (Join-Path $root "addin_installer.py")

$addinPath = Join-Path $env:APPDATA "Autodesk\Revit\Addins\2024\RfaMetadataAddin.addin"
[xml]$addinXml = Get-Content -LiteralPath $addinPath -Encoding UTF8
$assemblyPath = @($addinXml.RevitAddIns.AddIn | ForEach-Object { $_.Assembly } | Select-Object -Unique)[0]
$sourceDll = Join-Path $root "revit_addin\bin\RfaMetadataAddin.dll"
$sourceHash = (Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash
$deployHash = (Get-FileHash -LiteralPath $assemblyPath -Algorithm SHA256).Hash
if ($sourceHash -ne $deployHash) {
  throw "Deploy DLL hash does not match source DLL.`nSource: $sourceDll`nDeploy: $assemblyPath"
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Manifest: $addinPath"
Write-Host "Assembly: $assemblyPath"
if ($revitProcess) {
  Write-Host "Restart Revit to load the updated addin." -ForegroundColor Yellow
} else {
  Write-Host "Open Revit 2024 and use the SC Revit ribbon tab."
}
