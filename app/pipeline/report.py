"""Отчёт: запись .md-конспекта и полной транскрипции в Obsidian vault."""
import datetime
from pathlib import Path

from common import fmt_ts


def write_transcript(path: Path, title: str, duration: float,
                     lines: list[tuple[float, str]], model_name: str) -> None:
    body = "\n\n".join(f"**[{fmt_ts(t)}]** {text}" for t, text in lines)
    if not body:
        body = "_(речь не обнаружена)_"
    content = f"""# Транскрипция: {title}

- Источник: {path.name}
- Длительность: {fmt_ts(duration)}
- Модель: {model_name}
- Дата: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}

---

{body}
"""
    path.write_text(content, encoding="utf-8")


def write_concept(out_dir: Path, title: str, source_name: str, duration: float,
                  concept_body: str, frames: list[dict], model_name: str,
                  asr_model: str) -> Path:
    """Главный файл: конспект.md. Кадры — вложенные картинки из папки кадры/."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    important = [f for f in frames if f.get("importance") == "высокая"]
    if not important:
        important = [f for f in frames if f.get("importance") == "средняя"][:15]
    frame_md = ""
    if important:
        items = []
        for f in important:
            items.append(f"### [{fmt_ts(f['t'])}]\n![](кадры/{f['file']})\n_{f['desc']}_")
        frame_md = "\n\n## Моменты на экране\n\n" + "\n\n".join(items) + "\n"

    content = f"""---
title: "{title}"
source: "{source_name}"
duration: "{fmt_ts(duration)}"
created: "{now}"
asr: "{asr_model}"
tags:
  - видео-конспект
---

# {title}

> Длительность: {fmt_ts(duration)} · Транскрипция: {asr_model} · Кадров проанализировано: {len(frames)}

{concept_body}
{frame_md}
## Приложения

- [Полная транскрипция](транскрипция.md)
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "конспект.md"
    out.write_text(content, encoding="utf-8")
    return out