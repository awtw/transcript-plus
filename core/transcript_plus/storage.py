from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time

from .errors import require


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            require(version <= 1, "DATABASE_VERSION", "資料庫版本較新，請使用新版程式。")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects(
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
                    media_path TEXT NOT NULL, media_hash TEXT NOT NULL, duration_ms INTEGER NOT NULL,
                    media_info TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    transcript TEXT, captions TEXT, captions_stale INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    status TEXT NOT NULL, stage TEXT NOT NULL, attempt INTEGER NOT NULL,
                    input_revision INTEGER NOT NULL, parameters TEXT NOT NULL,
                    processed_ms INTEGER, error_code TEXT, error TEXT,
                    created REAL NOT NULL, started REAL, finished REAL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs(project_id)
                    WHERE status IN ('queued', 'running');
                CREATE TABLE IF NOT EXISTS history(
                    project_id TEXT NOT NULL REFERENCES projects(id), revision INTEGER NOT NULL,
                    transcript TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(project_id,revision));
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connection(self):
        with self.lock:
            db = sqlite3.connect(self.root / "app.sqlite3", timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def recover(self):
        with self.connection() as db:
            db.execute("UPDATE jobs SET status='interrupted',error_code='INTERRUPTED',error=?,finished=? WHERE status='running'",
                       ("上次執行中斷，請重試；已儲存的逐字稿仍保留。", time.time()))

    def project(self, project_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        require(row is not None, "NOT_FOUND", "找不到專案。")
        value = dict(row)
        for key in ("transcript", "captions", "media_info"):
            value[key] = json.loads(value[key]) if value[key] else None
        value["captions_stale"] = bool(value["captions_stale"])
        return value

    def projects(self):
        with self.connection() as db:
            rows = db.execute("""SELECT id,title,filename,duration_ms,revision,created,updated,
                transcript IS NOT NULL AS has_transcript FROM projects ORDER BY updated DESC""").fetchall()
        return [dict(row) for row in rows]

    def jobs(self):
        with self.connection() as db:
            rows = db.execute("""SELECT j.*, p.title FROM jobs j JOIN projects p ON p.id=j.project_id
                ORDER BY j.created DESC LIMIT 100""").fetchall()
        return [dict(row) for row in rows]

    def setting(self, key, default=None):
        with self.connection() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def save_transcript(self, project_id, expected_revision, doc, db=None):
        if db is None:
            with self.connection() as connection:
                return self.save_transcript(project_id, expected_revision, doc, connection)
        encoded = json.dumps(doc, ensure_ascii=False)
        changed = db.execute("""UPDATE projects SET transcript=?,revision=revision+1,
            captions_stale=CASE WHEN captions IS NULL THEN 0 ELSE 1 END,updated=?
            WHERE id=? AND revision=?""", (encoded, time.time(), project_id, expected_revision)).rowcount
        require(changed == 1, "REVISION_CONFLICT", "內容已更新，請重新載入；您的草稿仍保留。")
        db.execute("INSERT INTO history VALUES (?,?,?,?)", (project_id, expected_revision+1, encoded, time.time()))

    def save_captions(self, project_id, expected_revision, track, expected_track=None):
        with self.connection() as db:
            row = db.execute("SELECT revision,captions FROM projects WHERE id=?", (project_id,)).fetchone()
            require(row and row["revision"] == expected_revision, "REVISION_CONFLICT", "逐字稿已更新，請重新載入。")
            current = json.loads(row["captions"]) if row["captions"] else None
            if expected_track is not None:
                require(current and current["revision"] == expected_track,
                        "REVISION_CONFLICT", "字幕已更新，請重新載入。")
            track["revision"] = (current["revision"]+1) if current else 1
            track["source_revision"] = expected_revision
            db.execute("UPDATE projects SET captions=?,captions_stale=0,updated=? WHERE id=?",
                       (json.dumps(track, ensure_ascii=False), time.time(), project_id))
