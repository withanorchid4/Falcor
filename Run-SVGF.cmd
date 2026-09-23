@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-Falcor.ps1" -Renderer SVGF %*
if errorlevel 1 pause
