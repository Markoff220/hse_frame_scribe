"""ASR: GigaAM v3 e2e RNN-T (официальный пакет salute-developers/GigaAM).

Веса скачиваются с публичного CDN Sber в models/gigaam (первый запуск ~1 ГБ).
Лимит transcribe() — 25 с, поэтому на вход идут VAD-чанки.
"""
import gc
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChunkResult:
    start: float
    end: float
    text: str
    words: list = field(default_factory=list)  # (abs_start, abs_end, text)


class GigaAMASR:
    def __init__(self, cfg: dict, log):
        self.cfg = cfg
        self.log = log
        self.model = None

    def load(self) -> None:
        if self.model is not None:
            return
        import gigaam
        model_dir = Path(self.cfg.get("model_dir", "models/gigaam"))
        if not model_dir.is_absolute():
            from common import ROOT
            model_dir = ROOT / model_dir
        model_dir.mkdir(parents=True, exist_ok=True)
        self.log.info("Загрузка GigaAM %s (первый запуск — скачивание ~1 ГБ)...",
                      self.cfg.get("model", "v3_e2e_rnnt"))
        kwargs = {}
        device = self.cfg.get("device", "auto")
        if device != "auto":
            kwargs["device"] = device
        self.model = gigaam.load_model(
            self.cfg.get("model", "v3_e2e_rnnt"),
            download_root=str(model_dir),
            **kwargs,
        )
        dev = next(self.model.parameters()).device
        self.log.info("Модель загружена, device=%s", dev)

    def transcribe_chunk(self, wav: Path, offset: float) -> ChunkResult:
        """Транскрипция одного чанка <=25 с; таймстемпы слов — абсолютные."""
        res = self.model.transcribe(str(wav), word_timestamps=True)
        words = []
        for w in res.words or []:
            words.append((round(offset + w.start, 3), round(offset + w.end, 3), w.text))
        return ChunkResult(start=offset, end=offset + wav_duration(wav), text=res.text.strip(), words=words)

    def unload(self) -> None:
        if self.model is None:
            return
        del self.model
        self.model = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            self.log.info("Модель ASR выгружена из памяти")
        except Exception:
            pass


def wav_duration(wav: Path) -> float:
    import soundfile as sf
    info = sf.info(str(wav))
    return info.duration