@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
set "FLET=%VENV%\Scripts\flet.exe"

echo ============================================================
echo  NLCL one-click build
echo  Project: %~dp0
echo ============================================================
echo.

if not exist "%PY%" (
    echo [1/6] .venv not found, creating...
    where py >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [ERROR] Python launcher "py" not found.
        echo Install Python 3.11+ 64-bit and check "Add Python to PATH".
        echo Download: https://www.python.org/downloads/windows/
        goto :fail
    )
    py -3 -m venv "%VENV%"
    if errorlevel 1 goto :fail
) else (
    echo [1/6] Using existing .venv
)

echo.
echo [2/6] Updating pip...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo.
echo [3/6] Installing runtime dependencies...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [4/6] Installing build dependencies...
"%PY%" -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

echo.
echo [5/6] Cleaning old build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist NLCL.spec del /q NLCL.spec

echo.
echo [6/6] Packaging with PyInstaller via flet pack...
echo       This can take several minutes. Do not close this window.
"%FLET%" pack main.py ^
  --name NLCL ^
  --icon "assets\app.ico" ^
  --add-data "assets;assets" ^
  --product-name "NLCL" ^
  --file-description "NLCL - lightweight Minecraft Java launcher" ^
  --product-version "1.0.0" ^
  --file-version "1.0.0.0" ^
  --company-name "NLCL" ^
  --copyright "NLCL" ^
  --hidden-import PIL ^
  --hidden-import requests ^
  --hidden-import urllib3 ^
  --hidden-import segno ^
  --hidden-import minecraft_launcher_lib ^
  -y
if errorlevel 1 goto :fail

if not exist "dist\NLCL.exe" (
    echo.
    echo [ERROR] dist\NLCL.exe was not created.
    goto :fail
)

echo.
echo ============================================================
echo  BUILD SUCCESS
echo  EXE: %~dp0dist\NLCL.exe
echo ============================================================
echo.
echo Next steps:
echo   1. Double-click dist\NLCL.exe and test it.
echo   2. Upload NLCL.exe to GitHub Releases (see README).
echo.
pause
endlocal
exit /b 0

:fail
echo.
echo ============================================================
echo  BUILD FAILED
echo  Please read the error above, then check README.md.
echo ============================================================
echo.
pause
endlocal
exit /b 1
