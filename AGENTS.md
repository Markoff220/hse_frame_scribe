# VideoNotes

Видео обрабатывается цепочкой `ffmpeg -> Silero VAD -> GigaAM -> кадры/VLM -> map-reduce LLM`; готовые материалы сохраняются в `output/<имя-видео>/`.

## Точки входа
- CLI: `python app/pipeline/main.py process <video>`, `watch`, `selftest` и `download-mts <public-url>`. Логи CLI: `runtime/logs/run_*.log`.
- Web: `python app/web.py [port]` (8090 по умолчанию). Загрузка создаёт задачу `uploaded`; для видео необходим отдельный `POST /api/jobs/{id}/start`. Очередь обслуживает один поток.
- `app/pipeline/main.py` связывает все стадии; `app/web.py` вызывает его `process_video()`. UI находится в `app/web/index.html`.
- Публичная МТС Линк-задача сразу встаёт в очередь и сохраняет URL лишь во внутреннем `jobs.json`; не включайте `source_url` в API-ответы.

## Конфигурация и пути
- `common.ROOT` ищет вверх каталог с `config/config.json` или `config/docker.json`; все runtime-пути вычисляйте от `ROOT`, а не от CWD. Относительный `output.dir` также разрешается от `ROOT`.
- Локально используется `config/config.json`; контейнер устанавливает `VIDEONOTES_CONFIG=/app/config/docker.json`. `OLLAMA_URL`, `VLM_MODEL`, `LLM_MODEL` и `ASR_DEVICE` переопределяют значения конфигурации.
- Модули из `app/pipeline/` импортируются как топовые (`import common`, `import frames`): точки входа вручную добавляют этот каталог в `sys.path`. Не переводите их на `pipeline.*` без согласованной переработки запуска и Dockerfile.
- `runtime/tmp/` содержит uploads и персистентное состояние очереди `jobs.json`; при рестарте задачи `running` становятся `error`. Веса GigaAM: `runtime/models/gigaam`; логи web/job: `runtime/logs/`.
- ASR получает VAD-чанки максимум 22 с (`asr.max_segment_seconds`), поскольку GigaAM ограничивает транскрипцию 25 с.

## Запуск и проверка
- Локальная среда: Python >=3.10 и `ffmpeg`/`ffprobe` в `PATH`; Linux/macOS: `.venv/bin/pip install -r requirements.txt`.
- `selftest` загружает около 1 ГБ весов GigaAM при первом запуске и проверяет Ollama. Для обычного режима нужны Ollama и обе настроенные модели; `llm.provider: "stub"` отключает эту зависимость для отладки.
- Docker: `docker compose up -d --build`. Сервисы `ollama-init` предварительно скачивает модели, а `pipeline` ждёт его завершения. GPU-блоки `deploy` требуют NVIDIA Container Toolkit; для CPU их нужно закомментировать.
- `requirements.txt` не содержит `pytest` и `httpx`: перед тестами установите их отдельно. Из корня: `PYTHONPATH=app python -m pytest app/tests/`; отдельный API-тест: `PYTHONPATH=app python -m pytest app/tests/test_manual_start.py -q`.
- CI, линтер, typecheck и форматтер в репозитории не настроены.

## Язык
- Пользовательские тексты, логи и промпты проекта пишутся по-русски.
