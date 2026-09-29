import json
import os
from pathlib import Path
import shutil
import time

from . import __version__, domain, models
from .errors import AppError, require
from .jobs import JobRunner
from .media import file_hash, probe
from .storage import Store


class Service:
    def __init__(self, root, run_jobs=True):
        self.store = Store(root)
        self.runner = JobRunner(self.store)
        if run_jobs:
            self.runner.start()

    def shutdown(self):
        self.runner.shutdown()

    def dispatch(self, method, p):
        if method == "app.status":
            return {"version": __version__, "data_dir": str(self.store.root), "models": models.status(self.store)}
        if method == "project.list":
            return self.store.projects()
        if method == "project.get":
            return self.get_project(p["project_id"])
        if method == "project.import":
            return self.import_media(p["path"])
        if method == "model.configure":
            model = models.inspect_model(p["path"])
            self.store.set_setting("asr_model", model)
            return models.status(self.store)
        if method == "job.list":
            return self.store.jobs()
        if method == "job.start":
            return self.runner.enqueue(p["project_id"], p.get("language", "zh"))
        if method == "job.cancel":
            return self.runner.cancel(p["job_id"])
        if method == "job.retry":
            with self.store.connection() as db:
                old = db.execute("SELECT * FROM jobs WHERE id=?", (p["job_id"],)).fetchone()
            require(old, "NOT_FOUND", "找不到工作。")
            return self.runner.enqueue(old["project_id"], json.loads(old["parameters"])["language"], old["id"])
        if method == "transcript.edit":
            project = self.store.project(p["project_id"])
            require(project["transcript"], "NOT_READY", "請先完成轉錄。")
            doc = domain.edit_segment(project["transcript"], p["segment_id"], p["text"], p.get("speaker"))
            self.store.save_transcript(project["id"], p["expected_revision"], doc)
            return self.get_project(project["id"])
        if method == "transcript.restore":
            with self.store.connection() as db:
                row = db.execute("SELECT transcript FROM history WHERE project_id=? AND revision=?", (p["project_id"], p["target_revision"])).fetchone()
                require(row, "NOT_FOUND", "找不到要復原的版本。")
                self.store.save_transcript(p["project_id"], p["expected_revision"], json.loads(row[0]), db)
            return self.get_project(p["project_id"])
        if method.startswith("caption."):
            return self.caption(method, p)
        if method == "export.render":
            project = self.store.project(p["project_id"])
            require(project["revision"] == p["expected_revision"], "REVISION_CONFLICT", "匯出前內容已更新，請重新載入。")
            return {"content": domain.export_content(project, p["format"]), "filename": f'{project["title"]}.{p["format"]}'}
        raise AppError("UNKNOWN_METHOD", "不支援的操作。")

    def get_project(self, project_id):
        project = self.store.project(project_id)
        project["media_path"] = str(self.store.root / project["media_path"])
        project["warnings"] = domain.caption_warnings(project["captions"], project["duration_ms"]) if project["captions"] else []
        return project

    def import_media(self, path):
        source = Path(path).resolve(strict=True)
        info = probe(source)
        required = source.stat().st_size + info["duration_ms"] * 32 + 128*1024**2
        require(shutil.disk_usage(self.store.root).free >= required, "DISK_FULL", "磁碟空間不足以匯入與產生音訊。")
        project_id = domain.uid()
        folder = self.store.root / "projects" / project_id / "original"
        folder.mkdir(parents=True)
        destination = folder / ("source"+source.suffix.lower())
        try:
            shutil.copyfile(source, destination.with_suffix(destination.suffix+".partial"))
            destination.with_suffix(destination.suffix+".partial").replace(destination)
            digest = file_hash(destination)
            # Validate copied bytes, not just an original file that may have changed mid-copy.
            info = probe(destination)
            with self.store.connection() as db:
                now = time.time()
                db.execute("""INSERT INTO projects(id,title,filename,media_path,media_hash,duration_ms,media_info,created,updated)
                    VALUES (?,?,?,?,?,?,?,?,?)""", (project_id, source.stem[:120], source.name,
                    str(destination.relative_to(self.store.root)), digest, info["duration_ms"], json.dumps(info), now, now))
        except Exception:
            shutil.rmtree(folder.parent)
            raise
        return self.get_project(project_id)

    def caption(self, method, p):
        project = self.store.project(p["project_id"])
        require(project["transcript"], "NOT_READY", "請先完成轉錄。")
        if method == "caption.generate":
            # Explicit replace flag prevents silent destruction of manual edits.
            require(not project["captions"] or p.get("replace") is True,
                    "CONFIRM_REPLACE", "重新產生會取代目前字幕的拆句與時間設定。")
            track = domain.make_captions(project["transcript"], p.get("max_chars", 18))
        else:
            require(project["captions"] and not project["captions_stale"], "STALE_CAPTIONS", "字幕已過期，請先重新產生。")
            track = project["captions"]
            if method == "caption.split":
                track = domain.split_cue(track, project["transcript"], p["cue_id"], p["offset"], p.get("manual_ms"))
            elif method == "caption.merge":
                track = domain.merge_cue(track, p["cue_id"])
            elif method == "caption.time":
                cue = next((c for c in track["cues"] if c["id"] == p["cue_id"]), None)
                require(cue is not None, "NOT_FOUND", "找不到字幕。")
                require(domain.valid_time(p["start_ms"], p["end_ms"], project["duration_ms"]), "INVALID_TIMING", "字幕時間超出影音範圍。")
                cue.update(start_ms=p["start_ms"], end_ms=p["end_ms"], timing_status="manual", manual_override=True)
            else:
                raise AppError("UNKNOWN_METHOD", "不支援的字幕操作。")
        self.store.save_captions(project["id"], p["expected_revision"], track, p.get("expected_track_revision"))
        return self.get_project(project["id"])
