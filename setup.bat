@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo === VideoNotes: установка ===
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ОШИБКА] Python не найден. Установи Python 3.10+ с python.org (галочка "Add to PATH") и повтори.
  pause
  exit /b 1
)

echo [1/5] Виртуальное окружение...
if not exist venv\Scripts\python.exe python -m venv venv
call venv\Scripts\python.exe -m pip install -U pip >nul

echo [2/5] Зависимости (первый раз ~3 ГБ: torch CUDA, gigaam)...
call venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
  echo [ОШИБКА] pip install не удался. Прогони ещё раз — часто помогает.
  pause
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [3/5] Установка ffmpeg...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo ffmpeg не встал через winget. Скачай с https://www.gyan.dev/ffmpeg/builds/ (ffmpeg-release-essentials.zip),
    echo распакуй и добавь папку bin\ в PATH. Затем повтори setup.bat.
    pause
    exit /b 1
  )
) else (
  echo [3/5] ffmpeg уже есть
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo [4/5] Установка Ollama...
  winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo Ollama не встал через winget. Скачай с https://ollama.com/download и повтори setup.bat.
    pause
    exit /b 1
  )
) else (
  echo [4/5] Ollama уже есть
)

echo [5/5] Модели Ollama (первый раз ~14 ГБ):
echo   - qwen2.5vl:7b  (анализ кадров, ~5 ГБ)
echo   - qwen2.5:14b   (сборка конспекта, ~9 ГБ)
ollama pull qwen2.5vl:7b
ollama pull qwen2.5:14b-instruct-q4_K_M

echo.
echo === Самопроверка (GigaAM скачает модель ~1 ГБ, прогонит тест) ===
call venv\Scripts\python.exe app\pipeline\main.py selftest
echo.
echo Готово! Дальше:
echo   - перетащи видео на process.bat, ИЛИ
echo   - запусти watch.bat и кидай видео в папку in\
pause