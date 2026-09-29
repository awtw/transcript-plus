import json
from pathlib import Path
import subprocess
import sys
import time
import wave

import pytest

from transcript_plus.errors import AppError
from transcript_plus.instance import InstanceLock
from transcript_plus.storage import Store


def test_revision_conflict_never_overwrites_new_edit(service):
    params = {"project_id":"p1","expected_revision":1,"segment_id":"segment-a","text":"新的文字"}
    changed = service.dispatch("transcript.edit",params)
    assert changed["revision"] == 2
    with pytest.raises(AppError) as error:
        service.dispatch("transcript.edit",{**params,"text":"舊視窗文字"})
    assert error.value.code == "REVISION_CONFLICT"
    assert service.store.project("p1")["transcript"]["segments"][0]["text"] == "新的文字"


def test_stale_caption_export_requires_explicit_regeneration(service):
    service.dispatch("caption.generate",{"project_id":"p1","expected_revision":1})
    service.dispatch("transcript.edit",{"project_id":"p1","expected_revision":1,"segment_id":"segment-a","text":"下週開會"})
    with pytest.raises(AppError) as error:
        service.dispatch("export.render",{"project_id":"p1","expected_revision":2,"format":"srt"})
    assert error.value.code == "STALE_CAPTIONS"
    with pytest.raises(AppError) as error:
        service.dispatch("caption.generate",{"project_id":"p1","expected_revision":2})
    assert error.value.code == "CONFIRM_REPLACE"
    service.dispatch("caption.generate",{"project_id":"p1","expected_revision":2,"replace":True})
    assert "下週開會" in service.dispatch("export.render",{"project_id":"p1","expected_revision":2,"format":"srt"})["content"]


def test_caption_conflict_and_history_restoration(service):
    track = service.dispatch("caption.generate",{"project_id":"p1","expected_revision":1})["captions"]
    params = {"project_id":"p1","expected_revision":1,"expected_track_revision":track["revision"],"cue_id":track["cues"][0]["id"],"start_ms":900,"end_ms":4000}
    service.dispatch("caption.time",params)
    with pytest.raises(AppError,match="字幕已更新"):
        service.dispatch("caption.time",params)
    service.dispatch("transcript.edit",{"project_id":"p1","expected_revision":1,"segment_id":"segment-a","text":"不同的文字"})
    result = service.dispatch("transcript.restore",{"project_id":"p1","expected_revision":2,"target_revision":1})
    assert result["revision"] == 3 and result["transcript"]["segments"][0]["text"] == "大家好，今天開會。"
    assert result["captions_stale"]


def test_sqlite_persists_and_recovers_only_running(service):
    with service.store.connection() as db:
        for job_id,status in [("a","running"),("b","completed")]:
            db.execute("INSERT INTO jobs(id,project_id,status,stage,attempt,input_revision,parameters,created) VALUES (?,'p1',?,'asr',1,1,'{}',?)",(job_id,status,time.time()))
    again = Store(service.store.root)
    again.recover()
    assert again.project("p1")["revision"] == 1
    states = {j["id"]:j["status"] for j in again.jobs()}
    assert states == {"a":"interrupted","b":"completed"}


def test_single_instance_protects_same_database(tmp_path):
    with InstanceLock(tmp_path):
        with pytest.raises(AppError,match="執行中"):
            with InstanceLock(tmp_path): pass
    with InstanceLock(tmp_path): pass


def test_import_real_wav_copies_original(tmp_path,service):
    path=tmp_path/"中文 空白.wav"
    with wave.open(str(path),'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b'\0\0'*16000)
    project = service.import_media(str(path))
    original = Path(project["media_path"])
    assert original != path and original.read_bytes() == path.read_bytes()
    path.unlink()
    assert original.exists() and project["duration_ms"] == 1000


def test_cancelled_job_cannot_publish_result(service):
    with service.store.connection() as db:
        db.execute("INSERT INTO jobs(id,project_id,status,stage,attempt,input_revision,parameters,created) VALUES ('j','p1','queued','queued',1,1,'{}',?)",(time.time(),))
    service.runner.cancel("j")
    assert not service.runner.once()
    assert service.store.project("p1")["revision"] == 1


def test_requires_local_model_and_rejects_unknown_method(service):
    with pytest.raises(AppError) as error: service.dispatch("job.start",{"project_id":"p1"})
    assert error.value.code == "MODEL_MISSING"
    with pytest.raises(AppError): service.dispatch("shell.execute",{})


def test_json_lines_keeps_stdout_machine_readable(tmp_path):
    requests = [
        {"protocol_version":1,"request_id":1,"method":"project.list","params":{}},
        {"protocol_version":99,"request_id":2,"method":"app.status","params":{}},
        {"protocol_version":1,"request_id":3,"method":"app.status","params":{}},
    ]
    result = subprocess.run([sys.executable,"-m","transcript_plus","--data-dir",str(tmp_path)],
                            input="\n".join(json.dumps(r) for r in requests)+"\n",text=True,capture_output=True,timeout=15)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert [r["request_id"] for r in responses] == [1,2,3]
    assert responses[0]["result"] == []
    assert responses[1]["error"]["code"] == "PROTOCOL_VERSION"
    assert responses[2]["result"]["version"] == "0.1.0"


def test_m4a_playback_copy_is_seekable_cached_and_preserves_original(tmp_path, service):
    import shutil
    if not shutil.which('ffmpeg'):
        pytest.skip('需要 FFmpeg')
    source = tmp_path / '錄音.m4a'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
                    '-c:a', 'aac', str(source)], check=True)
    project = service.import_media(str(source))
    assert not project['media_info']['has_video']
    result = service.dispatch('project.playback', {'project_id': project['id']})
    path = Path(result['media_path'])
    with wave.open(str(path)) as audio:
        assert audio.getframerate() == 16000 and audio.getnchannels() == 1
        assert abs(audio.getnframes() / 16000 - 2) < .1
        audio.setpos(16000)
        assert audio.readframes(100)
    original = Path(project['media_path'])
    assert original.read_bytes() == source.read_bytes()
    modified = path.stat().st_mtime_ns
    assert service.dispatch('project.playback', {'project_id': project['id']}) == result
    assert path.stat().st_mtime_ns == modified
    path.write_bytes(b'broken')
    service.dispatch('project.playback', {'project_id': project['id']})
    with wave.open(str(path)) as audio:
        assert audio.getnframes() > 0
    original.write_bytes(b'changed')
    with pytest.raises(AppError, match='原始錄音已變更'):
        service.dispatch('project.playback', {'project_id': project['id']})
