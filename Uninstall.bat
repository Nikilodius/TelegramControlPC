@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

echo ============================================
echo   Telegram PC Control - полное удаление
echo ============================================
echo.
echo Это остановит бота и панель управления, уберёт автозапуск
echo с Windows и БЕЗВОЗВРАТНО удалит всю папку программы:
echo.
echo   %PROJECT_DIR%
echo.
echo (включая .venv, bot.log, и .env с токеном бота и паролем)
echo.
set /p CONFIRM="Точно удалить всё? Введи YES и нажми Enter: "
if /I not "%CONFIRM%"=="YES" (
    echo.
    echo Отменено, ничего не удалено.
    pause
    exit /b 0
)

echo.
echo Останавливаю бота...
if exist "bot.pid" (
    for /f "usebackq delims=" %%P in ("bot.pid") do (
        taskkill /PID %%P /F >nul 2>&1
    )
    del "bot.pid" >nul 2>&1
)

echo Останавливаю панель управления...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'control_panel\.pyw' -or $_.CommandLine -match 'bot\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo Убираю автозапуск с Windows...
set "STARTUP_VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TelegramPCControl.vbs"
if exist "%STARTUP_VBS%" del "%STARTUP_VBS%" >nul 2>&1

echo.
echo Удаляю папку программы целиком...

REM Batch-файл не может удалить сам себя, пока выполняется —
REM поэтому создаём отдельный скрытый скрипт, который подождёт закрытия
REM этого окна и снесёt всю папку целиком (вместе с собой).
set "HELPER=%TEMP%\tpc_uninstall_helper_%RANDOM%.vbs"
> "%HELPER%" echo Set fso = CreateObject("Scripting.FileSystemObject")
>> "%HELPER%" echo WScript.Sleep 1500
>> "%HELPER%" echo On Error Resume Next
>> "%HELPER%" echo fso.DeleteFolder "%PROJECT_DIR%", True
>> "%HELPER%" echo fso.DeleteFile WScript.ScriptFullName, True

echo.
echo Готово. Папка будет удалена через пару секунд после закрытия этого окна.
echo.
echo Совет: токен бота всё ещё действителен в Telegram — если хочешь
echo подстраховаться, отзови его через @BotFather -^> /revoke.
echo.
echo Спасибо, что пользовался Telegram PC Control!
timeout /t 3 >nul

start "" wscript "%HELPER%"
exit
