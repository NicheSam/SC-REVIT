$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$testBin = Join-Path $root "test_bin"
$testExe = Join-Path $testBin "DrainageEngineeringCoreTests.exe"
$coreSource = Join-Path $root "src\Drainage\DrainageEngineeringCore.cs"
$testSource = Join-Path $root "tests\DrainageEngineeringCoreTests.cs"

New-Item -ItemType Directory -Force -Path $testBin | Out-Null
try {
  & $csc /nologo /codepage:65001 /target:exe "/out:$testExe" $coreSource $testSource
  if ($LASTEXITCODE -ne 0) {
    throw "Drainage core test compilation failed, ExitCode=$LASTEXITCODE"
  }
  & $testExe
  if ($LASTEXITCODE -ne 0) {
    throw "Drainage core tests failed, ExitCode=$LASTEXITCODE"
  }
}
finally {
  if (Test-Path -LiteralPath $testBin) {
    Remove-Item -LiteralPath $testBin -Recurse -Force
  }
}
