# VideoNotes для macOS

Распакуйте `VideoNotes-macos-<arch>.zip`, затем выполните:

```bash
cd VideoNotes-macos-<arch>
./install.sh
```

Приложение будет скопировано в `/Applications` и запущено. При первом запуске PyApp скачает Python 3.13 и зависимости. Модели выбираются и скачиваются в разделе «Настройки моделей».

Перед использованием установите:

- `ffmpeg`, например `brew install ffmpeg`;
- [Ollama для macOS](https://ollama.com/download/mac).

Данные VideoNotes находятся в `~/Library/Application Support/VideoNotes`, а модели Ollama — в её собственном каталоге.

Собирать нужно на целевой архитектуре macOS (`arm64` или `x86_64`). Требуются Python 3.13+ с `setuptools`, Xcode Command Line Tools, Rust/Cargo и `curl`:

```bash
scripts/macos/build-pyapp.sh
```
