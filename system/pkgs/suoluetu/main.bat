@echo off
setlocal

echo Killing Explorer...
taskkill /f /im explorer.exe >nul 2>&1

echo Waiting...
timeout /t 2 /nobreak >nul

echo Deleting icon cache...
del /f /q /a "%LocalAppData%\IconCache.db" >nul 2>&1
del /f /q /a "%LocalAppData%\Microsoft\Windows\Explorer\iconcache*" >nul 2>&1
del /f /q /a "%LocalAppData%\Microsoft\Windows\Explorer\thumbcache*" >nul 2>&1

echo Restarting Explorer...
tasklist /fi "imagename eq explorer.exe" | find /i "explorer.exe" >nul
if errorlevel 1 start "" explorer.exe

echo Done.
endlocal