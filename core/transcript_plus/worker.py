"""Isolated inference process. No network downloads; stdout is reserved for progress."""
import json
import os
from pathlib import Path
import subprocess
import sys

from .domain import uid, validate_document, lexical
from .errors import AppError, require
from .media import atomic_json, binary, file_hash, process_options


def emit(**value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def execute(task):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    root = Path(task["artifact_dir"])
    root.mkdir(parents=True, exist_ok=True)
    audio = root / "audio.wav"
    marker = root / "preprocess.json"
    binding = {"source_hash": task["media_hash"], "pipeline": "pcm16-mono-v1", "stream": task["audio_stream"]}
    reusable = False
    if marker.is_file() and audio.is_file():
        try:
            cached = json.loads(marker.read_text())
            reusable = cached.get("binding") == binding and cached.get("sha256") == file_hash(audio)
        except (OSError, ValueError):
            pass
    emit(stage="preprocess", processed_ms=None)
    if not reusable:
        partial = root / "audio.partial.wav"
        result = subprocess.run([binary("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", task["media_path"],
                                 "-map", f'0:{task["audio_stream"]}', "-vn", "-ac", "1", "-ar", "16000",
                                 "-c:a", "pcm_s16le", str(partial)], capture_output=True, **process_options())
        require(result.returncode == 0, "UNSUPPORTED_CODEC", "音訊解碼失敗，原檔與先前結果仍保留。")
        partial.replace(audio)
        atomic_json(marker, {"binding": binding, "sha256": file_hash(audio)})
    emit(stage="asr", processed_ms=0)
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise AppError("RUNTIME_MISSING", "尚未安裝本機轉錄引擎。") from None
    model_info = task["model"]
    for name, expected in model_info["files"].items():
        path = Path(model_info["path"]) / name
        require(path.is_file() and file_hash(path) == expected, "MODEL_CORRUPT", "模型檔案已變更或毀損，請重新選擇模型。")
    model = WhisperModel(model_info["path"], device="cpu", compute_type="int8", cpu_threads=min(4, os.cpu_count() or 1),
                         local_files_only=True)
    output, info = model.transcribe(str(audio), language=task.get("language") or None,
                                    beam_size=5, vad_filter=True, word_timestamps=True,
                                    condition_on_previous_text=False)
    segments, duration = [], task["duration_ms"]
    for source in output:
        start, end = max(0, round(source.start*1000)), min(duration, round(source.end*1000))
        if end <= start or not source.text.strip():
            continue
        words, previous = [], start
        for word in source.words or []:
            a, b = round(word.start*1000), round(word.end*1000)
            if previous <= a < b <= end:
                words.append({"id": uid(), "text": word.word, "start_ms": a, "end_ms": b,
                              "confidence": word.probability})
                previous = b
        complete = bool(words) and lexical("".join(w["text"] for w in words)) == lexical(source.text)
        segments.append({"id": uid(), "start_ms": start, "end_ms": end, "text": source.text.strip(),
                         "raw_text": source.text.strip(), "speaker": "", "words": words,
                         "alignment_status": "valid" if complete else "incomplete"})
        emit(stage="asr", processed_ms=end)
    doc = {"schema_version": 1, "duration_ms": duration, "language": info.language,
           "model_hash": model_info["model_hash"], "engine": "faster-whisper", "segments": segments}
    validate_document(doc)
    atomic_json(root / f'result-{task["job_id"]}.json', doc)
    emit(stage="complete", processed_ms=duration)


def main(task_path):
    try:
        execute(json.loads(Path(task_path).read_text(encoding="utf-8")))
        return 0
    except AppError as exc:
        emit(error=exc.payload())
    except MemoryError:
        emit(error={"code": "OUT_OF_MEMORY", "message": "記憶體不足，請關閉其他程式或改用較小模型。"})
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        emit(error={"code": "INFERENCE_FAILED", "message": "本機推論失敗，請檢查模型相容性與音訊。"})
    return 1
