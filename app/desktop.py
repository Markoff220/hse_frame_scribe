"""Локальный launcher упакованного VideoNotes."""
import os
import shutil
import threading
import webbrowser
from importlib import resources
from pathlib import Path


def _data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "VideoNotes"


def _prepare_data_dir() -> Path:
    data_dir = _data_dir()
    config_dir = data_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    if not config_path.exists():
        default_config = resources.files("videonotes").joinpath("defaults/config.json")
        with resources.as_file(default_config) as source:
            shutil.copyfile(source, config_path)
    return data_dir


def main() -> None:
    data_dir = _prepare_data_dir()
    os.environ["VIDEONOTES_DATA_DIR"] = str(data_dir)
    os.environ["VIDEONOTES_CONFIG"] = str(data_dir / "config" / "config.json")

    from .web import run

    port = 8090
    threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    run(port=port, host="127.0.0.1")


if __name__ == "__main__":
    main()
