//! SQLite store. Same schema as the Python core (`user_version` 2) so projects can move between platforms.
use rusqlite::Connection;
use std::path::Path;

use crate::error::{err, CoreError, Result};

const SCHEMA_VERSION: i64 = 2;

fn db_err(e: rusqlite::Error) -> CoreError {
    CoreError { code: "DATABASE", message: e.to_string() }
}

pub fn open(path: &Path) -> Result<Connection> {
    let db = Connection::open(path).map_err(db_err)?;
    db.busy_timeout(std::time::Duration::from_secs(10)).map_err(db_err)?;
    db.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;").map_err(db_err)?;
    migrate(&db)?;
    Ok(db)
}

pub fn migrate(db: &Connection) -> Result<()> {
    let version: i64 = db.query_row("PRAGMA user_version", [], |r| r.get(0)).map_err(db_err)?;
    if version > SCHEMA_VERSION {
        return err("DATABASE_VERSION", "資料庫版本較新，請使用新版程式。");
    }
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS projects(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
            media_path TEXT NOT NULL, media_hash TEXT NOT NULL, duration_ms INTEGER NOT NULL,
            media_info TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
            transcript TEXT, captions TEXT, captions_stale INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL, updated REAL NOT NULL,
            speakers TEXT, summary TEXT);
        CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            status TEXT NOT NULL, stage TEXT NOT NULL, attempt INTEGER NOT NULL,
            input_revision INTEGER NOT NULL, parameters TEXT NOT NULL,
            processed_ms INTEGER, error_code TEXT, error TEXT,
            created REAL NOT NULL, started REAL, finished REAL, preview TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs(project_id)
            WHERE status IN ('queued', 'running');
        CREATE TABLE IF NOT EXISTS history(
            project_id TEXT NOT NULL REFERENCES projects(id), revision INTEGER NOT NULL,
            transcript TEXT NOT NULL, created REAL NOT NULL,
            PRIMARY KEY(project_id,revision));
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS people(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS voiceprints(
            id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
            embedding TEXT NOT NULL, quality TEXT NOT NULL, model_hash TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, project_id TEXT, speaker_group TEXT, created REAL NOT NULL);",
    )
    .map_err(db_err)?;
    db.execute_batch(&format!("PRAGMA user_version={SCHEMA_VERSION}")).map_err(db_err)
}

/// Jobs left `running` by a crash or OS kill become `interrupted`; on mobile the OS kills background work routinely.
pub fn recover(db: &Connection, now: f64) -> Result<usize> {
    db.execute(
        "UPDATE jobs SET status='interrupted',error_code='INTERRUPTED',error=?1,finished=?2 WHERE status='running'",
        ("上次執行中斷，請重試；已儲存的逐字稿仍保留。", now),
    )
    .map_err(db_err)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn project(db: &Connection, id: &str) {
        db.execute(
            "INSERT INTO projects(id,title,filename,media_path,media_hash,duration_ms,media_info,created,updated) VALUES(?1,'t','f','p','h',1000,'{}',0,0)",
            [id],
        )
        .unwrap();
    }

    #[test]
    fn migrate_is_idempotent_and_rejects_newer_database() {
        let db = Connection::open_in_memory().unwrap();
        migrate(&db).unwrap();
        migrate(&db).unwrap();
        db.execute_batch("PRAGMA user_version=99").unwrap();
        assert_eq!(migrate(&db).unwrap_err().code, "DATABASE_VERSION");
    }

    #[test]
    fn one_active_job_per_project_and_recover_interrupts_running() {
        let db = Connection::open_in_memory().unwrap();
        migrate(&db).unwrap();
        project(&db, "p1");
        let job = |id: &str, status: &str| {
            db.execute(
                "INSERT INTO jobs(id,project_id,status,stage,attempt,input_revision,parameters,created) VALUES(?1,'p1',?2,'asr',1,0,'{}',0)",
                (id, status),
            )
        };
        job("j1", "running").unwrap();
        assert!(job("j2", "queued").is_err());
        assert_eq!(recover(&db, 1.0).unwrap(), 1);
        let status: String = db.query_row("SELECT status FROM jobs WHERE id='j1'", [], |r| r.get(0)).unwrap();
        assert_eq!(status, "interrupted");
        job("j2", "queued").unwrap();
    }
}
