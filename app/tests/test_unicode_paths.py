"""Модели из папок с кириллицей: на Windows torch.jit и SentencePiece не открывают такие пути сами."""
import io

import pytest

import web  # noqa: F401 — добавляет app/pipeline в sys.path


def test_vad_model_is_loaded_from_bytes(monkeypatch):
    torch = pytest.importorskip("torch")
    pytest.importorskip("silero_vad")
    import audio

    real = torch.jit.load
    seen = []

    def spy(f, *args, **kwargs):
        seen.append(f)
        return real(f, *args, **kwargs)
    monkeypatch.setattr(torch.jit, "load", spy)
    model = audio.load_vad_model()
    assert seen and not isinstance(seen[0], (str, bytes)) and hasattr(seen[0], "read")

    from silero_vad import get_speech_timestamps
    assert get_speech_timestamps(torch.zeros(16000), model, sampling_rate=16000) == []


def test_gigaam_tokenizer_read_by_python(tmp_path, monkeypatch):
    spm = pytest.importorskip("sentencepiece")
    import asr

    # модель учим целиком в памяти: сам тренер SentencePiece на Windows тоже не открывает пути с кириллицей
    buf = io.BytesIO()
    spm.SentencePieceTrainer.train(sentence_iterator=iter(["привет мир это тест токенизатора"] * 50),
                                   model_writer=buf, vocab_size=20, normalization_rule_name="identity",
                                   minloglevel=2)
    model = tmp_path / "Учеба" / "tok.model"
    model.parent.mkdir()
    model.write_bytes(buf.getvalue())
    model = str(model)

    def no_native(self, *a, **k):
        raise RuntimeError("NOT_FOUND: так ведёт себя SentencePiece на Windows с кириллицей")
    monkeypatch.setattr(spm.SentencePieceProcessor, "LoadFromFile", no_native)
    orig = spm.SentencePieceProcessor.load

    with asr._tokenizer_from_bytes():
        sp = spm.SentencePieceProcessor()
        sp.load(model)  # так грузит gigaam.decoding.Tokenizer
        assert len(sp) == 20
    assert spm.SentencePieceProcessor.load is orig
    with pytest.raises(RuntimeError, match="NOT_FOUND"):
        spm.SentencePieceProcessor().load(model)
