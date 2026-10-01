import json

import numpy as np
import pytest

from transcript_plus import asr, diarization, hardware, speakers
from transcript_plus.errors import AppError
from transcript_plus.worker import merge_overlaps

MODEL = "model-hash"


def unit(*values):
    vector = np.asarray(values, dtype=float)
    return (vector / np.linalg.norm(vector)).tolist()


def turns_for(*spans):
    return [{"start": a, "end": b, "speaker_group": g} for a, b, g in spans]


def make_state(turns, vectors, media_hash="hash", profiles=()):
    cache = {"binding": diarization.cache_binding(media_hash, turns, MODEL), "vectors": vectors}
    groups = diarization.match_groups(cache, list(profiles), MODEL)
    return speakers.new_state({"turns": turns, "groups": groups, "cache": cache, "metrics": {}})


def word(wid, text, a, b):
    return {"id": wid, "text": text, "start_ms": a, "end_ms": b, "confidence": None}


def test_attach_prefers_longest_overlap_and_flags_mixed_segments():
    turns = turns_for((0, 6, "speaker_00"), (6, 10, "speaker_01"))
    result = diarization.attach_turns([{"start": 1, "end": 4}, {"start": 5, "end": 9}], turns, ["speaker_00", "speaker_01"])
    assert [r["speaker_group"] for r in result] == ["speaker_00", "speaker_01"]
    assert [r["needs_confirmation"] for r in result] == [False, True]


def test_attach_uses_nearest_turn_when_no_overlap():
    turns = turns_for((0, 2, "speaker_00"), (8, 10, "speaker_01"))
    result = diarization.attach_turns([{"start": 6, "end": 7}], turns, ["speaker_00", "speaker_01"])
    assert result[0]["speaker_group"] == "speaker_01"


def test_voice_match_needs_agreeing_excerpts_and_margin():
    alice = {"id": "a", "person_id": "A", "name": "Alice", "embedding": unit(1, 0, 0), "model_hash": MODEL,
             "quality": {"preprocessing": diarization.PREPROCESSING}, "enabled": True}
    bob = {**alice, "id": "b", "person_id": "B", "name": "Bob", "embedding": unit(0, 1, 0)}
    vectors = [np.asarray(unit(1, .05, 0)), np.asarray(unit(1, 0, .05))]
    assert diarization.conservative_match(vectors, [alice, bob], MODEL)["speaker_name"] == "Alice"
    assert diarization.conservative_match(vectors[:1], [alice, bob], MODEL)["match_reason"] == "insufficient_consistent_evidence"
    mixed = [np.asarray(unit(1, 0, 0)), np.asarray(unit(0, 1, 0))]
    assert diarization.conservative_match(mixed, [alice, bob], MODEL)["speaker_name"] == ""
    assert diarization.conservative_match(vectors, [{**alice, "model_hash": "other"}], MODEL)["speaker_id"] is None


def test_split_only_at_word_boundaries_between_speakers():
    words = [word("1", "大家好", 0, 1000), word("2", "我是", 1000, 2000), word("3", "小明", 2000, 3000)]
    segment = {"id": "s", "start_ms": 0, "end_ms": 3000, "text": "大家好我是小明", "raw_text": "大家好我是小明",
               "speaker": "", "alignment_status": "valid", "words": words}
    doc = {"segments": [segment]}
    result = speakers.split_segments(doc, turns_for((0, 1.0, "speaker_00"), (1.0, 3.0, "speaker_01")))
    assert [s["text"] for s in result["segments"]] == ["大家好", "我是小明"]
    assert [(s["start_ms"], s["end_ms"]) for s in result["segments"]] == [(0, 1000), (1000, 3000)]
    # A word that straddles two speakers is not divided, and edited text is left alone.
    assert len(speakers.split_segments(doc, turns_for((0, 1.5, "speaker_00"), (1.5, 3, "speaker_01")))["segments"]) == 1
    edited = {"segments": [{**segment, "text": "大家好我是小華"}]}
    assert len(speakers.split_segments(edited, turns_for((0, 1, "speaker_00"), (1, 3, "speaker_01")))["segments"]) == 1


