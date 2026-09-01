"""Аудио: извлечение из видео, VAD-сегментация, нарезка чанков."""
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
import torch


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def extract_audio(video: Path, out_wav: Path) -> None:
    """Видео -> 16 kHz mono WAV (формат GigaAM)."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_wav)],
        check=True,
    )


def vad_segments(wav: Path, threshold: float = 0.5,
                 min_speech_ms: int = 250, min_silence_ms: int = 500) -> list[tuple[float, float]]:
    """Речевые сегменты [(start_sec, end_sec), ...] через Silero VAD."""
    data, sr = sf.read(str(wav), dtype="float32")
    if sr != 16000:
        raise RuntimeError(f"Ожидался 16 kHz, получен {sr}")
    from silero_vad import get_speech_timestamps, load_silero_vad
    model = load_silero_vad()
    stamps = get_speech_timestamps(
        torch.from_numpy(data), model,
        sampling_rate=16000, threshold=threshold,
        min_speech_duration_ms=min_speech_ms,
        min_silence_duration_ms=min_silence_ms,
        speech_pad_ms=100, return_seconds=True,
    )
    return [(float(s["start"]), float(s["end"])) for s in stamps]


def merge_split_segments(segments: list[tuple[float, float]],
                         max_len: float = 22.0, merge_gap: float = 0.4) -> list[tuple[float, float]]:
    """Склеить близкие сегменты, разрезать длинные (лимит transcribe — 25 с)."""
    if not segments:
        return []
    merged: list[list[float]] = []
    for start, end in segments:
        if merged and start - merged[-1][1] <= merge_gap:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    out: list[tuple[float, float]] = []
    for start, end in merged:
        length = end - start
        if length <= max_len:
            out.append((start, end))
            continue
        n = int(np.ceil(length / max_len))
        step = length / n
        for i in range(n):
            out.append((start + i * step, min(start + (i + 1) * step, end)))
    return out


def cut_wav(src_wav: Path, start: float, end: float, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
         "-i", str(src_wav), "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )