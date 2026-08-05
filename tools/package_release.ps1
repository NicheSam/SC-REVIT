param(
  [string]$Version = "",
  [switch]$SkipAddinBuild,
  [string]$ExpectedAddinSha256 = ""
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $toolRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($Version)) {
  $versionPath = Join-Path $root "VERSION.txt"
  if (Test-Path -LiteralPath $versionPath) {
    $versionLine = Get-Content -LiteralPath $versionPath |
      Where-Object { $_ -match '^\s*Version\s*:' } |
      Select-Object -First 1
    if ($versionLine) {
      $Version = ($versionLine -replace '^\s*Version\s*:\s*', '').Trim()
    }
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
$addinDll = Join-Path $root "revit_addin\bin\RfaMetadataAddin.dll"
if ($SkipAddinBuild) {
  Write-Host "Using prebuilt Revit addin DLL."
}
else {
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "revit_addin\build.ps1")
  if ($LASTEXITCODE -ne 0) {
    throw "Revit addin build failed with exit code $LASTEXITCODE."
  }
}
if (!(Test-Path -LiteralPath $addinDll -PathType Leaf)) {
  throw "Revit addin DLL was not found: $addinDll"
}
$addinHash = (Get-FileHash -LiteralPath $addinDll -Algorithm SHA256).Hash
if (-not [string]::IsNullOrWhiteSpace($ExpectedAddinSha256) -and $addinHash -ne $ExpectedAddinSha256) {
  throw "Revit addin DLL hash does not match the required release snapshot."
}

Write-Host ""
Write-Host "[2/5] Build GUI executable..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "build_gui_exe.ps1")
if ($LASTEXITCODE -ne 0) {
  throw "GUI build failed with exit code $LASTEXITCODE."
}

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

$installerFiles = @(
  "Install_SC_REVIT.bat",
  "install_sc_revit.ps1",
  "Enable_SC_REVIT_Agent.bat",
  "Disable_SC_REVIT_Agent.bat",
  "Set_SC_REVIT_Agent.ps1",
  "Collect_SC_REVIT_Diagnostics.bat",
  "Collect_SC_REVIT_Diagnostics.ps1",
  "Uninstall_SC_REVIT.bat",
  "uninstall_sc_revit.ps1"
)
foreach ($installerFile in $installerFiles) {
  Copy-Item -LiteralPath (Join-Path $root ("installer\" + $installerFile)) -Destination $packageRoot -Force
}

Write-Host "[4/5] Copy payload..."
New-Item -ItemType Directory -Force -Path (Join-Path $payloadRoot "dist") | Out-Null
Copy-Item -LiteralPath (Join-Path $root "dist\RevitFamilyClassifier") -Destination (Join-Path $payloadRoot "dist\RevitFamilyClassifier") -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $payloadRoot "revit_addin\bin") | Out-Null
Copy-Item -LiteralPath (Join-Path $root "revit_addin\bin\RfaMetadataAddin.dll") -Destination (Join-Path $payloadRoot "revit_addin\bin\RfaMetadataAddin.dll") -Force
Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination (Join-Path $payloadRoot "README.md") -Force
Copy-Item -LiteralPath (Join-Path $root "VERSION.txt") -Destination (Join-Path $payloadRoot "VERSION.txt") -Force
$releaseNotesPath = Join-Path $root ("RELEASE_NOTES_" + $safeVersion + ".md")
if (Test-Path -LiteralPath $releaseNotesPath) {
  Copy-Item -LiteralPath $releaseNotesPath -Destination (Join-Path $payloadRoot (Split-Path -Leaf $releaseNotesPath)) -Force
}
$docsPath = Join-Path $root "docs"
if (Test-Path -LiteralPath $docsPath) {
  Copy-Item -LiteralPath $docsPath -Destination (Join-Path $payloadRoot "docs") -Recurse -Force
}

$payloadFiles = @(
  "payload/revit_addin/bin/RfaMetadataAddin.dll",
  "payload/dist/RevitFamilyClassifier/_internal/revit_addin/bin/RfaMetadataAddin.dll",
  "payload/dist/RevitFamilyClassifier/RevitFamilyClassifier.exe",
  "payload/VERSION.txt",
  "Install_SC_REVIT.bat",
  "install_sc_revit.ps1",
  "Enable_SC_REVIT_Agent.bat",
  "Disable_SC_REVIT_Agent.bat",
  "Set_SC_REVIT_Agent.ps1",
  "Collect_SC_REVIT_Diagnostics.bat",
  "Collect_SC_REVIT_Diagnostics.ps1",
  "Uninstall_SC_REVIT.bat",
  "uninstall_sc_revit.ps1"
)
$releaseFiles = @()
foreach ($relativePath in $payloadFiles) {
  $nativePath = Join-Path $packageRoot ($relativePath.Replace("/", "\"))
  if (!(Test-Path -LiteralPath $nativePath -PathType Leaf)) {
    throw "Release payload file is missing: $relativePath"
  }
  $releaseFiles += [ordered]@{
    path = $relativePath
    sha256 = (Get-FileHash -LiteralPath $nativePath -Algorithm SHA256).Hash
    size = (Get-Item -LiteralPath $nativePath).Length
  }
}
if (
  $releaseFiles[0].sha256 -ne $addinHash -or
  $releaseFiles[1].sha256 -ne $addinHash
) {
  throw "Packaged Revit DLL copies do not match the selected release DLL."
}
$releaseManifest = [ordered]@{
  version = $Version
  createdUtc = [DateTime]::UtcNow.ToString("o")
  files = $releaseFiles
}
[System.IO.File]::WriteAllText(
  (Join-Path $packageRoot "release_manifest.json"),
  ($releaseManifest | ConvertTo-Json -Depth 5),
  [System.Text.UTF8Encoding]::new($false)
)

Write-Host "[5/5] Create ZIP..."
if (Test-Path -LiteralPath $zipPath) {
  Remove-Item -LiteralPath $zipPath -Force
}
$packageItems = Get-ChildItem -LiteralPath $packageRoot -Force
Compress-Archive -LiteralPath $packageItems.FullName -DestinationPath $zipPath -Force

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
  $requiredEntries = @(
    "Install_SC_REVIT.bat",
    "install_sc_revit.ps1",
    "Enable_SC_REVIT_Agent.bat",
    "Disable_SC_REVIT_Agent.bat",
    "Collect_SC_REVIT_Diagnostics.bat",
    "Uninstall_SC_REVIT.bat",
    "release_manifest.json",
    "payload/dist/RevitFamilyClassifier/RevitFamilyClassifier.exe",
    "payload/revit_addin/bin/RfaMetadataAddin.dll",
    "payload/VERSION.txt"
  )
  $entryNames = @($zip.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
  foreach ($entry in $requiredEntries) {
    if ($entryNames -notcontains $entry) {
      throw "Release ZIP is missing required entry: $entry"
    }
  }
  if (-not ($entryNames | Where-Object {
    $_ -like "payload/docs/*.html"
  })) {
    throw "Release ZIP is missing the HTML user guide."
  }
}
finally {
  $zip.Dispose()
}

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
$zipHashPath = $zipPath + ".sha256"
[System.IO.File]::WriteAllText(
  $zipHashPath,
  ($zipHash + "  " + (Split-Path -Leaf $zipPath) + [Environment]::NewLine),
  [System.Text.UTF8Encoding]::new($false)
)

Write-Host ""
Write-Host "Release package ready:" -ForegroundColor Green
Write-Host $zipPath
Write-Host "SHA-256: $zipHash"
Write-Host "Checksum: $zipHashPath"
