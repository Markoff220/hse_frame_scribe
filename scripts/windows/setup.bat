@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."
echo === VideoNotes: установка ===
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ОШИБКА] Python не найден. Установи Python 3.13+ с python.org (галочка "Add to PATH") и повтори.
  pause
  exit /b 1
)

echo [1/5] Виртуальное окружение...
if not exist venv\Scripts\python.exe python -m venv venv
call venv\Scripts\python.exe -m pip install -U pip >nul

echo [2/5] Зависимости (первый раз ~2.5 ГБ: torch CUDA, gigaam)...
echo     PyTorch CUDA (cu130)...
call venv\Scripts\pip install torch==2.14.0 torchaudio==2.11.0 --extra-index-url https://download.pytorch.org/whl/cu130
if errorlevel 1 (
  echo [ОШИБКА] torch CUDA (cu130) не встал.
  echo Если старый драйвер GPU, повтори вручную с cu126:
  echo   venv\Scripts\pip install torch==2.14.0 torchaudio==2.11.0 --extra-index-url https://download.pytorch.org/whl/cu126
  pause
  exit /b 1
)
call venv\Scripts\python.exe -c "import torch; print('  CUDA доступен:', torch.cuda.is_available())"
echo     Остальные пакеты...
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

echo [5/5] Модели не скачиваются при установке.
echo Запусти web-интерфейс и выбери GigaAM и Qwen в разделе «Настройки моделей».
echo.
echo Готово! Дальше:
echo   - перетащи видео на scripts\windows\process.bat, ИЛИ
echo   - запусти scripts\windows\watch.bat и кидай видео в папку runtime\in\
pause
