import json
import time

import pytest

from transcript_plus.service import Service


@pytest.fixture
def document():
    return {"schema_version": 1, "duration_ms": 10000, "language": "zh", "segments": [
        {"id": "segment-a", "start_ms": 1000, "end_ms": 4000, "text": "大家好，今天開會。", "raw_text": "大家好，今天開會。",
         "speaker": "", "alignment_status": "valid", "words": [
            {"id": "w1", "text": "大家好，", "start_ms": 1000, "end_ms": 2000, "confidence": None},
            {"id": "w2", "text": "今天", "start_ms": 2100, "end_ms": 2700, "confidence": None},
            {"id": "w3", "text": "開會。", "start_ms": 2900, "end_ms": 4000, "confidence": None}]}
    ]}


@pytest.fixture
def service(tmp_path, document):
    service = Service(tmp_path / "workspace", run_jobs=False)
    with service.store.connection() as db:
        now = time.time()
        db.execute("""INSERT INTO projects(id,title,filename,media_path,media_hash,duration_ms,media_info,created,updated)
            VALUES ('p1','測試會議','meeting.wav','projects/p1/original/source.wav','hash',10000,'{}',?,?)""", (now,now))
    service.store.save_transcript("p1", 0, document)
    yield service
    service.shutdown()
