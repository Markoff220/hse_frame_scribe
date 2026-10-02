"""Отчёт: запись .md-конспекта и полной транскрипции в Obsidian vault."""
import datetime
from pathlib import Path

from common import fmt_ts


def group_paragraphs(segs: list[tuple[float, float, str]], pause: float = 2.0,
                     long_pause: float = 8.0, min_len: float = 15.0,
                     soft_len: float = 45.0, hard_len: float = 120.0) -> list[tuple[float, str]]:
    """Склеивает ASR-чанки [(start, end, text)] в абзацы [(start, text)].

    Новый абзац начинается, если:
      - пауза перед чанком >= long_pause с;
      - пауза >= pause с и абзац уже длиннее min_len с;
      - абзац длиннее soft_len с и предыдущий кусок закончил предложение;
      - абзац длиннее hard_len с (для моделей без пунктуации).
    """
    out: list[tuple[float, str]] = []
    buf: list[str] = []
    cur_start = prev_end = 0.0
    for start, end, text in segs:
        text = text.strip()
        if not text:
            continue
        if buf:
            length = prev_end - cur_start
            gap = start - prev_end
            sentence_end = buf[-1].endswith((".", "?", "!", "…"))
            if (gap >= long_pause
                    or (gap >= pause and length >= min_len)
                    or (length >= soft_len and sentence_end)
                    or length >= hard_len):
                out.append((cur_start, " ".join(buf)))
                buf = []
        if not buf:
            cur_start = start
        buf.append(text)
        prev_end = end
    if buf:
        out.append((cur_start, " ".join(buf)))
    return out


def write_transcript(path: Path, title: str, duration: float,
                     lines: list[tuple[float, str]], model_name: str,
                     source_name: str | None = None) -> None:
    body = "\n\n".join(f"**[{fmt_ts(t)}]** {text}" for t, text in lines)
    if not body:
        body = "_(речь не обнаружена)_"
    content = f"""# Транскрипция: {title}

- Источник: {source_name or path.name}
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