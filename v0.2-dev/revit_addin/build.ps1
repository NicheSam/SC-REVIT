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
    (Join-Path $root "src\RfaMetadataCommand.cs") `
    (Join-Path $root "src\RfaMetadataApplication.cs")

  if ($LASTEXITCODE -ne 0) {
    throw "C# 編譯失敗，ExitCode=$LASTEXITCODE"
  }

  Start-Sleep -Seconds 1
  $stagedDll = Join-Path $bin ("RfaMetadataAddin.dll.new." + [Guid]::NewGuid().ToString("N"))
  $backupDll = Join-Path $bin "RfaMetadataAddin.dll.bak"
  Copy-Item -LiteralPath $tmpOutputDll -Destination $stagedDll -Force

  $swapped = $false
  for ($attempt = 1; $attempt -le 8; $attempt++) {
    try {
      if (Test-Path -LiteralPath $backupDll) {
        Remove-Item -LiteralPath $backupDll -Force
      }
      if (Test-Path -LiteralPath $outputDll) {
        Move-Item -LiteralPath $outputDll -Destination $backupDll -Force
      }
      Move-Item -LiteralPath $stagedDll -Destination $outputDll -Force
      if ((Get-FileHash -LiteralPath $tmpOutputDll -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $outputDll -Algorithm SHA256).Hash) {
        throw "正式 DLL 雜湊驗證失敗"
      }
      if (Test-Path -LiteralPath $backupDll) {
        Remove-Item -LiteralPath $backupDll -Force
      }
      $swapped = $true
      break
    }
    catch {
      if ((-not (Test-Path -LiteralPath $outputDll)) -and (Test-Path -LiteralPath $backupDll)) {
        try {
          Move-Item -LiteralPath $backupDll -Destination $outputDll -Force
        }
        catch {
        }
      }
      if ($attempt -eq 8) {
        throw
      }
      Start-Sleep -Milliseconds 500
    }
  }
  if (Test-Path -LiteralPath $stagedDll) {
    Remove-Item -LiteralPath $stagedDll -Force
  }
  if (-not $swapped) {
    throw "無法覆蓋正式 DLL"
  }
  Write-Host "Built: $outputDll"
}
finally {
  if (Test-Path -LiteralPath $tmpBin) {
    Remove-Item -LiteralPath $tmpBin -Recurse -Force
  }
}
