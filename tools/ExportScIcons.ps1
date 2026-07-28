param(
  [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"

$toolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $toolRoot
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
  $OutputDirectory = Join-Path $root "assets\ui-icons"
}

$addinDll = Join-Path $root "revit_addin\bin\RfaMetadataAddin.dll"
if (-not (Test-Path -LiteralPath $addinDll)) {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "revit_addin\build.ps1")
}

Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
[System.Reflection.Assembly]::LoadFrom($addinDll) | Out-Null

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$iconNames = @(
  "family_archive",
  "project_recovery",
  "point_placement",
  "backstage",
  "fire_branch",
  "drainage_connect",
  "drainage_settings",
  "align_centerline",
  "connect_45",
  "down_45",
  "vertical_down",
  "opening_locator",
  "element_inspector",
  "parameter_audit",
  "breakpoint_check",
  "piping_support"
)

foreach ($iconName in $iconNames) {
  $bitmap = [RfaMetadataAddin.ScIconFactory]::Create($iconName, 64)
  $encoder = New-Object System.Windows.Media.Imaging.PngBitmapEncoder
  $encoder.Frames.Add([System.Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
  $path = Join-Path $OutputDirectory ($iconName + ".png")
  $stream = [System.IO.File]::Open(
    $path,
    [System.IO.FileMode]::Create,
    [System.IO.FileAccess]::Write)
  try {
    $encoder.Save($stream)
  }
  finally {
    $stream.Dispose()
  }
}

Write-Host ("Exported {0} SC icons to {1}" -f $iconNames.Count, $OutputDirectory)