def labelled(service_doc, state, assignments):
    return speakers.label_segments(service_doc, state, assignments)


def build_doc():
    return {"schema_version": 1, "duration_ms": 10000, "segments": [
        {"id": "a", "start_ms": 0, "end_ms": 3000, "text": "第一句", "raw_text": "第一句", "speaker": "", "words": []},
        {"id": "b", "start_ms": 3000, "end_ms": 6000, "text": "第二句", "raw_text": "第二句", "speaker": "", "words": []},
        {"id": "c", "start_ms": 6000, "end_ms": 9000, "text": "第三句", "raw_text": "第三句", "speaker": "", "words": []}]}


def build_state():
    turns = turns_for((0, 3, "speaker_01"), (3, 6, "speaker_00"), (6, 9, "speaker_01"))
    vectors = {"speaker_00": [unit(1, 0, 0)] * 3, "speaker_01": [unit(0, 1, 0)] * 3}
    return make_state(turns, vectors)


def test_names_follow_first_appearance_and_manual_names_are_protected():
    state, doc = build_state(), build_doc()
    assignments = {"a": {"speaker_group": "speaker_01", "needs_confirmation": False},
                   "b": {"speaker_group": "speaker_00", "needs_confirmation": False},
                   "c": {"speaker_group": "speaker_01", "needs_confirmation": True}}
    doc["segments"][2].update(speaker="王經理", speaker_source="manual")
    labelled(doc, state, assignments)
    assert [s["speaker"] for s in doc["segments"]] == ["講者 1", "講者 2", "王經理"]
    renamed, state = speakers.rename_group(doc, state, "speaker_01", "小明")
    assert [s["speaker"] for s in renamed["segments"]] == ["小明", "講者 2", "王經理"]
    moved = speakers.assign_segment(renamed, state, "b", "speaker_01")
    assert moved["segments"][1]["speaker"] == "小明" and moved["segments"][1]["speaker_group_source"] == "manual"
    assert not speakers.group_is_registrable(moved, "speaker_01")
    with pytest.raises(AppError):
        speakers.rename_group(doc, state, "speaker_99", "x")


def test_merge_keeps_registration_cache_valid():
    state, doc = build_state(), build_doc()
    labelled(doc, state, {"a": {"speaker_group": "speaker_01", "needs_confirmation": False},
                          "b": {"speaker_group": "speaker_00", "needs_confirmation": False},
                          "c": {"speaker_group": "speaker_01", "needs_confirmation": False}})
    merged, state = speakers.merge_groups(doc, state, "speaker_00", "speaker_01", "hash")
    assert {s["speaker_group"] for s in merged["segments"]} == {"speaker_01"}
    assert "speaker_00" not in state["groups"]
    assert diarization.valid_cache(state["cache"], diarization.cache_binding("hash", state["turns"], MODEL), ["speaker_01"])
    with pytest.raises(AppError):
        speakers.merge_groups(merged, state, "speaker_01", "speaker_01", "hash")


def test_voiceprint_needs_enough_consistent_clean_speech():
    turns = turns_for((0, 20, "speaker_00"), (20, 40, "speaker_01"))
    good = {"speaker_00": [unit(1, 0, 0)] * 3, "speaker_01": [unit(0, 1, 0)] * 2}
    cache = {"binding": diarization.cache_binding("hash", turns, MODEL), "vectors": good}
    built = diarization.build_voiceprint("hash", turns, cache, "speaker_00", MODEL)
    assert built["quality"]["excerpt_count"] == 3
    with pytest.raises(AppError, match="不足"):
        diarization.build_voiceprint("hash", turns, cache, "speaker_01", MODEL)
    mixed = {"binding": cache["binding"], "vectors": {"speaker_00": [unit(1, 0, 0), unit(0, 1, 0), unit(-1, 0, 0)], "speaker_01": []}}
    with pytest.raises(AppError, match="差異過大"):
        diarization.build_voiceprint("hash", turns, mixed, "speaker_00", MODEL)
    with pytest.raises(AppError, match="失效"):
        diarization.build_voiceprint("changed", turns, cache, "speaker_00", MODEL)


