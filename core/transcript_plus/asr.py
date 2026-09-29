"""Local quality decoding, matching FABO's quality profile (no silent fallback)."""
from contextlib import contextmanager
import importlib
from types import SimpleNamespace

from .errors import AppError


def parameters(engine, language="", word_timestamps=False):
    common = dict(language=language or None, task="transcribe", temperature=0,
                  condition_on_previous_text=True, word_timestamps=word_timestamps)
    if engine == "mlx":
        return {**common, "fp16": True}
    return {**common, "beam_size": 5, "vad_filter": False,
            "vad_parameters": {"min_silence_duration_ms": 1000, "speech_pad_ms": 400}}


@contextmanager
def mlx_progress(progress):
    """Observe mlx-whisper's frame updates inside this isolated worker only.

    Keep decoding/context unchanged. verbose=None disables upstream tqdm, so
    count updates independently; never print a terminal bar into JSONL stdout.
    mlx-whisper 0.4.x uses only context entry/exit and update on this object.
    """
    if progress is None:
        yield
        return
    module = importlib.import_module("mlx_whisper.transcribe")
    original = module.tqdm
    class FrameProgress:
        def __init__(self, *, total, **kwargs):
            self.total, self.n, self.reported = total, 0, 0
        def __enter__(self):
            progress(0)
            return self
        def update(self, n=1):
            self.n = min(self.total, max(0, self.n + n))
            milliseconds = round(self.n * module.HOP_LENGTH / module.SAMPLE_RATE * 1000)
            if milliseconds > self.reported:
                self.reported = milliseconds
                progress(milliseconds)
        def __exit__(self, exc_type, exc, traceback):
            return False
    module.tqdm = SimpleNamespace(tqdm=FrameProgress)
    try:
        yield
    finally:
        module.tqdm = original


def transcribe(audio, model, settings, *, progress=None):
    engine = model.get("engine", "faster-whisper")
    try:
        if engine == "mlx":
            import mlx_whisper
            from faster_whisper.audio import decode_audio
            # Use the same decoder/sample clock as FABO; don't invoke a shell decoder.
            samples = decode_audio(str(audio), sampling_rate=16000)
            with mlx_progress(progress):
                result = mlx_whisper.transcribe(samples, path_or_hf_repo=model["path"], verbose=None, **settings)
            return iter(result["segments"]), result.get("language", settings["language"] or "zh")
        from faster_whisper import WhisperModel
    except ImportError as exc:
        import sys
        print(f"ASR runtime import failed: {exc}", file=sys.stderr)
        if isinstance(exc, ModuleNotFoundError):
            raise AppError("RUNTIME_MISSING", "安裝包缺少所選模型的轉錄引擎，請重新安裝完整版本。") from None
        raise AppError("RUNTIME_LOAD_FAILED", "轉錄引擎已安裝，但 GPU 運算檔或相依函式庫無法載入，請更新完整安裝包。") from None
    import os
    decoder = WhisperModel(model["path"], device="cpu", compute_type="int8",
                           cpu_threads=min(4, os.cpu_count() or 1), local_files_only=True)
    if progress is not None:
        progress(0)
    output, info = decoder.transcribe(str(audio), **settings)
    def segments():
        for s in output:
            yield {"start": s.start, "end": s.end, "text": s.text,
                   "words": [{"start": w.start, "end": w.end, "word": w.word, "probability": w.probability}
                             for w in s.words or []]}
    return segments(), info.language
