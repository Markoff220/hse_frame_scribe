# VideoNotes для macOS

Распакуйте `VideoNotes-macos-<arch>.zip`, затем выполните:

```bash
cd VideoNotes-macos-<arch>
./install.sh
```

Приложение будет скопировано в `/Applications` и запущено. При первом запуске PyApp скачает Python и зависимости (Apple Silicon — Python 3.13, Intel — Python 3.12: у torch 2.2.2, последнего с x86_64-колёсами, нет поддержки 3.13). Модели выбираются и скачиваются в разделе «Настройки моделей».

Перед использованием установите:

- `ffmpeg`, например `brew install ffmpeg`;
- [Ollama для macOS](https://ollama.com/download/mac).

Данные VideoNotes находятся в `~/Library/Application Support/VideoNotes`, а модели Ollama — в её собственном каталоге.

Собирать нужно на целевой архитектуре macOS (`arm64` или `x86_64`). Требуются Python с `setuptools` (Apple Silicon — 3.13+, Intel — 3.12), Xcode Command Line Tools, Rust/Cargo и `curl`:

```bash
scripts/macos/build-pyapp.sh
```
