"""Isolated inference process. No network downloads; stdout is reserved for progress."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from . import hardware, speakers
from .domain import uid, validate_document, lexical
from .errors import AppError, require
from .media import atomic_json, binary, file_hash, process_options


_EMIT = threading.Lock()


def emit(**value):
    with _EMIT:
        print(json.dumps(value, ensure_ascii=False), flush=True)


def merge_overlaps(segments):
    """Models occasionally emit overlapping segments; merge them rather than hand the editor invalid time."""
    result = []
    for segment in segments:
        while result and segment["start_ms"] < result[-1]["end_ms"]:
            previous = result.pop()
            segment = {**segment, "id": previous["id"], "start_ms": min(previous["start_ms"], segment["start_ms"]),
                       "end_ms": max(previous["end_ms"], segment["end_ms"]),
                       "text": (previous["text"] + (" " if previous["text"][-1:].isascii() and previous["text"][-1:].isalnum()
                                                     and segment["text"][:1].isascii() and segment["text"][:1].isalnum() else "")
                                + segment["text"]),
                       "words": previous["words"] + segment["words"],
                       "review_reasons": list(dict.fromkeys(previous["review_reasons"] + segment["review_reasons"] + ["模型時間重疊已合併"]))}
            segment["raw_text"] = segment["text"]
            lexical_words = "".join(w["text"] for w in segment["words"])
            segment["alignment_status"] = "valid" if segment["words"] and lexical(lexical_words) == lexical(segment["text"]) else "incomplete"
        result.append(segment)
    return result


class SpeakerLane:
    """Speaker clustering in its own process so it can overlap ASR and free its memory afterwards."""

    def __init__(self, task, root, audio):
        self.path = root / f'diarization-{task["job_id"]}.json'
        self.spec = {"audio": str(audio), "media_hash": task["media_hash"], "result": str(self.path),
                     **task["diarization"]}
        spec_path = root / f'diarization-task-{task["job_id"]}.json'
        atomic_json(spec_path, self.spec)
        command = [sys.executable, "--diarize", str(spec_path)] if getattr(sys, "frozen", False) \
            else [sys.executable, "-m", "transcript_plus", "--diarize", str(spec_path)]
        env = {**os.environ, "TP_CONCURRENT_STAGES": "1" if task.get("concurrent") else "0", "PYTHONIOENCODING": "utf-8"}
        self.fraction, self.error = 0., None
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                        encoding="utf-8", env=env, **process_options())
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        for line in self.process.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if "progress" in event:
                self.fraction = event["progress"]
            elif "error" in event:
                self.error = event["error"]

    def finish(self, on_progress=None):
        while self.process.poll() is None:
            if on_progress:
                on_progress(self.fraction)
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        self.reader.join()
        if self.process.returncode != 0 or not self.path.is_file():
            raise AppError("DIARIZATION_FAILED", self.error or "講者分析失敗。")
        return json.loads(self.path.read_text(encoding="utf-8"))

    def stop(self):
        # Stays in the worker's process group, so the runner's group kill also reaches it; this is the normal-exit path.
        if self.process.poll() is not None:
            return
        if os.name == "nt":
            from .processes import terminate_tree
            terminate_tree(self.process)
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()


def diarize_main(spec_path):
    """Entry for `--diarize`: cluster speakers across the audio and write the analysis."""
    try:
        from . import diarization
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        samples = diarization.load_samples(spec["audio"])
        last = [-1.]

        def progress(done, total):
            fraction = round(done / max(1, total), 3)
            if fraction != last[0]:
                last[0] = fraction
                emit(progress=fraction)
        result = diarization.analyze(samples, spec["models"], spec["voiceprints"], spec["media_hash"],
                                     speaker_count=spec.get("speaker_count"), progress=progress)
        atomic_json(Path(spec["result"]), result)
        return 0
    except ImportError:
        emit(error="安裝包缺少講者分析元件（sherpa-onnx），請重新安裝完整版本。")
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        emit(error=str(exc) if isinstance(exc, (ValueError, AppError)) else "講者分析失敗，請檢查模型與音訊。")
    return 1


def summarize_transcript(task, root):
    """Start llama-server for this job only, summarize the saved transcript snapshot, then stop it."""
    from . import summary
    config = task["summary"]
    model = config["model"]
    try:
        stat = Path(model["path"]).stat()
        intact = stat.st_size == model["size_bytes"] and stat.st_mtime_ns == model["mtime_ns"]
    except OSError:
        intact = False
    require(intact, "MODEL_CORRUPT", "摘要模型檔案已變更或不存在，請重新選擇。")
    doc = json.loads(Path(task["transcript_path"]).read_text(encoding="utf-8"))
    duration = task["duration_ms"]
    emit(stage="summary_loading", processed_ms=None)
    try:
        with summary.LlamaServer(config["binary"], model["path"], model["alias"], root / "summary-server.log") as client:
            def progress(done, total):
                emit(stage="summary", processed_ms=round(duration * done / max(1, total)))
            progress(0, 1)
            out = summary.summarize(doc["segments"], client, progress)
    except ValueError as exc:
        raise AppError("SUMMARY_FAILED", f"{exc}。可重試；已儲存的逐字稿不受影響。") from exc
    items = summary.attach_sources(out["items"], doc["segments"], uid)
    atomic_json(root / f'summary-{task["job_id"]}.json', {
        "items": items, "chunk_count": out["chunk_count"], "model": model["alias"], "model_sha256": model["sha256"],
        "covered_segments": len(out["covered_segment_indices"]), "total_segments": len(doc["segments"]),
        "quality_status": "unscored"})
    emit(stage="complete", processed_ms=duration)


def execute(task):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    root = Path(task["artifact_dir"])
    root.mkdir(parents=True, exist_ok=True)
    if task.get("kind") == "summary":
        return summarize_transcript(task, root)
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
    diar = task.get("diarization")
    if diar:
        check_models(diar["models"], diar["hashes"])
    if task.get("kind") == "diarize":
        return diarize_existing(task, root, audio, diar)
    emit(stage="model_loading", processed_ms=None)
    model_info = task["model"]
    for name, expected in model_info["files"].items():
        path = Path(model_info["path"]) / name
        require(path.is_file() and file_hash(path) == expected, "MODEL_CORRUPT", "模型檔案已變更或毀損，請重新選擇模型。")
    from .asr import review_reasons, transcribe
    engine = model_info.get("engine", "faster-whisper")
    settings = task["asr_parameters"]
    duration = task["duration_ms"]
    lane = None
    if diar and hardware.concurrent_stages():
        # ASR and speaker clustering use different silicon (GPU/Metal vs CPU) or split the cores between them.
        os.environ["TP_CONCURRENT_STAGES"] = "1"
        lane = SpeakerLane({**task, "concurrent": True}, root, audio)
    try:
        def progress(milliseconds):
            emit(stage="asr", processed_ms=min(duration, max(0, milliseconds)))
        output, language = transcribe(task["media_path"] if engine == "mlx" else audio, model_info, settings,
                                     progress=progress, runtime=task.get("runtime"))
        if engine == "mlx":
            emit(stage="saving", processed_ms=duration)
        segments = []
        for source in output:
            start, end = max(0, round(source["start"]*1000)), min(duration, round(source["end"]*1000))
            if end <= start or not source["text"].strip():
                continue
            words, previous = [], start
            for word in source.get("words", []) or []:
                a, b = round(word["start"]*1000), round(word["end"]*1000)
                if previous <= a < b <= end:
                    words.append({"id": uid(), "text": word["word"], "start_ms": a, "end_ms": b,
                                  "confidence": word.get("probability")})
                    previous = b
            complete = bool(words) and lexical("".join(w["text"] for w in words)) == lexical(source["text"])
            segments.append({"id": uid(), "start_ms": start, "end_ms": end, "text": source["text"].strip(),
                             "raw_text": source["text"].strip(), "speaker": "", "words": words,
                             "alignment_status": "valid" if complete else "incomplete",
                             "review_reasons": review_reasons(source)})
            if engine != "mlx":
                progress(end)
                emit(preview={"start_ms": start, "end_ms": end, "text": source["text"].strip()})
        segments = merge_overlaps(segments)
        doc = {"schema_version": 1, "duration_ms": duration, "language": language,
               "model_hash": model_info["model_hash"], "engine": engine, "asr_parameters": settings,
               "asr_runtime": task.get("runtime"), "segments": segments}
        if diar and segments:
            doc = label_speakers(task, root, audio, doc, lane, diar, split=True)
        emit(stage="saving", processed_ms=duration)
        validate_document(doc)
        atomic_json(root / f'result-{task["job_id"]}.json', doc)
    finally:
        if lane is not None:
            lane.stop()
    emit(stage="complete", processed_ms=duration)


def check_models(models, hashes):
    for key, expected in hashes.items():
        path = Path(models[key])
        require(path.is_file() and file_hash(path) == expected, "MODEL_CORRUPT", "講者模型已變更或毀損，請重新選擇。")


def run_lane(task, root, audio, lane, duration):
    lane = lane or SpeakerLane(task, root, audio)
    try:
        return lane.finish(lambda fraction: emit(stage="diarization", processed_ms=round(fraction * duration)))
    finally:
        lane.stop()


def label_speakers(task, root, audio, doc, lane, diar, split):
    """Speaker clustering failing must not lose a finished transcript; report it and continue unlabeled."""
    duration = task["duration_ms"]
    try:
        emit(stage="diarization", processed_ms=0)
        analysis = run_lane(task, root, audio, lane, duration)
        from . import diarization
        emit(stage="speaker_assign", processed_ms=duration)
        if split and any(s["alignment_status"] == "valid" for s in doc["segments"]):
            doc = speakers.split_segments(doc, analysis["turns"])
        samples = diarization.load_samples(audio)
        spans = [{"start": s["start_ms"] / 1000, "end": s["end_ms"] / 1000} for s in doc["segments"]]
        results = diarization.assign(samples, diar["models"], spans, analysis)
        atomic_json(root / f'analysis-{task["job_id"]}.json',
                    {"analysis": analysis, "assignments": speakers.assignments_for(doc, results),
                     "speaker_count": diar.get("speaker_count")})
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        emit(warning=str(exc) if isinstance(exc, (AppError, ValueError)) else "講者分析失敗，已保留未標講者的逐字稿。")
    return doc


def diarize_existing(task, root, audio, diar):
    """Re-analyze speakers for a finished transcript; labels are keyed by segment id so edits survive."""
    from . import diarization
    doc = json.loads(Path(task["transcript_path"]).read_text(encoding="utf-8"))
    duration = task["duration_ms"]
    emit(stage="diarization", processed_ms=0)
    analysis = run_lane(task, root, audio, None, duration)
    emit(stage="speaker_assign", processed_ms=duration)
    samples = diarization.load_samples(audio)
    spans = [{"start": s["start_ms"] / 1000, "end": s["end_ms"] / 1000} for s in doc["segments"]]
    results = diarization.assign(samples, diar["models"], spans, analysis)
    atomic_json(root / f'analysis-{task["job_id"]}.json',
                {"analysis": analysis, "assignments": speakers.assignments_for(doc, results),
                 "speaker_count": diar.get("speaker_count")})
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
