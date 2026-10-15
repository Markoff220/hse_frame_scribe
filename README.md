# VideoNotes

VideoNotes превращает видео в Markdown-конспект для Obsidian. Приложение извлекает звук, распознаёт речь, выбирает важные кадры и собирает выжимку с помощью локальных моделей.

Для каждого видео создаются `конспект.md`, полная `транскрипция.md` и папка `кадры/`.

## Готовые приложения

В релизах доступны самостоятельные дистрибутивы для Linux, Windows и macOS. В них не входят Python, модели, FFmpeg и Ollama: Python и зависимости PyApp установит при первом запуске, а FFmpeg, Ollama и модели устанавливаются на компьютере пользователя.

| ОС | Архив | Архитектура | Установка | Данные приложения |
| --- | --- | --- | --- | --- |
| Linux | `VideoNotes-linux-x86_64.tar.gz` | x86_64 | `./install.sh` | `${XDG_DATA_HOME:-~/.local/share}/VideoNotes` |
| Windows | `VideoNotes-windows-x86_64.zip` | x86_64 | `install.ps1` | `%LOCALAPPDATA%\VideoNotes` |
| macOS | `VideoNotes-macos-<arch>.zip` | arm64 или x86_64 | `./install.sh` | `~/Library/Application Support/VideoNotes` |

Во всех вариантах результаты, настройки, загрузки, логи и веса GigaAM хранятся в каталоге данных приложения. Модели Ollama хранятся в каталоге, настроенном самой Ollama.

### Перед установкой

Установите системные зависимости для своей ОС:

