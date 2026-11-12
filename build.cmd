@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo [error] venv\Scripts\python.exe not found.
  echo         Create it first:  py -3.12 -m venv venv
  echo         Then install:     venv\Scripts\python.exe -m pip install nuitka
  exit /b 1
)

echo [moss] building - this takes 1-3 minutes, the first time it also downloads
echo [moss] the exact MinGW gcc nuitka wants (about 100 MB, cached afterwards).
"venv\Scripts\python.exe" "tools\build.py" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [error] build failed - exit code %RC%
exit /b %RC%