def seed_analysis(service):
    doc = build_doc()
    doc["duration_ms"] = 10000
    state = build_state()
    labelled(doc, state, {"a": {"speaker_group": "speaker_01", "needs_confirmation": False},
                          "b": {"speaker_group": "speaker_00", "needs_confirmation": False},
                          "c": {"speaker_group": "speaker_01", "needs_confirmation": False}})
    with service.store.connection() as db:
        db.execute("UPDATE projects SET transcript=?,speakers=?,revision=1 WHERE id='p1'",
                   (json.dumps(doc, ensure_ascii=False), json.dumps(state)))
    return doc, state


def test_registering_a_voiceprint_names_the_group_and_rejects_lookalikes(service):
    seed_analysis(service)
    project = service.dispatch("voiceprint.register", {"project_id": "p1", "expected_revision": 1,
                                                       "group": "speaker_00", "name": "陳小姐"})
    assert project["revision"] == 2
    assert [g["name"] for g in project["speaker_summary"]["groups"] if g["label"] == "speaker_00"] == ["陳小姐"]
    assert project["transcript"]["segments"][1]["speaker"] == "陳小姐"
    assert service.dispatch("voiceprint.list", {})[0]["name"] == "陳小姐"
    person = service.dispatch("voiceprint.list", {})[0]["id"]
    with pytest.raises(AppError) as duplicate:
        service.dispatch("voiceprint.register", {"project_id": "p1", "expected_revision": 2, "group": "speaker_00", "person_id": person})
    assert duplicate.value.code == "DUPLICATE"
    # The same voice under another name would make both unusable.
    with pytest.raises(AppError) as clash:
        service.dispatch("voiceprint.register", {"project_id": "p1", "expected_revision": 2, "group": "speaker_00", "name": "別人"})
    assert clash.value.code == "VOICE_CONFLICT"
    assert service.dispatch("voiceprint.delete", {"person_id": person}) == []


def test_speaker_edits_do_not_stale_captions(service):
    seed_analysis(service)
    service.dispatch("caption.generate", {"project_id": "p1", "expected_revision": 1})
    project = service.dispatch("speaker.rename_group", {"project_id": "p1", "expected_revision": 1, "group": "speaker_00", "name": "主持人"})
    assert project["revision"] == 2 and not project["captions_stale"]
    with pytest.raises(AppError) as conflict:
        service.dispatch("speaker.rename_group", {"project_id": "p1", "expected_revision": 1, "group": "speaker_00", "name": "x"})
    assert conflict.value.code == "REVISION_CONFLICT"


def test_typing_a_name_marks_it_manual(service):
    seed_analysis(service)
    edited = service.dispatch("transcript.edit", {"project_id": "p1", "expected_revision": 1, "segment_id": "a", "text": "第一句", "speaker": "老闆"})
    segment = edited["transcript"]["segments"][0]
    assert segment["speaker"] == "老闆" and segment["speaker_source"] == "manual"
    unchanged = service.dispatch("transcript.edit", {"project_id": "p1", "expected_revision": 2, "segment_id": "b", "text": "第二句", "speaker": "講者 2"})
    assert unchanged["transcript"]["segments"][1].get("speaker_source") == "model"


def test_diarization_job_requires_models_and_retry_keeps_request(service, tmp_path):
    with pytest.raises(AppError) as error:
        service.dispatch("speaker.analyze", {"project_id": "p1"})
    assert error.value.code == "MODEL_MISSING"
    service.store.set_setting("speaker_models", {"segmentation": str(tmp_path / "s.onnx"), "embedding": str(tmp_path / "e.onnx"), "name": "m", "hashes": {}})
    with pytest.raises(AppError):
        service.dispatch("speaker.analyze", {"project_id": "p1"})  # files absent
    (tmp_path / "s.onnx").write_bytes(b"s")
    (tmp_path / "e.onnx").write_bytes(b"e")
    job = service.dispatch("speaker.analyze", {"project_id": "p1", "speaker_count": 3})
    stored = json.loads(service.store.jobs()[0]["parameters"])
    assert stored["request"]["kind"] == "diarize" and stored["request"]["speaker_count"] == 3
    with service.store.connection() as db:
        db.execute("UPDATE jobs SET status='failed' WHERE id=?", (job["job_id"],))
    retried = service.dispatch("job.retry", {"job_id": job["job_id"]})
    assert retried["job_id"] != job["job_id"]
    with pytest.raises(AppError):
        service.dispatch("speaker.analyze", {"project_id": "p1", "speaker_count": 99})


