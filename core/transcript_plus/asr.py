"""Local quality decoding, matching FABO's quality profile (no silent fallback)."""
from contextlib import contextmanager
import importlib
import sys
from types import SimpleNamespace

from . import hardware
from .errors import AppError

PROFILES = ("quality", "balanced", "fast")
CT2_BEAM = {"quality": 5, "balanced": 3, "fast": 1}
MAX_GLOSSARY = 4000


def plain_path(value):
    r"""Strip the Windows extended-length prefix; CTranslate2 cannot open model.bin through \\?\ paths."""
    value = str(value)
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    return value[4:] if value.startswith("\\\\?\\") else value


def parameters(engine, language="", word_timestamps=False, profile="quality", glossary=""):
    """Decode settings. quality = FABO quality profile; balanced/fast trade accuracy for speed."""
    if profile not in PROFILES:
        raise AppError("INVALID_INPUT", "不支援的轉錄方案。")
    common = dict(language=language or None, task="transcribe", temperature=0,
                  condition_on_previous_text=profile != "fast", word_timestamps=word_timestamps)
    terms = (glossary or "").strip()
    if terms:
        if len(terms) > MAX_GLOSSARY:
            raise AppError("INVALID_INPUT", f"術語表不得超過 {MAX_GLOSSARY} 字元。")
        common["initial_prompt"] = terms
    if engine == "mlx":
        return {**common, "fp16": True}
    return {**common, "beam_size": CT2_BEAM[profile], "vad_filter": False,
            "vad_parameters": {"min_silence_duration_ms": 1000, "speech_pad_ms": 400}}


def runtime_options(engine, profile="quality", word_timestamps=False):
    """Non-decode switches. MLX fused attention is faster but cannot produce word timestamps."""
    return {"mlx_fast_attention": engine == "mlx" and profile in ("balanced", "fast") and not word_timestamps}


def review_reasons(source):
    """Flag low-confidence segments the way FABO does so reviewers can find them."""
    reasons = []
    for key, threshold, high, reason in (("avg_logprob", -1, False, "語音文字信心偏低"),
                                         ("no_speech_prob", .6, True, "可能無語音"),
                                         ("compression_ratio", 2.4, True, "文字可能重複")):
        value = source.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and (value > threshold if high else value < threshold):
            reasons.append(reason)
    return reasons


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


def transcribe(audio, model, settings, *, progress=None, runtime=None):
    engine = model.get("engine", "faster-whisper")
    path = plain_path(model["path"])
    try:
        if engine == "mlx":
            import mlx_whisper
            from faster_whisper.audio import decode_audio
            from .mlx_attention import attention_scope
            # Use the same decoder/sample clock as FABO; don't invoke a shell decoder.
            samples = decode_audio(str(audio), sampling_rate=16000)
            fast = (runtime or {}).get("mlx_fast_attention", False)
            with mlx_progress(progress), attention_scope(fast, settings.get("word_timestamps", False)):
                result = mlx_whisper.transcribe(samples, path_or_hf_repo=path, verbose=None, **settings)
            return iter(result["segments"]), result.get("language", settings["language"] or "zh")
        from faster_whisper import WhisperModel
    except ImportError as exc:
        print(f"ASR runtime import failed: {exc}", file=sys.stderr)
        if isinstance(exc, ModuleNotFoundError):
            raise AppError("RUNTIME_MISSING", "安裝包缺少所選模型的轉錄引擎，請重新安裝完整版本。") from None
        raise AppError("RUNTIME_LOAD_FAILED", "轉錄引擎已安裝，但 GPU 運算檔或相依函式庫無法載入，請更新完整安裝包。") from None
    return ct2_segments(WhisperModel, path, audio, settings, progress)


def ct2_segments(model_class, path, audio, settings, progress):
    """Use CUDA when CTranslate2 sees a GPU, otherwise the physical cores. A broken CUDA stack falls back to CPU."""
    runtimes = [hardware.ct2_runtime()]
    if runtimes[0]["device"] == "cuda":
        runtimes.append(hardware.ct2_runtime(prefer_cuda=False))
    for index, runtime in enumerate(runtimes):
        try:
            decoder = model_class(path, local_files_only=True, **runtime)
            if progress is not None:
                progress(0)
            output, info = decoder.transcribe(str(audio), **settings)
            # The generator is lazy: missing cuBLAS/cuDNN only fails once decoding starts.
            iterator = iter(output)
            first = next(iterator, None)
            break
        except Exception as exc:
            if index == len(runtimes) - 1:
                raise
            print(f"CUDA 不可用，改用 CPU：{exc}", file=sys.stderr, flush=True)

    def segments():
        for s in _chain(first, iterator):
            yield {"start": s.start, "end": s.end, "text": s.text, "avg_logprob": getattr(s, "avg_logprob", None),
                   "no_speech_prob": getattr(s, "no_speech_prob", None), "compression_ratio": getattr(s, "compression_ratio", None),
                   "words": [{"start": w.start, "end": w.end, "word": w.word, "probability": w.probability}
                             for w in s.words or []]}
    return segments(), info.language


def _chain(first, rest):
    if first is not None:
        yield first
    yield from rest
