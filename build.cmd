@echo off
REM ============================================================================
REM  moss build helper  (V-380)
REM  Shortcut for the long nuitka command that is kept in moss.py.
REM  The real logic lives in tools\build.py -- do NOT put logic here.
REM  Keep this file ASCII-only: cmd.exe under cp936 mangles non-ASCII bytes in
REM  .cmd files (that is exactly why the build logic is Python, see build.py).
REM ============================================================================
setlocal
REM  Resolve OUR OWN folder (not the caller's cwd), then build from the repo root.
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