| ОС | FFmpeg | Ollama |
| --- | --- | --- |
| Linux | пакет `ffmpeg` из репозитория дистрибутива | [страница загрузки](https://ollama.com/download/linux) |
| Windows | [страница загрузки](https://ffmpeg.org/download.html), добавьте `ffmpeg` в `PATH` | [страница загрузки](https://ollama.com/download/windows) |
| macOS | `brew install ffmpeg` | [страница загрузки](https://ollama.com/download/mac) |

При первом запуске откройте в приложении «Настройки моделей», выберите и скачайте ASR, VLM и LLM. Указаны точные размеры файлов в каталогах GigaAM и Ollama на момент релиза; фактическое место на диске может быть немного больше из-за служебных данных Ollama.

| Роль | Модель | Размер загрузки |
| --- | --- | --- |
| Распознавание речи | `v3_e2e_rnnt` | 449,2 МБ |
| Распознавание речи | `v3_e2e_ctc` | 442,6 МБ |
| Распознавание речи | `v3_ctc` | 441,7 МБ |
| Анализ кадров | `qwen2.5vl:3b` | 3,2 ГБ |
| Анализ кадров | `qwen2.5vl:7b` | 6,0 ГБ |
| Конспект | `qwen2.5:3b` | 1,9 ГБ |
| Конспект | `qwen2.5:7b` | 4,7 ГБ |
| Конспект | `qwen2.5:14b-instruct-q4_K_M` | 9,0 ГБ |

Для обработки без GPU подойдут `qwen2.5vl:3b` и `qwen2.5:3b`; для GPU с 11 ГБ VRAM или больше рекомендуются `qwen2.5vl:7b` и `qwen2.5:14b-instruct-q4_K_M`.

### Linux x86_64

```bash
tar -xzf VideoNotes-linux-x86_64.tar.gz
cd VideoNotes-linux-x86_64
./install.sh
videonotes
```

Установщик поместит launcher в `~/.local/bin/videonotes` и добавит приложение в меню рабочего стола. Если команда `videonotes` не найдена, добавьте `~/.local/bin` в `PATH` или перезапустите сеанс.

### Windows x86_64

Распакуйте `VideoNotes-windows-x86_64.zip`, откройте PowerShell в распакованной папке и выполните:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Приложение появится в меню «Пуск». Launcher устанавливается в `%LOCALAPPDATA%\VideoNotes\bin\videonotes.exe`.

### macOS

Скачайте архив, соответствующий архитектуре Mac: `arm64` для Apple Silicon или `x86_64` для Intel. Затем выполните:

```bash
cd VideoNotes-macos-<arch>
./install.sh
```

Установщик скопирует `VideoNotes.app` в `/Applications` и запустит его. Архивы, собранные без Apple Developer ID, macOS может заблокировать при первом открытии. В таком случае подтвердите запуск в «Системные настройки → Конфиденциальность и безопасность».

## Использование

1. Откройте VideoNotes.
2. В «Настройки моделей» скачайте модели для выбранного режима: для транскрибации нужна только GigaAM, для полной обработки — также VLM и LLM. Режим «Только аудио» работает без моделей.
3. Выберите режим и загрузите видео или вставьте ссылку на запись МТС Линк.
4. Нажмите «Запустить» у созданной задачи.
5. Скачайте готовый конспект, транскрипцию, WAV или MP4 после завершения обработки.

Задачи обрабатываются по одной. В режиме «Транскрибация» создаётся `транскрипция.md` с абзацами и таймкодами без кадров и Ollama; «Только аудио» извлекает `audio.wav`. Результаты находятся в каталоге данных приложения, в `output/<имя-видео>/`.

## Записи МТС Линк

Вместо файла можно вставить ссылку на запись из адресной строки:

```
https://my.mts-link.ru/12345678/987654321/record-new/123456789/record-file/1234567890
https://my.mts-link.ru/12345678/987654321/record-new/123456789
https://my.mts-link.ru/j/12345678/987654321/record-new/123456789/<токен публичной ссылки>
```

Подходят `my.mts-link.ru`, `hse.mts-link.ru` и другие поддомены. После «Запустить» VideoNotes скачивает куски записи, склеивает их в MP4 и запускает выбранный режим. Склейка берёт демонстрацию экрана как картинку (без камер поверх неё, чёрный кадр, когда экрана нет) и смешивает звук всех микрофонов, ставя каждый кусок на своё время. Режим «Только видео» сохраняет MP4 без обработки. Видео кладётся в папку результата как `запись.mp4`; если обработка упала, его всё равно можно скачать из карточки задачи.

Закрытой записи нужен вход: войдите на my.mts-link.ru, откройте F12 → Application → Cookies → `https://my.mts-link.ru` и скопируйте значение cookie `access` (длинная строка на `eyJ`; на старых аккаунтах вместо него `sessionId`). Браузер запоминает его локально, сервер использует только для запроса данных записи и не сохраняет на диск. Это доступ к аккаунту, не передавайте его другим.

Если кусок записи не скачался даже после нескольких попыток, задача останавливается с ошибкой, а не теряет кусок звука молча. Добавьте ссылку ещё раз: скачанные куски лежат в `runtime/tmp/mts_link/` и докачаются с того же места.

Склейка перенесена из форка [lumiragee/mtslinker](https://github.com/lumiragee/mtslinker).

## Сборка дистрибутивов

Каждый пакет нужно собирать нативно на целевой ОС. Скрипты создают wheel приложения, загружают исходный код PyApp `0.29.0`, собирают launcher через Rust/Cargo и помещают архив в `dist/`.

| ОС | Среда сборки | Команда | Результат |
| --- | --- | --- | --- |
| Linux | Linux x86_64, `python3` с `setuptools`, Rust/Cargo, `curl` | `scripts/linux/build-pyapp.sh` | `dist/VideoNotes-linux-x86_64.tar.gz` |
| Windows | Windows x86_64, Python 3.13+ с `setuptools`, Rust/Cargo, PowerShell, `tar` | `.\scripts\windows\build-pyapp.ps1` | `dist\VideoNotes-windows-x86_64.zip` |
| macOS | macOS целевой архитектуры, Python с `setuptools` (Apple Silicon — 3.13+, Intel — 3.12), Xcode Command Line Tools, Rust/Cargo, `curl` | `scripts/macos/build-pyapp.sh` | `dist/VideoNotes-macos-<arch>.zip` |

Для публичного распространения macOS-сборки подпишите и нотарифицируйте `VideoNotes.app` сертификатом Apple Developer ID после сборки. Скрипт не выполняет подпись, так как сертификат и учётные данные издателя не входят в репозиторий.

## Docker

Docker подходит для запуска на сервере или машине разработчика.

```bash
cp .env.example .env
docker compose up -d --build
```

Откройте `http://localhost:8090`, настройте модели и запустите задачу. Для NVIDIA GPU установите NVIDIA Container Toolkit и задайте `ASR_DEVICE=cuda` в `.env`. Для CPU закомментируйте блоки `deploy:` у `ollama` и `pipeline` в `docker-compose.yml`, затем задайте `ASR_DEVICE=cpu`.

## Локальный запуск из исходников

Требуются Python 3.12+ (рекомендуется 3.13; на Intel Mac — 3.12, так как torch 2.2.2 не поддерживает 3.13) и `ffmpeg` в `PATH`; Ollama нужна для полной обработки.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app/pipeline/main.py selftest
.venv/bin/python app/pipeline/main.py process /путь/к/видео.mp4
```

Транскрипция без кадров и Ollama:

```bash
.venv/bin/python app/pipeline/main.py transcribe /путь/к/видео.mp4
```

Скачать запись МТС Линк в `output/<название>/запись.mp4` (значение cookie `access` или `sessionId` можно передать и через переменную `MTS_SESSION_ID`):

```bash
.venv/bin/python app/pipeline/main.py download-mts "https://my.mts-link.ru/.../record-new/..." --session-id ЗНАЧЕНИЕ
```

Только извлечение моно-WAV 16 кГц:

```bash
.venv/bin/python app/pipeline/main.py extract-audio /путь/к/видео.mp4
```

Web-интерфейс без Docker:

```bash
.venv/bin/python app/web.py 8090
```

По умолчанию сервер слушает все сетевые интерфейсы (`0.0.0.0`), так что интерфейс доступен и с других устройств в сети. Чтобы открыть его только на этом компьютере, задайте `VIDEONOTES_HOST=127.0.0.1`.

Для Windows исходников сначала запустите `scripts/windows/setup.bat`, затем:

| Скрипт | Что делает |
| --- | --- |
| `scripts/windows/web.bat` | Запускает веб-интерфейс на `127.0.0.1:8090` и сам открывает браузер. Если сервер уже запущен, просто открывает браузер. Другой порт: `web.bat 8091` |
| `scripts/windows/transcribe.bat` | Перетащите на него одно или несколько видео: для каждого получится `транскрипция.md`, без кадров и Ollama |
| `scripts/windows/process.bat` | Перетащите видео: полная обработка с конспектом |
| `scripts/windows/watch.bat` | Следит за папкой `runtime/in/` и обрабатывает всё, что туда попадёт |

> **GPU на Windows:** `pip install torch` по умолчанию ставит CPU-сборку даже при наличии видеокарты (на Linux сразу идёт CUDA). `setup.bat` ставит torch с `--extra-index-url https://download.pytorch.org/whl/cu130` и показывает `CUDA доступен: True/False`. Если в веб-интерфейсе «Ускорение GPU не обнаружено — работает CPU», а видеокарта есть — переустановите torch вручную:
>
> ```powershell
> .\venv\Scripts\pip uninstall torch torchaudio -y
> .\venv\Scripts\pip install torch==2.14.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
> .\venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"  # должно быть True
> ```
>
> На старых драйверах замените `cu130` на `cu126`. После переустановки перезапустите `app/web.py`.

> **GPU на macOS:** на Apple Silicon ускорение — это MPS (Metal), а не CUDA. Приложение само выбирает устройство: `cuda` → `mps` → `cpu`, в интерфейсе при работе на MPS строка показывает `GPU · Apple Silicon (MPS)`. На Intel Mac GPU-ускорения нет вообще — «работает CPU» ожидаемо. Нюанс установки: у torch 2.14.0 для macOS есть только arm64-колёса, поэтому Intel Mac (`x86_64`) ставит torch 2.2.2 — последнюю версию с x86_64-колёсами (в `requirements.txt` и `pyproject.toml` это уже учтено маркерами `sys_platform == "darwin" and platform_machine == "x86_64"`).

## Как работает

| Этап | Инструмент | Результат |
| --- | --- | --- |
| Извлечение аудио | ffmpeg | Моно-аудио 16 кГц |
| Поиск речи | Silero VAD | Фрагменты речи до 22 секунд |
| Распознавание | GigaAM v3 e2e RNN-T | Транскрипция с таймкодами |
| Выбор кадров | ffmpeg | Смены сцен и интервальные кадры |
| Анализ экрана | Ollama VLM | Описание и важность кадра |
| Конспект | Ollama LLM | Map-reduce выжимка транскрипта и кадров |

## Настройка и диагностика

Локальный режим использует `config/config.json`, Docker - `config/docker.json`. `OLLAMA_URL` и `ASR_DEVICE` переопределяют значения конфигурации, `VIDEONOTES_HOST` задаёт адрес веб-сервера (по умолчанию `0.0.0.0`). Выбор моделей из интерфейса сохраняется в `runtime/tmp/model_settings.json`.

| Проверка | Способ |
| --- | --- |
| Локальный стек | `python app/pipeline/main.py selftest` |
| Статус web-стека | `GET /api/health` |
| Каталог моделей | `GET /api/models` |
| Лог задачи | `runtime/logs/job_<id>.log` |

## API

| Метод | Endpoint | Назначение |
| --- | --- | --- |
| `POST` | `/api/upload` | Загрузить видео |
| `POST` | `/api/mts-link` | Добавить запись МТС Линк: `{url, mode, session_id}` |
| `GET` | `/api/jobs` | Получить очередь и статусы |
| `POST` | `/api/jobs/{id}/start` | Поставить загруженную задачу в очередь |
| `GET` | `/api/jobs/{id}/log` | Получить лог задачи |
| `GET` | `/api/jobs/{id}/download` | Скачать конспект, транскрипцию, WAV или MP4 |
| `GET` | `/api/jobs/{id}/video` | Скачать MP4 записи МТС Линк |
| `GET` | `/api/health` | Проверить ASR, Ollama, GPU и каталог вывода |
| `GET` | `/api/models` | Каталог, установленные и выбранные модели |
| `POST` | `/api/models/pull` | Запустить загрузку модели |
| `PUT` | `/api/settings/models` | Применить скачанный набор моделей |
