# AGENTS.md — VideoNotes

Видео → .md нейроконспект: ffmpeg → Silero VAD → GigaAM ASR → кадры + Ollama VLM → map-reduce конспект (Ollama LLM).
Проект — Git-репозиторий, результаты хранятся в `output/` внутри корня проекта.

## Структура
- `app/pipeline/` — ядро: `main.py` (CLI: `process <video>` / `watch` / `selftest`), `common.py` (конфиг, ROOT), `audio.py`, `asr.py`, `frames.py`, `vlm.py` (Ollama-клиент + StubLLM), `summarize.py`, `report.py`.
- `app/web.py` — FastAPI-сервис (один worker-поток, очередь задач); UI — `app/web/index.html`.
- `app/tests/` — тесты; запускать из корня (`conftest.py` кладёт `app/` в `sys.path`).
- Корень: докер-файлы (`Dockerfile`, `docker-compose.yml`, `.env`, `.dockerignore`) и `requirements.txt`; конфиги — в `config/`, Windows-скрипты — в `scripts/windows/`, runtime-данные — в `runtime/`.
- `config/config.json` — локальный конфиг; `config/docker.json` — для контейнера (выбирается переменной `VIDEONOTES_CONFIG`). Переопределения через env: `OLLAMA_URL`, `VLM_MODEL`, `LLM_MODEL`, `ASR_DEVICE`.
- `GET /api/health` — статус стека для панели индикаторов в UI: `asr` (ok/partial/missing по весам в `model_dir`), `vlm`/`llm` (ok/missing/unavailable по `Ollama /api/tags`), `gpu` (torch.cuda), `output_dir` (хостовый путь к папке конспектов, из `OUTPUT_HOST_DIR`).
- `output.dir` разрешается относительно корня проекта (не CWD).
- `runtime/in/` — watch-папка (`processed/`, `failed/`); `runtime/tmp/` — scratch (uploads, `jobs.json`, можно чистить); `runtime/logs/` — `job_<id>.log`, `web_*.log`, `run_*.log`; `runtime/models/gigaam` — веса ASR.

## Команды
- Самопроверка: `python app/pipeline/main.py selftest` (ffmpeg, GigaAM — при первом запуске скачает ~1 ГБ с CDN Sber, кадры, Ollama).
- Одно видео: `python app/pipeline/main.py process <video>`; слежение за `runtime/in/`: `watch`.
- Web локально: `python app/web.py [port]` (по умолчанию 8090).
- Docker: `docker compose up -d --build` — поднимает самодостаточный стек: `ollama` (LLM/VLM-сервер с GPU), `ollama-init` (разовая загрузка моделей 7b/14b), `pipeline` (web). GPU-профиль по умолчанию (`.env`: `ASR_DEVICE=cuda`, модели 7b/14b; блоки `deploy:` в compose). Требуется NVIDIA Container Toolkit на хосте. CPU-профиль — см. комментарии в `.env` и `docker-compose.yml`.
- Тесты: `pytest app/tests/` из корня — pytest и httpx в `requirements.txt` нет, их нужно доустановить (fastapi/uvicorn уже есть); один тест: `pytest app/tests/test_manual_start.py -k manual_start`.
- Lint/typecheck/CI нет.

## Подводные камни
- `ROOT` вычисляется в `app/pipeline/common.py` поиском вверх по дереву папки с `config/config.json` или `config/docker.json`: локально — корень проекта, в контейнере — `/app`. Все пути — от него, не от `app/`.
- Модули `app/pipeline/` импортируются как топовые, не как пакет: `web.py`/`main.py` добавляют `app/pipeline/` в `sys.path` — писать `import common`, а не `import pipeline.common`.
- Ollama крутится в контейнере стека (сервис `ollama`), не на хосте: `pipeline` ходит к нему по `http://ollama:11434`. Если переключиться на хостовый Ollama — `OLLAMA_URL=http://host.docker.internal:11434` (`extra_hosts: host-gateway`). Нет Ollama — стадии 4/5 упадут.
- Веса GigaAM (~1 ГБ) живут в docker-volume `gigaam-models` и переживают пересборку; первый запуск скачивает их с CDN Sber.
- Лимит `transcribe()` GigaAM — 25 с, поэтому на вход идут VAD-чанки ≤ 22 с (`asr.max_segment_seconds`).
- `llm.provider: "stub"` в конфиге — StubLLM, отладка пайплайна без Ollama.
- Web: загрузка НЕ запускает задачу автоматически — явный `POST /api/jobs/{id}/start` («uploaded» → «queued»). Один worker: задачи выполняются последовательно.
- Состояние задач персистится в `runtime/tmp/jobs.json` (после рестарта сервиса «running» → «error»); upload > 8 ГБ отклоняется (413).
- `.env` — для docker compose (текущий профиль: GPU, модели 7b/14b); CPU-профиль и переключение — в комментариях внутри файла.
- Windows-скрипты `.bat` используют `venv\Scripts\python.exe` (ПК); на сервере venv называется `.venv` (Linux) — не путать.
- Весь код, логи, промпты и UI на русском — сохранять.
