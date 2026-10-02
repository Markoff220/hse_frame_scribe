@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

rem Веб-интерфейс VideoNotes: запускает сервер и сам открывает браузер.
rem Сервер слушает только этот компьютер (127.0.0.1). Порт можно передать аргументом: web.bat 8091

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8090"
set "URL=http://127.0.0.1:%PORT%"

if not exist venv\Scripts\python.exe (
  echo Сначала запусти scripts\windows\setup.bat ^(установка зависимостей^)
  pause
  exit /b 1
)

rem Уже запущен в другом окне: просто открываем браузер
powershell -NoProfile -Command "$c = New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', %PORT%); exit 0 } catch { exit 1 } finally { $c.Close() }"
if not errorlevel 1 (
  echo VideoNotes уже запущен: %URL%
  start "" "%URL%"
  exit /b 0
)

echo VideoNotes: %URL%
echo Браузер откроется сам, когда сервер будет готов. Остановить сервер: Ctrl+C или закрыть это окно
echo.

rem Ждём до 2 минут, пока сервер начнёт принимать соединения, и открываем браузер
start "" /b powershell -NoProfile -Command "for ($i = 0; $i -lt 120; $i++) { $c = New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', %PORT%); Start-Process '%URL%'; exit } catch { Start-Sleep -Seconds 1 } finally { $c.Close() } }"

set "VIDEONOTES_HOST=127.0.0.1"
call venv\Scripts\python.exe app\web.py %PORT%
echo.
pause
