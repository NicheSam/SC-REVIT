param(
  [string]$OutputDirectory = "$env:USERPROFILE\Desktop"
)

$ErrorActionPreference = "Stop"
$stamp = [DateTime]::Now.ToString("yyyyMMdd-HHmmss")
$workDir = Join-Path $env:TEMP ("SC_REVIT_Diagnostics_" + $stamp)
$outputZip = Join-Path $OutputDirectory ("SC_REVIT_Diagnostics_" + $stamp + ".zip")
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

$manifestPath = Join-Path $env:APPDATA "Autodesk\Revit\Addins\2024\RfaMetadataAddin.addin"
$dllPath = Join-Path $env:LOCALAPPDATA "SCRevit\Revit2024\RfaMetadataAddin.dll"
$versionPath = Join-Path $env:LOCALAPPDATA "SC_REVIT\VERSION.txt"
$queueDir = Join-Path $env:LOCALAPPDATA "RevitFamilyClassifier\runtime\queue"

$summary = [ordered]@{
  collectedLocal = [DateTime]::Now.ToString("o")
  windowsVersion = [Environment]::OSVersion.VersionString
  manifestExists = Test-Path -LiteralPath $manifestPath
  dllExists = Test-Path -LiteralPath $dllPath
  dllSha256 = if (Test-Path -LiteralPath $dllPath) {
    (Get-FileHash -LiteralPath $dllPath -Algorithm SHA256).Hash
  } else { $null }
  dllSignature = if (Test-Path -LiteralPath $dllPath) {
    (Get-AuthenticodeSignature -LiteralPath $dllPath).Status.ToString()
  } else { $null }
  agentListenerEnabled = Test-Path -LiteralPath (Join-Path $queueDir "agent_listener.enabled")
  pendingRequestCount = @(Get-ChildItem -LiteralPath (Join-Path $queueDir "requests") -Filter "*.json" -ErrorAction SilentlyContinue).Count
  quarantineBatchCount = @(Get-ChildItem -LiteralPath (Join-Path $queueDir "quarantine") -Directory -ErrorAction SilentlyContinue).Count
}
[System.IO.File]::WriteAllText(
  (Join-Path $workDir "summary.json"),
  ($summary | ConvertTo-Json -Depth 4),
  [System.Text.UTF8Encoding]::new($false)
)

foreach ($source in @($manifestPath, $versionPath)) {
  if (Test-Path -LiteralPath $source) {
    Copy-Item -LiteralPath $source -Destination $workDir -Force
  }
}
$errorDir = Join-Path $queueDir "errors"
if (Test-Path -LiteralPath $errorDir) {
  Copy-Item -LiteralPath $errorDir -Destination (Join-Path $workDir "errors") -Recurse -Force
}
$quarantineDir = Join-Path $queueDir "quarantine"
if (Test-Path -LiteralPath $quarantineDir) {
  $diagnosticQuarantineDir = Join-Path $workDir "quarantine"
  New-Item -ItemType Directory -Force -Path $diagnosticQuarantineDir | Out-Null
  Get-ChildItem -LiteralPath $quarantineDir -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 3 |
    ForEach-Object {
      Copy-Item -LiteralPath $_.FullName -Destination $diagnosticQuarantineDir -Recurse -Force
    }
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
Compress-Archive -Path (Join-Path $workDir "*") -DestinationPath $outputZip -Force
Write-Host "Diagnostics package created:" -ForegroundColor Green
Write-Host $outputZip
