param(
  [switch]$GuiOnly
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Assert-NativeStepSucceeded {
  param(
    [string]$StepName
  )

  if ($LASTEXITCODE -ne 0) {
    throw "$StepName failed with exit code $LASTEXITCODE."
  }
}

Write-Host "SC REVIT: install / update" -ForegroundColor Cyan
Write-Host "Development root: $root"

$revitProcess = Get-Process -Name "Revit" -ErrorAction SilentlyContinue
if ($revitProcess -and -not $GuiOnly) {
  throw "Revit is currently running. Close Revit before a full DLL + GUI update, or use -GuiOnly for a GUI hot update."
}

$configuredInstallRoot = [Environment]::GetEnvironmentVariable("SC_REVIT_HOME", "User")
$installRoot = if ([string]::IsNullOrWhiteSpace($configuredInstallRoot)) {
  Join-Path $env:LOCALAPPDATA "SC_REVIT"
} else {
  $configuredInstallRoot
}
$sourceGuiDir = Join-Path $root "dist\RevitFamilyClassifier"
$deployGuiDir = Join-Path $installRoot "dist\RevitFamilyClassifier"
$sourceGuiExe = Join-Path $sourceGuiDir "RevitFamilyClassifier.exe"
$deployGuiExe = Join-Path $deployGuiDir "RevitFamilyClassifier.exe"

if (-not $GuiOnly) {
  Write-Host ""
  Write-Host "[1/4] Build Revit addin DLL..."
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "revit_addin\build.ps1")
  Assert-NativeStepSucceeded "Revit addin build"
}

Write-Host ""
Write-Host $(if ($GuiOnly) { "[1/2] Build GUI executable..." } else { "[2/4] Build GUI executable..." })
$runningGui = Get-Process -Name "RevitFamilyClassifier" -ErrorAction SilentlyContinue
$restartGuiAfterUpdate = [bool]$runningGui
if ($runningGui) {
  Write-Host "Closing running GUI to avoid locked files..."
  $runningGui | Stop-Process -Force
  $runningGui | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
}
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "build_gui_exe.ps1")
Assert-NativeStepSucceeded "GUI build"

Write-Host ""
Write-Host $(if ($GuiOnly) { "[2/2] Deploy GUI executable..." } else { "[3/4] Deploy GUI executable..." })
if (-not (Test-Path -LiteralPath $sourceGuiExe)) {
  throw "Built GUI executable was not found: $sourceGuiExe"
}
New-Item -ItemType Directory -Force -Path $deployGuiDir | Out-Null
foreach ($item in Get-ChildItem -LiteralPath $sourceGuiDir -Force) {
  Copy-Item -LiteralPath $item.FullName -Destination $deployGuiDir -Recurse -Force
}
$sourceGuiHash = (Get-FileHash -LiteralPath $sourceGuiExe -Algorithm SHA256).Hash
$deployGuiHash = (Get-FileHash -LiteralPath $deployGuiExe -Algorithm SHA256).Hash
if ($sourceGuiHash -ne $deployGuiHash) {
  throw "Deploy GUI hash does not match source GUI.`nSource: $sourceGuiExe`nDeploy: $deployGuiExe"
}
[Environment]::SetEnvironmentVariable("SC_REVIT_HOME", $installRoot, "User")
$env:SC_REVIT_HOME = $installRoot

if (-not $GuiOnly) {
  Write-Host ""
  Write-Host "[4/4] Install / update Revit addin manifest..."
  python (Join-Path $root "addin_installer.py") --force
  Assert-NativeStepSucceeded "Revit addin manifest installation"

  $addinPath = Join-Path $env:APPDATA "Autodesk\Revit\Addins\2024\RfaMetadataAddin.addin"
  [xml]$addinXml = Get-Content -LiteralPath $addinPath -Encoding UTF8
  $assemblyPaths = @($addinXml.RevitAddIns.AddIn | ForEach-Object { $_.Assembly } | Select-Object -Unique)
  if (@($addinXml.RevitAddIns.AddIn).Count -ne 1 -or $assemblyPaths.Count -ne 1) {
    throw "Revit manifest must contain exactly one SC REVIT Application entry."
  }
  $assemblyPath = $assemblyPaths[0]
  $sourceDll = Join-Path $root "revit_addin\bin\RfaMetadataAddin.dll"
  $sourceHash = (Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash
  $deployHash = (Get-FileHash -LiteralPath $assemblyPath -Algorithm SHA256).Hash
  if ($sourceHash -ne $deployHash) {
    throw "Deploy DLL hash does not match source DLL.`nSource: $sourceDll`nDeploy: $assemblyPath"
  }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "GUI: $deployGuiExe"
Write-Host "GUI hash: $deployGuiHash"
if (-not $GuiOnly) {
  Write-Host "Manifest: $addinPath"
  Write-Host "Assembly: $assemblyPath"
  Write-Host "Open Revit 2024 and use the SC Revit ribbon tab."
}
if ($restartGuiAfterUpdate) {
  Start-Process -FilePath $deployGuiExe -WorkingDirectory $deployGuiDir
  Write-Host "Restarted the updated SC REVIT GUI."
}
