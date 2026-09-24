@echo off
REM ============================================================
REM  Build moss.exe with Nuitka.
REM
REM  ASCII only -- non-ASCII comments break under the default
REM  cp936 codepage on Chinese Windows.
REM
REM  Why "venv" and why Python 3.12:
REM    Nuitka cannot use MinGW/gcc with Python 3.13 (CPython 3.13
REM    changed internal layouts). Python 3.12 builds fine.
REM    The venv keeps the build toolchain out of the system Python,
REM    and "venv" is the conventional folder name.
REM
REM  Usage:  tools\打包.cmd
REM ============================================================
setlocal
cd /d "%~dp0.."
echo [build] working dir: %CD%

if not exist "moss.py" (
  echo [ERROR] moss.py not found in %CD%
  exit /b 1
)
if not exist "icon.ico" (
  echo [ERROR] icon.ico not found in %CD%
  echo         See design\图标提示词.md and tools\图标优化.py
  exit /b 1
)

if not exist "venv\Scripts\python.exe" (
  echo [setup] venv not found, creating it with Python 3.12 ...
  py -3.12 -m venv venv
  if errorlevel 1 (
    echo [ERROR] failed to create venv.
    echo         Is Python 3.12 installed?  Check with:  py -0p
    exit /b 1
  )
  venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  venv\Scripts\python.exe -m pip install nuitka
  if errorlevel 1 (
    echo [ERROR] failed to install nuitka into venv.
    exit /b 1
  )
)

echo [build] running Nuitka (first run downloads a C compiler; takes a while)...
venv\Scripts\python.exe -m nuitka ^
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
echo [OK] built %CD%\moss.exe
echo.
echo Next (do not skip):
echo   1^) .\moss.exe --selfcheck
echo   2^) cd into some project dir and run this exe with "m"
echo      to prove MOSS_HOME resolves correctly after packaging.
echo.
echo Ship moss.exe together with the system\ folder.
endlocal
