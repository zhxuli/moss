@echo off
echo 正在关闭 Windows 资源管理器...
taskkill /f /im explorer.exe

echo 正在删除图标缓存文件...
cd /d %userprofile%\AppData\Local
del IconCache.db /a

echo 操作完成，正在重启资源管理器...
start explorer.exe
echo.
echo 缓存已清空！
pause