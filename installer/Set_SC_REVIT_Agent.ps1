param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("enable", "disable")]
  [string]$Mode
)

$ErrorActionPreference = "Stop"
$queueDir = Join-Path $env:LOCALAPPDATA "RevitFamilyClassifier\runtime\queue"
$markerPath = Join-Path $queueDir "agent_listener.enabled"
$heartbeatPath = Join-Path $queueDir "listener_heartbeat.json"
New-Item -ItemType Directory -Force -Path $queueDir | Out-Null

if ($Mode -eq "enable") {
  [System.IO.File]::WriteAllText(
    $markerPath,
    "enabled`n",
    [System.Text.Encoding]::ASCII
  )
  Write-Host "SC REVIT Agent listener enabled." -ForegroundColor Green
  Write-Host "Open Revit 2024 or wait a few seconds for the listener to connect."
}
else {
  if (Test-Path -LiteralPath $markerPath) {
    Remove-Item -LiteralPath $markerPath -Force
  }
  if (Test-Path -LiteralPath $heartbeatPath) {
    Remove-Item -LiteralPath $heartbeatPath -Force
  }
  Write-Host "SC REVIT Agent listener disabled." -ForegroundColor Green
  Write-Host "Manual Revit ribbon tools remain available."
}
