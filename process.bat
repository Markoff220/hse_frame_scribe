@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo Использование: перетащи видео-файл на этот файл
  pause
  exit /b 1
)

if not exist venv\Scripts\python.exe (
  echo Сначала запусти setup.bat (установка зависимостей)
  pause
  exit /b 1
)

call venv\Scripts\python.exe app\pipeline\main.py process "%~1"
echo.
pause