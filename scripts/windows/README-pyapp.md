# VideoNotes для Windows

Распакуйте `VideoNotes-windows-x86_64.zip`, затем в PowerShell выполните:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Приложение появится в меню «Пуск». При первом запуске PyApp скачает Python 3.13 и зависимости. Модели выбираются и скачиваются в разделе «Настройки моделей».

Перед использованием установите:

- [FFmpeg](https://ffmpeg.org/download.html), доступный в `PATH`;
- [Ollama для Windows](https://ollama.com/download/windows).

Данные VideoNotes находятся в `%LOCALAPPDATA%\VideoNotes`, а модели Ollama — в её собственном каталоге.

Для сборки архива на Windows x86_64 требуются Python 3.13+ с `setuptools`, Rust/Cargo, PowerShell и `tar` (входит в современные Windows):

```powershell
.\scripts\windows\build-pyapp.ps1
```
