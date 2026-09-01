@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo Сначала запусти setup.bat (установка зависимостей)
  pause
  exit /b 1
)
echo Режим наблюдения: кидай видео в папку in\ — обработка автоматически.
echo Остановить: Ctrl+C
call venv\Scripts\python.exe app\pipeline\main.py watch
pause