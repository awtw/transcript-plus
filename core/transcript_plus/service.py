import json
import os
from pathlib import Path
import shutil
import time

from . import __version__, diarization, domain, hardware, models, speakers, summary
from .errors import AppError, require
from .jobs import JobRunner
from .media import file_hash, probe, prepare_playback
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
            return {"version": __version__, "data_dir": str(self.store.root), "models": models.status(self.store),
                    "glossary": self.store.setting("glossary", ""),
                    "hardware": {"cores": hardware.physical_cores(), "memory_gb": round(hardware.memory_bytes() / 1024**3),
                                 "cuda": hardware.cuda_device_count() > 0, "apple_silicon": hardware.is_apple_silicon(),
                                 "concurrent_stages": hardware.concurrent_stages()}}
        if method == "project.list":
            return self.store.projects()
        if method == "project.get":
            return self.get_project(p["project_id"])
        if method == "project.playback":
            return prepare_playback(self.store, p["project_id"])
        if method == "project.import":
            return self.import_media(p["path"])
        if method == "model.configure":
            model = models.inspect_model(p["path"])
            self.store.set_setting("asr_model", model)
            return models.status(self.store)
        if method == "model.configure_speakers":
            self.store.set_setting("speaker_models", models.find_speaker_models(p["path"]))
            return models.status(self.store)
        if method == "model.configure_summary":
            self.store.set_setting("summary_model", models.inspect_summary_model(p["path"]))
            return models.status(self.store)
        if method == "summary.start":
            return self.runner.enqueue(p["project_id"], kind="summary")
        if method == "glossary.set":
            text = p.get("text", "")
            require(isinstance(text, str) and len(text.strip()) <= 4000, "INVALID_INPUT", "術語表不得超過 4000 字元。")
            self.store.set_setting("glossary", text.strip())
            return {"glossary": text.strip()}
        if method == "job.list":
            return self.store.jobs()
        if method == "job.start":
            return self.runner.enqueue(p["project_id"], p.get("language", ""), word_timestamps=p.get("word_timestamps", False),
                                       profile=p.get("profile", "quality"), diarize=p.get("diarize", False),
                                       speaker_count=p.get("speaker_count"))
        if method == "job.cancel":
            return self.runner.cancel(p["job_id"])
        if method == "job.retry":
            with self.store.connection() as db:
                old = db.execute("SELECT * FROM jobs WHERE id=?", (p["job_id"],)).fetchone()
            require(old, "NOT_FOUND", "找不到工作。")
            stored = json.loads(old["parameters"])
            request = stored.get("request") or {"language": stored.get("language", ""), "kind": "transcribe",
                                                 "word_timestamps": stored.get("asr_parameters", {}).get("word_timestamps", False)}
            return self.runner.enqueue(old["project_id"], retry_of=old["id"], **request)
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
        if method.startswith("speaker."):
            return self.speaker(method, p)
        if method.startswith("voiceprint."):
            return self.voiceprint(method, p)
        if method.startswith("caption."):
            return self.caption(method, p)
        if method == "export.render":
            project = self.store.project(p["project_id"])
            require(project["revision"] == p["expected_revision"], "REVISION_CONFLICT", "匯出前內容已更新，請重新載入。")
            if p["format"] == "md":
                require(project["summary"] and project["summary"]["source_revision"] == project["revision"], "STALE_SUMMARY",
                        "摘要尚未產生或已過期，請先重新產生。")
                return {"content": summary.to_markdown(project), "filename": f'{project["title"]}-摘要.md'}
            return {"content": domain.export_content(project, p["format"]), "filename": f'{project["title"]}.{p["format"]}'}
        raise AppError("UNKNOWN_METHOD", "不支援的操作。")

    def get_project(self, project_id):
        project = self.store.project(project_id)
        state = project.pop("speakers")
        project["speaker_summary"] = speakers.summary(project["transcript"], state) if state and project["transcript"] else None
        project["media_path"] = str(self.store.root / project["media_path"])
        project["summary_stale"] = bool(project["summary"] and project["summary"]["source_revision"] != project["revision"])
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

    def speaker(self, method, p):
        project = self.store.project(p["project_id"])
        if method == "speaker.analyze":
            return self.runner.enqueue(project["id"], kind="diarize", speaker_count=p.get("speaker_count"))
        state, doc = self.store.project_speakers(project["id"]), project["transcript"]
        require(doc and state, "NOT_READY", "尚未執行講者分析。")
        require(project["revision"] == p["expected_revision"], "REVISION_CONFLICT", "內容已更新，請重新載入。")
        if method == "speaker.rename_group":
            doc, state = speakers.rename_group(doc, state, p["group"], p["name"])
        elif method == "speaker.assign":
            doc = speakers.assign_segment(doc, state, p["segment_id"], p["group"])
        elif method == "speaker.merge":
            doc, state = speakers.merge_groups(doc, state, p["source"], p["target"], project["media_hash"])
            doc, state = speakers.rematch(doc, state, self.store.voiceprints(enabled_only=True))
        elif method == "speaker.rematch":
            ids = p.get("candidate_ids")
            require(ids is None or (isinstance(ids, list) and all(isinstance(i, str) for i in ids)), "INVALID_INPUT", "出席者設定格式不正確。")
            require(p.get("match_mode", "fuzzy") in diarization.MATCH_MODES, "INVALID_INPUT", "比對模式只能是 fuzzy 或 forced。")
            doc, state = speakers.rematch(doc, state, self.store.voiceprints(enabled_only=True), p.get("match_mode", "fuzzy"), ids)
        else:
            raise AppError("UNKNOWN_METHOD", "不支援的講者操作。")
        self.store.save_transcript(project["id"], project["revision"], doc, speakers=state, keep_captions=True)
        return self.get_project(project["id"])

    def voiceprint(self, method, p):
        if method == "voiceprint.list":
            people = {}
            for row in self.store.voiceprints():
                person = people.setdefault(row["person_id"], {"id": row["person_id"], "name": row["name"], "samples": 0,
                                                              "enabled": False, "seconds": 0., "created": row["created"]})
                person["samples"] += 1
                person["enabled"] = person["enabled"] or row["enabled"]
                person["seconds"] += row["quality"].get("duration_seconds", 0.)
            return list(people.values())
        with self.store.connection() as db:
            if method == "voiceprint.rename":
                name = p["name"].strip() if isinstance(p.get("name"), str) else ""
                require(name and len(name) <= 80, "INVALID_INPUT", "姓名需為 1–80 字。")
                db.execute("UPDATE people SET name=? WHERE id=?", (name, p["person_id"]))
            elif method == "voiceprint.delete":
                db.execute("DELETE FROM people WHERE id=?", (p["person_id"],))
            elif method == "voiceprint.enable":
                require(type(p["enabled"]) is bool, "INVALID_INPUT", "設定必須為布林值。")
                db.execute("UPDATE voiceprints SET enabled=? WHERE person_id=?", (int(p["enabled"]), p["person_id"]))
            elif method != "voiceprint.register":
                raise AppError("UNKNOWN_METHOD", "不支援的聲紋操作。")
        if method != "voiceprint.register":
            return self.voiceprint("voiceprint.list", p)
        return self.register_voiceprint(p)

    def register_voiceprint(self, p):
        """Register a person from a speaker group's clean excerpts, then rematch this project."""
        project = self.store.project(p["project_id"])
        state, doc = self.store.project_speakers(project["id"]), project["transcript"]
        require(doc and state, "NOT_READY", "尚未執行講者分析。")
        require(project["revision"] == p["expected_revision"], "REVISION_CONFLICT", "內容已更新，請重新載入。")
        group = p["group"]
        require(speakers.group_is_registrable(doc, group), "STALE_ANALYSIS",
                "此分群有手動移入的段落，語音樣本與成員不一致；請重新分析講者後再註冊。")
        built = diarization.build_voiceprint(project["media_hash"], state["turns"], state["cache"], group,
                                             state["cache"]["binding"]["model_hash"])
        name = (p.get("name") or "").strip()
        existing = self.store.voiceprints()
        with self.store.connection() as db:
            if p.get("person_id"):
                person = db.execute("SELECT * FROM people WHERE id=?", (p["person_id"],)).fetchone()
                require(person, "NOT_FOUND", "找不到這位講者。")
                person_id = person["id"]
            else:
                require(name and len(name) <= 80, "INVALID_INPUT", "請輸入姓名（1–80 字）。")
                person_id = domain.uid()
            require(not any(v["person_id"] == person_id and v["project_id"] == project["id"] and v["speaker_group"] == group
                            for v in existing), "DUPLICATE", "已經從這個專案的這位講者註冊過聲紋。")
            clash = diarization.conflicting_person(built["embedding"], [v for v in existing if v["person_id"] != person_id and v["enabled"]],
                                                state["cache"].get("gates", {}).get("conflict", diarization.MATCH_THRESHOLD))
            require(clash is None, "VOICE_CONFLICT",
                    f"這段聲音與已註冊的「{clash[1] if clash else ''}」過於相似，註冊後會互相干擾；若是同一人，請改選該講者新增樣本。")
            if not p.get("person_id"):
                db.execute("INSERT INTO people VALUES (?,?,?)", (person_id, name, time.time()))
            db.execute("INSERT INTO voiceprints VALUES (?,?,?,?,?,1,?,?,?)",
                       (domain.uid(), person_id, json.dumps(built["embedding"]), json.dumps(built["quality"]),
                        built["model_hash"], project["id"], group, time.time()))
        doc, state = speakers.rematch(doc, state, self.store.voiceprints(enabled_only=True))
        self.store.save_transcript(project["id"], project["revision"], doc, speakers=state, keep_captions=True)
        return self.get_project(project["id"])
