$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bin = Join-Path $root "bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$tmpBin = Join-Path $root ("bin_build_tmp_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmpBin | Out-Null

$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$revitApi = "C:\Program Files\Autodesk\Revit 2024\RevitAPI.dll"
$revitApiUi = "C:\Program Files\Autodesk\Revit 2024\RevitAPIUI.dll"
$webExtensions = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Web.Extensions.dll"
$presentationCore = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\WPF\PresentationCore.dll"
$windowsBase = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\WPF\WindowsBase.dll"
$outputDll = Join-Path $bin "RfaMetadataAddin.dll"
$tmpOutputDll = Join-Path $tmpBin "RfaMetadataAddin.dll"
$sourceFiles = Get-ChildItem -LiteralPath (Join-Path $root "src") -Filter "*.cs" -Recurse | Sort-Object FullName | ForEach-Object { $_.FullName }

try {
  & $csc `
    /nologo `
    /codepage:65001 `
    /target:library `
    /reference:$revitApi `
    /reference:$revitApiUi `
    /reference:$webExtensions `
    /reference:$presentationCore `
    /reference:$windowsBase `
    "/out:$tmpOutputDll" `
    $sourceFiles

  if ($LASTEXITCODE -ne 0) {
    throw "C# 編譯失敗，ExitCode=$LASTEXITCODE"
  }

  $backupDll = Join-Path $bin "RfaMetadataAddin.dll.bak"
  if (Test-Path -LiteralPath $backupDll) {
    Remove-Item -LiteralPath $backupDll -Force
  }
  if (Test-Path -LiteralPath $outputDll) {
    Rename-Item -LiteralPath $outputDll -NewName "RfaMetadataAddin.dll.bak" -Force
  }
  try {
    [System.IO.File]::WriteAllBytes($outputDll, [System.IO.File]::ReadAllBytes($tmpOutputDll))
  }
  catch {
    if ((-not (Test-Path -LiteralPath $outputDll)) -and (Test-Path -LiteralPath $backupDll)) {
      Rename-Item -LiteralPath $backupDll -NewName "RfaMetadataAddin.dll" -Force
    }
    throw
  }
  if (Test-Path -LiteralPath $backupDll) {
    Remove-Item -LiteralPath $backupDll -Force
  }
  if (-not (Test-Path -LiteralPath $outputDll)) {
    throw "Build failed: $outputDll was not created."
  }
  Write-Host "Built: $outputDll"
}
finally {
  if (Test-Path -LiteralPath $tmpBin) {
    Remove-Item -LiteralPath $tmpBin -Recurse -Force
  }
}
