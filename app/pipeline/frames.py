"""Кадры: детект сцен (ffmpeg scene filter) + страховочный интервал, извлечение JPEG."""
import re
import subprocess
from pathlib import Path

SCENE_RE = re.compile(r"pts_time:(\d+\.?\d*)")


def detect_scenes(video: Path, threshold: float = 0.3) -> list[float]:
    """Время (сек) резких смен кадра. Для лекций/экранов = смена слайдов."""
    cmd = [
        "ffmpeg", "-v", "info", "-i", str(video),
        "-vf", f"select='gt(scene\\,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    times = [float(m) for m in SCENE_RE.findall(proc.stderr)]
    dedup: list[float] = []
    for t in times:
        if not dedup or t - dedup[-1] > 5:
            dedup.append(t)
    return dedup


def plan_frames(duration: float, scene_times: list[float],
                interval: float = 90.0, max_frames: int = 100) -> list[float]:
    """Финальный план кадров: сцены + равномерная сетка, без дублей, с лимитом."""
    candidates = [t for t in scene_times if 2 <= t < duration - 2]
    t = interval / 2
    while t < duration - 2:
        if not any(abs(t - c) < interval / 3 for c in candidates):
            candidates.append(t)
        t += interval
    if not candidates and duration >= 6:
        # короткое видео (< интервала): хотя бы один кадр в середине
        candidates.append(min(5.0, duration / 2))
    candidates = sorted(set(candidates))
    if len(candidates) > max_frames:
        step = len(candidates) / max_frames
        candidates = [candidates[int(i * step)] for i in range(max_frames)]
    return candidates


def extract_frame(video: Path, t: float, out: Path, width: int = 1280) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
             "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out)],
            check=True,
        )
    except subprocess.CalledProcessError:
        return False
    return out.exists() and out.stat().st_size > 1000