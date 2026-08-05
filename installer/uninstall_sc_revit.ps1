param(
  [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "SC_REVIT"),
  [switch]$RemoveRuntimeData,
  [switch]$SkipUserEnvironmentUpdate,
  [switch]$SkipProcessCheck
)

$ErrorActionPreference = "Stop"
if (-not $SkipProcessCheck -and (Get-Process -Name "Revit" -ErrorAction SilentlyContinue)) {
  throw "Close Revit before uninstalling SC REVIT."
}

$addinPath = Join-Path $env:APPDATA "Autodesk\Revit\Addins\2024\RfaMetadataAddin.addin"
if (Test-Path -LiteralPath $addinPath) {
  [xml]$addinXml = Get-Content -LiteralPath $addinPath -Encoding UTF8
  $owned = @($addinXml.RevitAddIns.AddIn | Where-Object {
    $_.AddInId -eq "6DCCB516-9F7B-4AF4-90D4-6BE5B8B9B1D8"
  }).Count -gt 0
  if (-not $owned) {
    throw "The existing RfaMetadataAddin.addin is not owned by this SC REVIT installation."
  }
  Set-ItemProperty -LiteralPath $addinPath -Name IsReadOnly -Value $false
  Remove-Item -LiteralPath $addinPath -Force
}

$deployDir = Join-Path $env:LOCALAPPDATA "SCRevit\Revit2024"
if (Test-Path -LiteralPath $deployDir) {
  Remove-Item -LiteralPath $deployDir -Recurse -Force
}
if (Test-Path -LiteralPath $InstallRoot) {
  Remove-Item -LiteralPath $InstallRoot -Recurse -Force
}
if (-not $SkipUserEnvironmentUpdate) {
  [Environment]::SetEnvironmentVariable("SC_REVIT_HOME", $null, "User")
}

if ($RemoveRuntimeData) {
  $runtimeDir = Join-Path $env:LOCALAPPDATA "RevitFamilyClassifier"
  if (Test-Path -LiteralPath $runtimeDir) {
    Remove-Item -LiteralPath $runtimeDir -Recurse -Force
  }
}

Write-Host "SC REVIT was uninstalled." -ForegroundColor Green
if (-not $RemoveRuntimeData) {
  Write-Host "Runtime diagnostics were preserved under LocalAppData\RevitFamilyClassifier."
}
