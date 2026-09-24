@echo off
REM ============================================================
REM  Build moss.exe with Nuitka.
REM
REM  ASCII only -- non-ASCII comments break under the default
REM  cp936 codepage on Chinese Windows.
REM
REM  Usage:  tools\打包.cmd
REM ============================================================
setlocal
cd /d "%~dp0.."

echo [1/3] Working dir: %CD%

if not exist "icon.ico" (
  echo [ERROR] icon.ico not found in %CD%
  echo         Generate one first -- see design\图标提示词.md
  exit /b 1
)
if not exist "moss.py" (
  echo [ERROR] moss.py not found in %CD%
  exit /b 1
)

echo [2/3] Running Nuitka (this takes a few minutes)...
python -m nuitka ^
  --onefile ^
  --lto=yes ^
  --remove-output ^
  --onefile-tempdir-spec="{CACHE_DIR}/moss_build/{TIME}" ^
  --windows-icon-from-ico=icon.ico ^
  --include-package=core ^
  -o moss moss.py

if errorlevel 1 (
  echo.
  echo [ERROR] build failed.
  exit /b 1
)

if not exist "moss.exe" (
  echo [ERROR] Nuitka reported success but moss.exe is missing.
  exit /b 1
)

echo.
echo [3/3] [OK] built %CD%\moss.exe
echo.
echo Next steps (do not skip):
echo   1^) .\moss.exe --selfcheck
echo   2^) cd to some project dir and run this exe with "m"
echo      to prove MOSS_HOME resolves correctly after packaging.
echo.
echo Reminder: moss.exe must ship together with the system\ folder.
endlocal
