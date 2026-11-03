@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\local-integration.ps1" -Action start
if errorlevel 1 pause
