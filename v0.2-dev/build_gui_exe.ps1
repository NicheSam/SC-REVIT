$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$specPath = "E:\Desktop\Codex\pyinstaller_spec_tmp"
$workPath = "E:\Desktop\Codex\pyinstaller_build_tmp"
New-Item -ItemType Directory -Force -Path $specPath | Out-Null
New-Item -ItemType Directory -Force -Path $workPath | Out-Null
$rulesPath = Join-Path $root "rules.json"
$parameterTemplatesPath = Join-Path $root "parameter_templates"
$addinBinPath = Join-Path $root "revit_addin\bin"

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onedir `
  --name RevitFamilyClassifier `
  --specpath $specPath `
  --workpath $workPath `
  --additional-hooks-dir "build_hooks" `
  --add-data "$rulesPath;." `
  --add-data "$parameterTemplatesPath;parameter_templates" `
  --add-data "$addinBinPath;revit_addin\bin" `
  "gui_app.py"

$exe = Join-Path $root "dist\RevitFamilyClassifier\RevitFamilyClassifier.exe"
if (!(Test-Path -LiteralPath $exe)) {
  throw "Build failed: $exe was not created."
}

Write-Output "Built: $exe"
