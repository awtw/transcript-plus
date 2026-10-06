import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from . import hardware, models, speakers
from .asr import PROFILES, parameters, runtime_options
from .domain import make_captions, uid, validate_document
from .errors import AppError, require
from .media import atomic_json, file_hash, process_options
from .processes import terminate_tree

PREVIEW_SEGMENTS = 12


class JobRunner:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.process = None
        self.process_lock = threading.Lock()
        self.active_job = None
        self.thread = threading.Thread(target=self.loop, name="transcript-jobs", daemon=True)

    def start(self):
        self.store.recover()
        self.thread.start()

    def enqueue(self, project_id, language="", retry_of=None, word_timestamps=False, profile="quality",
                diarize=False, speaker_count=None, kind="transcribe"):
        require(language in ("", "zh", "en"), "INVALID_INPUT", "不支援的語言設定。")
        require(type(word_timestamps) is bool and type(diarize) is bool, "INVALID_INPUT", "設定必須為布林值。")
        require(profile in PROFILES, "INVALID_INPUT", "不支援的轉錄方案。")
        require(kind in ("transcribe", "diarize"), "INVALID_INPUT", "不支援的工作類型。")
        require(speaker_count is None or (type(speaker_count) is int and 1 <= speaker_count <= 32),
                "INVALID_INPUT", "講者人數需為 1–32 的整數或留空。")
        project = self.store.project(project_id)
        if kind == "diarize":
            diarize = True
            require(project["transcript"], "NOT_READY", "請先完成轉錄。")
        model = self.store.setting("asr_model")
        if kind == "transcribe":
            require(model and Path(model["path"]).is_dir(), "MODEL_MISSING", "請先在模型設定選擇本機模型。")
            engine = model.get("engine", "faster-whisper")
            require(not (word_timestamps and runtime_options(engine, profile)["mlx_fast_attention"]),
                    "INVALID_INPUT", "詞級時間與快速注意力不可同時開啟，請改用「品質」方案。")
        if diarize:
            speaker_models, available, runtime = models.diarization_ready(self.store)
            require(available, "MODEL_MISSING", "請先在模型設定選擇講者模型資料夾。")
            require(runtime, "RUNTIME_MISSING", "安裝包缺少講者分析元件，請重新安裝完整版本。")
        request = {"language": language, "word_timestamps": word_timestamps, "profile": profile,
                   "diarize": diarize, "speaker_count": speaker_count, "kind": kind}
        stored = {"request": request}
        if kind == "transcribe":
            engine = model.get("engine", "faster-whisper")
            stored.update(language=language, model=model, profile=profile,
                          asr_parameters=parameters(engine, language, word_timestamps, profile, self.store.setting("glossary", "")),
                          runtime=runtime_options(engine, profile, word_timestamps))
        with self.store.connection() as db:
            require(not db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')", (project_id,)).fetchone(),
                    "JOB_ACTIVE", "這個專案已有進行中的工作。")
            if retry_of:
                old = db.execute("SELECT * FROM jobs WHERE id=? AND project_id=?", (retry_of, project_id)).fetchone()
                require(old and old["status"] in ("failed", "interrupted", "cancelled"), "INVALID_STATE", "此工作目前無法重試。")
            attempt = db.execute("SELECT COALESCE(MAX(attempt),0)+1 FROM jobs WHERE project_id=?", (project_id,)).fetchone()[0]
            job_id = uid()
            db.execute("""INSERT INTO jobs(id,project_id,status,stage,attempt,input_revision,parameters,created)
                VALUES (?,?,'queued','queued',?,?,?,?)""", (job_id, project_id, attempt, project["revision"],
                json.dumps(stored), time.time()))
        self.wake.set()
        return {"job_id": job_id}

    def cancel(self, job_id):
        with self.store.connection() as db:
            changed = db.execute("UPDATE jobs SET status='cancelled',finished=? WHERE id=? AND status IN ('queued','running')",
                                 (time.time(), job_id)).rowcount
        require(changed, "INVALID_STATE", "此工作已結束或不存在。")
        with self.process_lock:
            if self.active_job == job_id:
                terminate_tree(self.process)
        return {"cancelled": True}

    def shutdown(self):
        self.stop.set()
        self.wake.set()
        with self.process_lock:
            terminate_tree(self.process)
        if self.thread.is_alive():
            self.thread.join(timeout=6)

    def loop(self):
        while not self.stop.is_set():
            try:
                if self.once():
                    continue
            except Exception as exc:
                print(f"工作排程錯誤：{type(exc).__name__}: {exc}", file=sys.stderr)
            self.wake.wait(1)
            self.wake.clear()

    def once(self):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created,id LIMIT 1").fetchone()
            if not row:
                return False
            job = dict(row)
            db.execute("UPDATE jobs SET status='running',stage='preprocess',started=? WHERE id=?", (time.time(), job["id"]))
        try:
            self.execute(job)
        except Exception as exc:
            error = exc if isinstance(exc, AppError) else AppError("WORKER_CRASHED", "處理失敗，已儲存的內容仍保留；可以重試。")
            if not isinstance(exc, AppError):
                print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            with self.store.connection() as db:
                db.execute("""UPDATE jobs SET status=?,error_code=?,error=?,finished=? WHERE id=? AND status='running'""",
                           ("interrupted" if self.stop.is_set() else "failed", error.code, error.message, time.time(), job["id"]))
        return True

    def execute(self, job):
        project = self.store.project(job["project_id"])
        params = json.loads(job["parameters"])
        artifacts = self.store.root / "artifacts" / project["id"]
        artifacts.mkdir(parents=True, exist_ok=True)
        source = self.store.root / project["media_path"]
        require(file_hash(source) == project["media_hash"], "MEDIA_CHANGED", "專案影音已變更或毀損。")
        request = params.get("request", {})
        task = {**params, "job_id": job["id"], "media_path": str(source), "media_hash": project["media_hash"],
                "duration_ms": project["duration_ms"], "audio_stream": project["media_info"]["audio_stream"],
                "artifact_dir": str(artifacts), "kind": request.get("kind", "transcribe")}
        if request.get("diarize"):
            speaker_models = self.store.setting("speaker_models")
            require(speaker_models, "MODEL_MISSING", "請先在模型設定選擇講者模型資料夾。")
            task["diarization"] = {
                "models": {k: speaker_models[k] for k in ("segmentation", "embedding", "voiceprint") if speaker_models.get(k)},
                "hashes": speaker_models["hashes"], "speaker_count": request.get("speaker_count"),
                "voiceprints": [{k: v[k] for k in ("id", "person_id", "name", "embedding", "model_hash", "quality", "enabled")}
                                for v in self.store.voiceprints(enabled_only=True)]}
        if task["kind"] == "diarize":
            snapshot = artifacts / f'transcript-{job["id"]}.json'
            atomic_json(snapshot, project["transcript"])
            task["transcript_path"] = str(snapshot)
        task_path = artifacts / f'task-{job["id"]}.json'
        atomic_json(task_path, task)
        command = [sys.executable, "--worker", str(task_path)] if getattr(sys, "frozen", False) else [sys.executable, "-m", "transcript_plus", "--worker", str(task_path)]
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
        error = warning = None
        preview, flushed = [], 0.
        with (artifacts / "worker.log").open("w", encoding="utf-8") as log:
            with self.process_lock:
                require(not self.stop.is_set(), "INTERRUPTED", "服務正在關閉。")
                with self.store.connection() as db:
                    status = db.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()[0]
                require(status == "running", "CANCELLED", "工作已取消。")
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8",
                                                env=env, start_new_session=os.name != "nt", **process_options())
                self.active_job = job["id"]
                process = self.process
            try:
                for line in process.stdout:
                    event = json.loads(line)
                    if "error" in event:
                        error = AppError(event["error"]["code"], event["error"]["message"])
                    elif "warning" in event:
                        warning = event["warning"]
                    elif "preview" in event:
                        # Coalesce: the UI polls about once a second, so write at most that often.
                        preview = (preview + [event["preview"]])[-PREVIEW_SEGMENTS:]
                        if time.time() - flushed >= 1:
                            flushed = time.time()
                            with self.store.connection() as db:
                                db.execute("UPDATE jobs SET preview=? WHERE id=? AND status='running'",
                                           (json.dumps(preview, ensure_ascii=False), job["id"]))
                    elif event.get("stage"):
                        with self.store.connection() as db:
                            db.execute("UPDATE jobs SET stage=?,processed_ms=? WHERE id=? AND status='running'",
                                       (event["stage"], event.get("processed_ms"), job["id"]))
                process.wait()
                if error:
                    raise error
                require(process.returncode == 0, "WORKER_CRASHED", "推論程序中斷，請重試。")
            finally:
                terminate_tree(process)
                process.stdout.close()
                with self.process_lock:
                    self.process, self.active_job = None, None
        analysis_path = artifacts / f'analysis-{job["id"]}.json'
        analysis = json.loads(analysis_path.read_text(encoding="utf-8")) if analysis_path.is_file() else None
        if task["kind"] == "diarize":
            require(analysis, "DIARIZATION_FAILED", "講者分析沒有產生結果。")
            return self.finish_diarization(job, project, analysis)
        result = json.loads((artifacts / f'result-{job["id"]}.json').read_text(encoding="utf-8"))
        validate_document(result)
        state = None
        if analysis:
            state = speakers.new_state(analysis["analysis"], analysis.get("speaker_count"))
            speakers.label_segments(result, state, analysis["assignments"])
        with self.store.connection() as db:
            status = db.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()[0]
            if status != "running" or self.stop.is_set():
                return
            self.store.save_transcript(project["id"], job["input_revision"], result, db, speakers=state)
            if state is None:  # A fresh transcript invalidates the previous speaker analysis.
                db.execute("UPDATE projects SET speakers=NULL WHERE id=?", (project["id"],))
            # First transcription generates a track. Re-transcription must not overwrite manual captions.
            if project["captions"] is None:
                track = make_captions(result)
                track["source_revision"] = job["input_revision"]+1
                db.execute("UPDATE projects SET captions=?,captions_stale=0 WHERE id=?", (json.dumps(track, ensure_ascii=False), project["id"]))
            db.execute("UPDATE jobs SET status='completed',stage=?,error=?,finished=? WHERE id=?",
                       ("complete" if result["segments"] else "no_speech", warning, time.time(), job["id"]))
        self.discard_scratch(project["id"], job["id"])

    def finish_diarization(self, job, project, analysis):
        """Apply labels to the newest transcript by segment id, so edits made while analyzing are kept."""
        with self.store.connection() as db:
            status = db.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()[0]
            if status != "running" or self.stop.is_set():
                return
            row = db.execute("SELECT revision,transcript FROM projects WHERE id=?", (project["id"],)).fetchone()
            doc = json.loads(row["transcript"])
            state = speakers.new_state(analysis["analysis"], analysis.get("speaker_count"))
            speakers.label_segments(doc, state, analysis["assignments"])
            self.store.save_transcript(project["id"], row["revision"], doc, db, speakers=state, keep_captions=True)
            db.execute("UPDATE jobs SET status='completed',stage='complete',finished=? WHERE id=?", (time.time(), job["id"]))
        self.discard_scratch(project["id"], job["id"])

    def discard_scratch(self, project_id, job_id):
        """Embeddings and transcript snapshots are large and already stored in the database."""
        for pattern in (f"analysis-{job_id}.json", f"diarization-*{job_id}.json", f"transcript-{job_id}.json"):
            for path in (self.store.root / "artifacts" / project_id).glob(pattern):
                path.unlink(missing_ok=True)
