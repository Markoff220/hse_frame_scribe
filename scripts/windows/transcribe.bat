@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

rem Только транскрипция: перетащи на этот файл одно или несколько видео.
rem Для каждого получится output\имя-видео\транскрипция.md. Кадры и Ollama не нужны.

if "%~1"=="" (
  echo Использование: перетащи на этот файл одно или несколько видео
  echo Для каждого получится output\имя-видео\транскрипция.md, кадры и Ollama не нужны
  pause
  exit /b 1
)

if not exist venv\Scripts\python.exe (
  echo Сначала запусти scripts\windows\setup.bat ^(установка зависимостей^)
  pause
  exit /b 1
)

set "FAILED=0"

:next
if "%~1"=="" goto done
echo.
echo === "%~nx1"
call venv\Scripts\python.exe app\pipeline\main.py transcribe "%~1"
if errorlevel 1 set /a FAILED+=1
shift
goto next

:done
echo.
if "%FAILED%"=="0" (
  echo Готово. Транскрипции лежат в папке output
) else (
  echo Не получилось обработать файлов: %FAILED%. Ошибка выше в логе
)
pause
if not "%FAILED%"=="0" exit /b 1
exit /b 0
