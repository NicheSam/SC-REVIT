param(
  [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "SC_REVIT"),
  [switch]$SkipUserEnvironmentUpdate
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$payloadRoot = Join-Path $scriptRoot "payload"
$releaseManifestPath = Join-Path $scriptRoot "release_manifest.json"

Write-Host "SC REVIT installer" -ForegroundColor Cyan
Write-Host "Install root: $InstallRoot"

if (!(Test-Path -LiteralPath $payloadRoot)) {
  throw "Payload folder was not found: $payloadRoot"
}
if (!(Test-Path -LiteralPath $releaseManifestPath)) {
  throw "Release manifest was not found: $releaseManifestPath"
}

Write-Host "[0/4] Verify release payload..."
$releaseManifest = Get-Content -LiteralPath $releaseManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$scriptRootFull = [System.IO.Path]::GetFullPath($scriptRoot)
$scriptRootPrefix = $scriptRootFull.TrimEnd('\') + '\'
foreach ($file in $releaseManifest.files) {
  $candidate = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot $file.path))
  if (-not $candidate.StartsWith($scriptRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Release manifest path escapes the package root: $($file.path)"
  }
  if (!(Test-Path -LiteralPath $candidate -PathType Leaf)) {
    throw "Release payload file is missing: $($file.path)"
  }
  $actualHash = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash
  if ($actualHash -ne $file.sha256) {
    throw "Release payload hash mismatch: $($file.path)"
  }
}

$revitProcess = Get-Process -Name "Revit" -ErrorAction SilentlyContinue
if ($revitProcess) {
  Write-Host ""
  Write-Host "Revit is currently running." -ForegroundColor Yellow
  Write-Host "Close and restart Revit after installation to load SC REVIT."
}

Write-Host ""
Write-Host "[1/4] Copy application files..."
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$payloadItems = Get-ChildItem -LiteralPath $payloadRoot -Force
if ($payloadItems.Count -eq 0) {
  throw "Payload folder is empty: $payloadRoot"
}
foreach ($item in $payloadItems) {
  Copy-Item -LiteralPath $item.FullName -Destination $InstallRoot -Recurse -Force
}

$guiExe = Join-Path $InstallRoot "dist\RevitFamilyClassifier\RevitFamilyClassifier.exe"
$sourceDll = Join-Path $InstallRoot "revit_addin\bin\RfaMetadataAddin.dll"
if (!(Test-Path -LiteralPath $guiExe)) {
  throw "GUI executable was not found after copy: $guiExe"
}
if (!(Test-Path -LiteralPath $sourceDll)) {
  throw "Revit addin DLL was not found after copy: $sourceDll"
}

Write-Host "[2/4] Prepare Revit addin DLL..."
$deployDir = Join-Path $env:LOCALAPPDATA "RfaMetadataAddin"
New-Item -ItemType Directory -Force -Path $deployDir | Out-Null
$hash = (Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash.ToLower().Substring(0, 12)
$deployDll = Join-Path $deployDir ("RfaMetadataAddin." + $hash + ".dll")
Copy-Item -LiteralPath $sourceDll -Destination $deployDll -Force
[System.IO.File]::WriteAllText(
  (Join-Path $deployDir "sc_revit_home.txt"),
  $InstallRoot,
  [System.Text.UTF8Encoding]::new($false)
)
if (-not $SkipUserEnvironmentUpdate) {
  [Environment]::SetEnvironmentVariable("SC_REVIT_HOME", $InstallRoot, "User")
}

Write-Host "[3/4] Write Revit 2024 addin manifest..."
$addinDir = Join-Path $env:APPDATA "Autodesk\Revit\Addins\2024"
New-Item -ItemType Directory -Force -Path $addinDir | Out-Null
$addinPath = Join-Path $addinDir "RfaMetadataAddin.addin"
if (Test-Path -LiteralPath $addinPath) {
  Set-ItemProperty -LiteralPath $addinPath -Name IsReadOnly -Value $false
}
$manifest = @"
<?xml version="1.0" encoding="utf-8" standalone="no"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>RfaMetadataListener</Name>
    <Assembly>$deployDll</Assembly>
    <AddInId>6DCCB516-9F7B-4AF4-90D4-6BE5B8B9B1D8</AddInId>
    <FullClassName>RfaMetadataAddin.RfaMetadataBootstrapApplication</FullClassName>
    <VendorId>DEX</VendorId>
    <VendorDescription>Background queue listener for SC REVIT requests</VendorDescription>
  </AddIn>
  <AddIn Type="Command">
    <Name>RfaMetadataAddin</Name>
    <Assembly>$deployDll</Assembly>
    <AddInId>1C9F98C5-50C8-4C1E-9D1F-7BEAD9A6762C</AddInId>
    <FullClassName>RfaMetadataAddin.RfaMetadataCommand</FullClassName>
    <VendorId>DEX</VendorId>
    <VendorDescription>SC REVIT command entry</VendorDescription>
  </AddIn>
  <AddIn Type="Command">
    <Name>SC Drainage Runtime Self Test</Name>
    <Assembly>$deployDll</Assembly>
    <AddInId>A60D2AB6-D860-43D0-91D6-82F4EAC7216A</AddInId>
    <FullClassName>RfaMetadataAddin.DrainageRuntimeSelfTestCommand</FullClassName>
    <VendorId>DEX</VendorId>
    <VendorDescription>Development-only runtime verification for SC drainage tools</VendorDescription>
  </AddIn>
</RevitAddIns>
"@
[System.IO.File]::WriteAllText($addinPath, $manifest, [System.Text.UTF8Encoding]::new($false))
Set-ItemProperty -LiteralPath $addinPath -Name IsReadOnly -Value $true

Write-Host "[4/4] Verify installation..."
[xml]$addinXml = Get-Content -LiteralPath $addinPath -Encoding UTF8
$assemblyPath = @($addinXml.RevitAddIns.AddIn | ForEach-Object { $_.Assembly } | Select-Object -Unique)[0]
if ($assemblyPath -ne $deployDll) {
  throw "Manifest assembly path does not match deployed DLL."
}
if (!(Test-Path -LiteralPath $assemblyPath)) {
  throw "Manifest points to a DLL that does not exist: $assemblyPath"
}
$sourceHash = (Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash
$deployHash = (Get-FileHash -LiteralPath $assemblyPath -Algorithm SHA256).Hash
if ($sourceHash -ne $deployHash) {
  throw "Installed Revit DLL hash does not match the release payload."
}

Write-Host ""
Write-Host "Installed SC REVIT successfully." -ForegroundColor Green
Write-Host "Manifest: $addinPath"
Write-Host "Assembly: $deployDll"
Write-Host "GUI: $guiExe"
Write-Host "Version: $($releaseManifest.version)"
Write-Host ""
Write-Host "Restart Revit 2024, then open the SC REVIT ribbon tab."
