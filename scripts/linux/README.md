# VideoNotes для Linux

Архив содержит launcher `videonotes` и установщик `install.sh`.

```bash
tar -xzf VideoNotes-linux-x86_64.tar.gz
cd VideoNotes-linux-x86_64
./install.sh
videonotes
```

При первом запуске PyApp скачивает Python 3.13 и разворачивает Python-зависимости. Модели не входят в архив: их выбирают и скачивают в разделе «Настройки моделей».

Перед запуском установите системные зависимости:

- `ffmpeg` из репозитория вашего дистрибутива;
- [Ollama](https://ollama.com/download/linux) для Qwen-моделей.

Данные приложения хранятся в `${XDG_DATA_HOME:-~/.local/share}/VideoNotes`: там находятся результаты, настройки, логи, загрузки и веса GigaAM. Модели Ollama хранятся в каталоге, настроенном самой Ollama.

Для сборки архива на Linux x86_64 требуются `python3` с `setuptools`, Rust/Cargo и `curl`:

```bash
scripts/linux/build-pyapp.sh
```
