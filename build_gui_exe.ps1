$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$buildTempRoot = Join-Path $root ".build_tmp"
$specPath = Join-Path $buildTempRoot "spec"
$workPath = Join-Path $buildTempRoot "work"
$distPath = Join-Path $buildTempRoot "dist"
$finalDist = Join-Path $root "dist\RevitFamilyClassifier"
New-Item -ItemType Directory -Force -Path $specPath | Out-Null
New-Item -ItemType Directory -Force -Path $workPath | Out-Null
New-Item -ItemType Directory -Force -Path $distPath | Out-Null
Remove-Item -LiteralPath (Join-Path $distPath "RevitFamilyClassifier") -Recurse -Force -ErrorAction SilentlyContinue
$rulesPath = Join-Path $root "rules.json"
$parameterTemplatesPath = Join-Path $root "parameter_templates"
$addinBinPath = Join-Path $root "revit_addin\bin"
$uiIconsPath = Join-Path $root "assets\ui-icons"

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onedir `
  --name RevitFamilyClassifier `
  --distpath $distPath `
  --specpath $specPath `
  --workpath $workPath `
  --additional-hooks-dir "build_hooks" `
  --add-data "$rulesPath;." `
  --add-data "$parameterTemplatesPath;parameter_templates" `
  --add-data "$addinBinPath;revit_addin\bin" `
  --add-data "$uiIconsPath;assets\ui-icons" `
  "gui_app.py"

$tempExe = Join-Path $distPath "RevitFamilyClassifier\RevitFamilyClassifier.exe"
if (!(Test-Path -LiteralPath $tempExe)) {
  throw "Build failed: $tempExe was not created."
}
if (Test-Path -LiteralPath $finalDist) {
  $backupDist = Join-Path (Split-Path -Parent $finalDist) ("RevitFamilyClassifier.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
  Rename-Item -LiteralPath $finalDist -NewName (Split-Path -Leaf $backupDist)
}
Copy-Item -LiteralPath (Join-Path $distPath "RevitFamilyClassifier") -Destination $finalDist -Recurse -Force

$exe = Join-Path $finalDist "RevitFamilyClassifier.exe"
if (!(Test-Path -LiteralPath $exe)) {
  throw "Build failed: $exe was not created."
}

Write-Output "Built: $exe"
