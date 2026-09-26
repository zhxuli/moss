@echo off
setlocal EnableDelayedExpansion

:: ------------------- 配置区 -------------------
set "tld_list=.com. .cn. .net. .org. .io. .gov. .edu. .dev. .app. .xyz. .top. .vip. .co. .cc. .io. .hk. .xin."
:: --------------------------------------------

:: 获取第一个参数
set "input_str=%~1"

:: 1. 检查是否传入了参数
if "%input_str%"=="" (
    echo.
    echo 错误: 请提供一个 URL 或本地路径作为参数。
    goto :show_usage
)

:: 2. 核心判断：是否以白名单中的TLD结尾
set "is_url=false"
for %%d in (%tld_list:.= %) do (
    :: 使用延迟扩展 !input_str! 来获取变量的实时值
    set "temp_str=!input_str!"
    
    :: 将结尾的 .tld 替换为空。例如，将 "google.com" 中的 ".com" 替换掉
    set "replaced_str=!temp_str:.%%d=!"

    :: 如果替换后的字符串和原字符串不同，说明原字符串是以 .tld 结尾的
    if /i not "!temp_str!"=="!replaced_str!" (
        set "is_url=true"
        goto :handle_url
    )
)

:: 如果循环结束，is_url 仍然是 false，则说明不是URL
goto :handle_path


:: --- URL 处理逻辑 ---
:handle_url
echo [信息] 检测到顶级域名，作为URL处理...
set "final_target=%input_str%"

if /i "%final_target:~0,8%"=="https://" goto :open_it
if /i "%final_target:~0,7%"=="http://" goto :open_it

echo [信息] 未检测到 http/https 协议头，将自动添加 "http://"
set "final_target=http://%input_str%"
goto :open_it


:: --- 本地路径处理逻辑 ---
:handle_path
echo [信息] 未检测到已知顶级域名，作为本地文件/目录处理...

if exist "%input_str%" (
    echo [信息] 成功找到本地路径: "%input_str%"
    set "final_target=%input_str%"
    goto :open_it
) else (
    echo.
    echo [错误] "%input_str%" 不是一个已知的URL，也不是一个当前存在的本地路径。
    echo [提示] 如果是本地路径，请确保您在正确的目录下运行，或提供完整路径。
    goto :show_usage
)


:: --- 执行打开操作 ---
:open_it
echo 正在打开: %final_target%
start "" "%final_target%"
goto :eof


:: --- 显示用法并退出 ---
:show_usage
echo.
echo 用法: %0 ^<url_or_path^>
echo.
echo 示例:
echo   %0 google.com             ^(作为URL打开^)
echo   %0 main.py                ^(作为本地文件打开^)
echo   %0 myproject              ^(作为本地目录打开^)
echo   %0 "C:\Users\Admin"       ^(作为本地目录打开^)
echo.
goto :eof

:: 注意: endlocal 会自动禁用延迟扩展
endlocal