def test_profiles_and_glossary_shape_decoding():
    fast = asr.parameters("faster-whisper", profile="fast", glossary=" 台灣 Breeze ")
    assert fast["beam_size"] == 1 and fast["condition_on_previous_text"] is False and fast["initial_prompt"] == "台灣 Breeze"
    assert asr.parameters("faster-whisper")["beam_size"] == 5
    assert asr.runtime_options("mlx", "balanced") == {"mlx_fast_attention": True}
    assert asr.runtime_options("mlx", "balanced", word_timestamps=True) == {"mlx_fast_attention": False}
    assert asr.runtime_options("faster-whisper", "fast") == {"mlx_fast_attention": False}
    with pytest.raises(AppError):
        asr.parameters("mlx", glossary="字" * 4001)


def test_fast_attention_and_word_timestamps_are_exclusive(service, tmp_path):
    service.store.set_setting("asr_model", {"path": str(tmp_path), "engine": "mlx"})
    with pytest.raises(AppError, match="快速注意力"):
        service.dispatch("job.start", {"project_id": "p1", "word_timestamps": True, "profile": "balanced"})


def test_windows_extended_prefix_is_removed():
    assert asr.plain_path("\\\\?\\C:\\models\\breeze") == "C:\\models\\breeze"
    assert asr.plain_path("\\\\?\\UNC\\server\\share\\m") == "\\\\server\\share\\m"
    assert asr.plain_path("/Users/a/model") == "/Users/a/model"


def test_cuda_failure_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(hardware, "cuda_device_count", lambda: 1)
    runtimes = []

    class Decoder:
        def __init__(self, path, **runtime):
            runtimes.append(runtime["device"])
            if runtime["device"] == "cuda":
                raise RuntimeError("cublas64_12.dll missing")

        def transcribe(self, audio, **kw):
            return iter([]), type("Info", (), {"language": "zh"})()
    segments, language = asr.ct2_segments(Decoder, "m", "a.wav", {}, None)
    assert runtimes == ["cuda", "cpu"] and list(segments) == [] and language == "zh"


def test_concurrency_needs_cores_and_memory(monkeypatch):
    monkeypatch.delenv("TP_CONCURRENT_STAGES", raising=False)
    hardware.physical_cores.cache_clear()
    hardware.memory_bytes.cache_clear()
    monkeypatch.setattr(hardware, "physical_cores", lambda: 8)
    monkeypatch.setattr(hardware, "memory_bytes", lambda: 16 * 1024**3)
    assert hardware.concurrent_stages()
    monkeypatch.setattr(hardware, "memory_bytes", lambda: 8 * 1024**3)
    assert not hardware.concurrent_stages()
    monkeypatch.setenv("TP_CONCURRENT_STAGES", "1")
    assert hardware.concurrent_stages()


def test_overlapping_model_segments_are_merged():
    def seg(sid, a, b, text, words=()):
        return {"id": sid, "start_ms": a, "end_ms": b, "text": text, "raw_text": text, "speaker": "",
                "words": list(words), "alignment_status": "incomplete", "review_reasons": []}
    merged = merge_overlaps([seg("1", 0, 2000, "你好"), seg("2", 1500, 3000, "世界"), seg("3", 3000, 4000, "再見")])
    assert [(s["start_ms"], s["end_ms"], s["text"]) for s in merged] == [(0, 3000, "你好世界"), (3000, 4000, "再見")]
    assert "模型時間重疊已合併" in merged[0]["review_reasons"]
