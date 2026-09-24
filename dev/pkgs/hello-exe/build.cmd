@echo off
REM Build src\main.go into main.exe.
REM
REM Why this split:
REM   A shipped package carries only main.exe -- users do not need the Go
REM   toolchain, and startup is fast.
REM   src\ keeps the source so it can be edited later; this script makes the exe.
REM
REM Measured: "go run" ~19s (recompiles every time) vs compiled exe ~0.05s.
REM
REM NOTE: keep this file ASCII-only. Non-ASCII comments break under the
REM       default cp936 codepage on Chinese Windows.
go build -o "%~dp0main.exe" "%~dp0src\main.go"
if errorlevel 1 (
  echo [ERROR] build failed. Make sure "go" is installed and on PATH.
  exit /b 1
)
echo [OK] built %~dp0main.exe
