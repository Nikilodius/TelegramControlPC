@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "LOG=%~dp0install.log"
echo ==== Установка Telegram PC Control : %date% %time% ==== > "%LOG%"

echo ============================================
echo   Telegram PC Control - установка
echo ============================================
echo.

call :find_python
if defined PYLAUNCHER goto :have_python

echo Python не найден ^(или найдена "заглушка" Microsoft Store^).
echo Пробую установить Python автоматически с python.org...
echo Python не найден, начинаю автоустановку >> "%LOG%"
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ВНИМАНИЕ: для установки Python на весь компьютер нужны права администратора.
    echo Закрой это окно, нажми правой кнопкой на install.bat и выбери
    echo "Запуск от имени администратора", затем запусти ещё раз.
    echo.
    pause
    exit /b 1
)

set "PY_VERSION=3.12.7"
set "PYURL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-amd64.exe"
set "PYINSTALLER=%TEMP%\python_installer_%RANDOM%.exe"

echo Скачиваю Python %PY_VERSION%...
echo URL: %PYURL% >> "%LOG%"
echo Файл: %PYINSTALLER% >> "%LOG%"

where curl >nul 2>&1
if %errorlevel%==0 (
    curl -L --fail -o "%PYINSTALLER%" "%PYURL%" >> "%LOG%" 2>&1
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYINSTALLER%'" >> "%LOG%" 2>&1
)

if not exist "%PYINSTALLER%" (
    echo.
    echo НЕ УДАЛОСЬ скачать установщик Python ^(нет интернета, прокси или блокировка антивирусом^).
    echo Подробности смотри в файле install.log рядом со скриптом.
    echo Установи Python вручную: https://www.python.org/downloads/
    echo При установке обязательно отметь галочку "Add python.exe to PATH", затем запусти install.bat снова.
    echo.
    pause
    exit /b 1
)

for %%A in ("%PYINSTALLER%") do set "PYSIZE=%%~zA"
if "%PYSIZE%"=="0" (
    echo Скачанный файл пустой — загрузка не удалась. Подробности в install.log.
    del "%PYINSTALLER%" >nul 2>&1
    pause
    exit /b 1
)

echo Устанавливаю Python, подожди ~1-2 минуты ^(появится индикатор прогресса^)...
echo Запускаю установщик... >> "%LOG%"
"%PYINSTALLER%" /passive InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0 >> "%LOG%" 2>&1
set "INSTALL_EXIT=%errorlevel%"
echo Установщик Python завершился с кодом %INSTALL_EXIT% >> "%LOG%"
del "%PYINSTALLER%" >nul 2>&1

REM Windows не обновляет PATH в уже открытом окне cmd после установки —
REM подставляем типичные пути установки Python вручную для этой сессии.
set "PATH=%PATH%;%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts"
set "PATH=%PATH%;%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts"

call :find_python
if defined PYLAUNCHER goto :have_python

echo.
echo Python, похоже, установился ^(код установщика: %INSTALL_EXIT%^), но эта консоль его пока не видит.
echo Закрой это окно и запусти install.bat ещё раз — обычно со второго раза всё находится.
echo Если и тогда не поможет — открой install.log и пришли мне, что там написано.
echo.
pause
exit /b 1

:have_python
echo.
echo Найден Python: %PYLAUNCHER%
%PYLAUNCHER% --version
%PYLAUNCHER% --version >> "%LOG%" 2>&1
echo.

echo Создаю виртуальное окружение .venv...
%PYLAUNCHER% -m venv .venv >> "%LOG%" 2>&1
if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo Не удалось создать виртуальное окружение. Подробности в install.log.
    echo Попробуй запустить install.bat ещё раз, либо от имени администратора.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
echo Обновляю pip...
python -m pip install --upgrade pip >> "%LOG%" 2>&1

echo Ставлю зависимости из requirements.txt ^(может занять минуту^)...
python -m pip install -r requirements.txt >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
    echo.
    echo Не удалось установить зависимости. Подробности в install.log.
    echo Обычно помогает: закрыть окно, проверить интернет и запустить install.bat ещё раз.
    pause
    exit /b 1
)

if not exist .env copy .env.example .env >nul

echo.
echo ============================================
echo   Готово! Всё установлено успешно.
echo ============================================
echo Открой панель управления двойным кликом по ControlPanel.vbs,
echo заполни там Bot Token / User ID / пароль и нажми "Запустить бота".
echo.
pause
exit /b 0

REM ---------------------------------------------------------------
REM Проверка наличия РЕАЛЬНОГО Python.
REM Важно: на новых Windows команда "python" без установленного Python
REM может открывать Microsoft Store вместо ошибки (т.н. App Execution
REM Alias-заглушка). Поэтому мало факта "команда нашлась" — нужно
REM убедиться, что она реально печатает версию Python.
REM ---------------------------------------------------------------
:find_python
set "PYLAUNCHER="
where py >nul 2>&1
if %errorlevel%==0 (
    py --version 2>nul | findstr /b "Python" >nul
    if !errorlevel!==0 (
        set "PYLAUNCHER=py"
        exit /b 0
    )
)
where python >nul 2>&1
if %errorlevel%==0 (
    python --version 2>nul | findstr /b "Python" >nul
    if !errorlevel!==0 (
        set "PYLAUNCHER=python"
        exit /b 0
    )
)
exit /b 1
