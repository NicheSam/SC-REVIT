@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Set_SC_REVIT_Agent.ps1" -Mode disable
pause
