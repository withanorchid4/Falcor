@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "app=%CD%\build\windows-vs2022\bin\Release\Mogwai.exe"
if not exist "%app%" exit /b 1
"%app%" --device-type d3d12 --script "%CD%\scripts\DDGIAccumulated.py" %*
popd
