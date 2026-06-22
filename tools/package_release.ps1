param(
  [string]$Version = ""
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $toolRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($Version)) {
  $versionPath = Join-Path $root "VERSION.txt"
  if (Test-Path -LiteralPath $versionPath) {
    $Version = (Get-Content -LiteralPath $versionPath -First 1).Trim()
  }
}
if ([string]::IsNullOrWhiteSpace($Version)) {
  $Version = "dev"
}
$safeVersion = ($Version -replace '[^A-Za-z0-9._-]', '_')

Write-Host "SC REVIT release packager" -ForegroundColor Cyan
Write-Host "Version: $Version"

Write-Host ""
Write-Host "[1/5] Build Revit addin DLL..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "revit_addin\build.ps1")

Write-Host ""
Write-Host "[2/5] Build GUI executable..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "build_gui_exe.ps1")

$releaseRoot = Join-Path $root "release"
$packageRoot = Join-Path $releaseRoot ("SC_REVIT_" + $safeVersion + "_installer")
$payloadRoot = Join-Path $packageRoot "payload"
$zipPath = Join-Path $releaseRoot ("SC_REVIT_" + $safeVersion + "_installer.zip")

Write-Host ""
Write-Host "[3/5] Prepare release folder..."
if (Test-Path -LiteralPath $packageRoot) {
  Remove-Item -LiteralPath $packageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $payloadRoot | Out-Null
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

Copy-Item -LiteralPath (Join-Path $root "installer\Install_SC_REVIT.bat") -Destination $packageRoot -Force
Copy-Item -LiteralPath (Join-Path $root "installer\install_sc_revit.ps1") -Destination $packageRoot -Force

Write-Host "[4/5] Copy payload..."
New-Item -ItemType Directory -Force -Path (Join-Path $payloadRoot "dist") | Out-Null
Copy-Item -LiteralPath (Join-Path $root "dist\RevitFamilyClassifier") -Destination (Join-Path $payloadRoot "dist\RevitFamilyClassifier") -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $payloadRoot "revit_addin\bin") | Out-Null
Copy-Item -LiteralPath (Join-Path $root "revit_addin\bin\RfaMetadataAddin.dll") -Destination (Join-Path $payloadRoot "revit_addin\bin\RfaMetadataAddin.dll") -Force
Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination (Join-Path $payloadRoot "README.md") -Force
Copy-Item -LiteralPath (Join-Path $root "VERSION.txt") -Destination (Join-Path $payloadRoot "VERSION.txt") -Force

Write-Host "[5/5] Create ZIP..."
if (Test-Path -LiteralPath $zipPath) {
  Remove-Item -LiteralPath $zipPath -Force
}
$packageItems = Get-ChildItem -LiteralPath $packageRoot -Force
Compress-Archive -LiteralPath $packageItems.FullName -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Release package ready:" -ForegroundColor Green
Write-Host $zipPath
