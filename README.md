# VideoNotes

VideoNotes превращает видео в Markdown-конспект для Obsidian: извлекает звук, распознаёт речь, выбирает важные кадры и собирает итоговую выжимку через LLM.

На выходе для каждого видео создаются `конспект.md`, полная `транскрипция.md` и папка `кадры/` с иллюстрациями экранных моментов.

## Как работает

| Этап | Инструмент | Результат |
| --- | --- | --- |
| Извлечение аудио | ffmpeg | Моно-аудио 16 кГц |
| Поиск речи | Silero VAD | Фрагменты речи до 22 секунд |
| Распознавание | GigaAM v3 e2e RNN-T | Транскрипция с таймкодами |
| Выбор кадров | ffmpeg | Смены сцен и кадры через заданный интервал |
| Анализ экрана | Ollama VLM | Описание и важность кадра |
| Конспект | Ollama LLM | Map-reduce выжимка транскрипта и кадров |

## Системные требования

### Рекомендуемый профиль GPU

- Docker Engine и Docker Compose v2.
- NVIDIA GPU с 11 ГБ VRAM или больше. Проверено на RTX 2080 Ti 11 ГБ.
- NVIDIA Container Toolkit на хосте.
- 16 ГБ RAM и не менее 30 ГБ свободного места плюс размер исходных видео.
- Модели занимают место в Docker volume: GigaAM около 1 ГБ, `qwen2.5vl:7b` и `qwen2.5:14b-instruct-q4_K_M` суммарно около 15 ГБ.

### CPU-профиль

- Docker Engine и Docker Compose v2.
- Не менее 8 ГБ RAM и 15 ГБ свободного места плюс видео.
- Используются модели `qwen2.5vl:3b` и `qwen2.5:3b`.
- Обработка заметно медленнее; GPU для GigaAM и Ollama не используется.

### Запуск без Docker

- Python 3.10 или новее.
- `ffmpeg` в `PATH`.
- Ollama для анализа кадров и составления конспекта.
- Для Windows предусмотрены `.bat`-скрипты.

## Быстрый запуск Docker

1. Скопируйте шаблон окружения:

   ```bash
   cp .env.example .env
   ```

   Результаты всегда сохраняются в `./output` рядом с проектом.

2. Для GPU-профиля установите NVIDIA Container Toolkit, затем в `.env` включите:

   ```dotenv
   ASR_DEVICE=cuda
   ```

3. Запустите стек:

   ```bash
   docker compose up -d --build
   ```

4. Откройте `http://localhost:8090`, перейдите в «Настройки моделей», скачайте и примените ASR, VLM и LLM. Затем загрузите видео и нажмите «Запустить».

Ollama поднимается внутри стека, но модели не скачиваются при сборке или запуске Compose. Веса GigaAM и Qwen загружаются только по явному действию в веб-интерфейсе и сохраняются в Docker volumes.

### CPU-режим Docker

1. В `docker-compose.yml` закомментируйте блоки `deploy:` у сервисов `ollama` и `pipeline`.
2. В `.env` задайте:

   ```dotenv
   ASR_DEVICE=cpu
   ```

3. Выполните `docker compose up -d --build`.

## Локальный запуск

### Windows

1. Запустите `scripts/windows/setup.bat`.
2. Перетащите видео на `scripts/windows/process.bat`, либо запустите `scripts/windows/watch.bat` и положите видео в `runtime/in/`.

`watch.bat` переносит успешно обработанные файлы в `runtime/in/processed/`, а завершившиеся ошибкой — в `runtime/in/failed/`.

### Linux и macOS

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app/pipeline/main.py selftest
.venv/bin/python app/pipeline/main.py process /путь/к/видео.mp4
```

Для запуска web-интерфейса без Docker:

```bash
.venv/bin/python app/web.py 8090
```

## Настройка

`config/config.json` используется в локальном режиме, `config/docker.json` — в Docker. Пути в `output.dir` разрешаются относительно корня проекта, а не текущей директории терминала.

| Параметр | Назначение | Значение по умолчанию |
| --- | --- | --- |
| `asr.model` | Модель GigaAM | `v3_e2e_rnnt` |
| `asr.model_dir` | Папка весов ASR | `runtime/models/gigaam` |
| `asr.vad_threshold` | Порог Silero VAD | `0.5` |
| `asr.max_segment_seconds` | Максимальная длина фрагмента ASR | `22` |
| `frames.scene_threshold` | Чувствительность к смене сцен | `0.3` |
| `frames.interval_seconds` | Интервал регулярных кадров | `90` |
| `frames.max_frames` | Лимит выбранных кадров | `100` |
| `frames.width` | Ширина кадра для VLM | `1280` |
| `llm.provider` | Провайдер LLM: `ollama` или `stub` | `ollama` |
| `llm.ollama_url` | Адрес Ollama | зависит от режима |
| `llm.vlm_model` | VLM для кадров | `qwen2.5vl:7b` |
| `llm.llm_model` | LLM для конспекта | `qwen2.5:14b-instruct-q4_K_M` |
| `llm.temperature` | Температура генерации | `0.2` |
| `llm.chunk_words` | Размер блока транскрипта для map-reduce | `2000` |
| `output.dir` | Папка готовых конспектов | `output` в Docker |
| `watch.poll_seconds` | Интервал проверки папки `runtime/in/` | `3` |
| `watch.move_on_success` | Переносить успешно обработанное видео | `true` |

Переменные `.env` переопределяют настройки Docker:

| Переменная | Назначение |
| --- | --- |
| `OLLAMA_URL` | URL Ollama; по умолчанию `http://ollama:11434` внутри стека |
| `ASR_DEVICE` | Устройство GigaAM: `cuda`, `cpu` или `auto` |
| `PORT` | Порт web-интерфейса |
| `PYTORCH_INDEX` | Индекс пакетов PyTorch при сборке образа |

## Результаты и диагностика

Структура результата:

```text
<output>/<имя_видео>/
├── конспект.md
├── транскрипция.md
└── кадры/
```

- Проверка локального стека: `python app/pipeline/main.py selftest`.
- Статус web-стека: `GET /api/health`.
- Каталог и состояние моделей: `GET /api/models`.
- Логи задач: `runtime/logs/job_<id>.log`.
- В интерфейсе загрузка только создаёт задачу; её нужно явно запустить кнопкой «Запустить». Задачи выполняются по одной.
- Выбранные модели сохраняются в `runtime/tmp/model_settings.json`; задача фиксирует их набор при запуске.

## API

| Метод | Endpoint | Назначение |
| --- | --- | --- |
| `POST` | `/api/upload` | Загрузить видео |
| `GET` | `/api/jobs` | Получить очередь и статусы |
| `POST` | `/api/jobs/{id}/start` | Поставить загруженную задачу в очередь |
| `GET` | `/api/jobs/{id}/log` | Получить лог задачи |
| `GET` | `/api/jobs/{id}/download` | Скачать готовый конспект |
| `GET` | `/api/health` | Проверить ASR, Ollama, GPU и каталог вывода |
| `GET` | `/api/models` | Каталог, установленные и выбранные модели |
| `POST` | `/api/models/pull` | Запустить загрузку модели |
| `PUT` | `/api/settings/models` | Применить скачанный набор моделей |
