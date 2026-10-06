"""Ported from fabo-asr's group consolidation, forced matching and gate calibration."""
import json

import numpy as np
import pytest

from transcript_plus import diarization, models, speakers
from transcript_plus.errors import AppError

MODEL = "voice-hash"


def unit(*values):
    vector = np.asarray(values, dtype=float)
    return vector / np.linalg.norm(vector)


def profile(person, vector, name=None, model=MODEL):
    return {"id": f"{person}-1", "person_id": person, "name": name or person.title(), "embedding": unit(*vector).tolist(),
            "model_hash": model, "quality": {"preprocessing": diarization.PREPROCESSING}, "enabled": True}


def turns_for(*spans):
    return [{"start": a, "end": b, "speaker_group": g} for a, b, g in spans]


def lookup(table):
    """embed(start, end) that answers by which turn the span starts in."""
    def embed(start, end):
        for (a, b), vector in table.items():
            if a <= start < b:
                return unit(*vector)
        raise ValueError("no speech")
    return embed


def test_small_group_folds_into_the_most_similar_big_group():
    turns = turns_for((0, 100, "g0"), (100, 200, "g1"), (200, 210, "g2"))
    centers = {"g0": unit(1, 0, 0), "g1": unit(0, 1, 0), "g2": unit(.95, .05, 0)}
    merged, mapping = diarization.merge_small_groups(turns, centers)
    assert mapping["g2"] == "g0" and mapping["g0"] == "g0" and mapping["g1"] == "g1"
    assert merged[-1]["speaker_group"] == "g0" and merged[-1]["merged_from"] == "g2"
    # protected groups (split out on purpose by refinement) and dissimilar ones stay
    assert diarization.merge_small_groups(turns, centers, protect={"g2"})[1]["g2"] == "g2"
    centers["g2"] = unit(0, 0, 1)
    assert diarization.merge_small_groups(turns, centers)[1]["g2"] == "g2"


def test_roster_merge_folds_groups_that_sound_like_one_enrolled_person():
    turns = turns_for((0, 100, "g0"), (100, 130, "g1"), (130, 200, "g2"))
    centers = {"g0": unit(1, .1, 0), "g1": unit(1, 0, .1), "g2": unit(0, 1, 0)}
    roster = [profile("alice", (1, 0, 0)), profile("bob", (0, 1, 0))]
    gates = diarization.gates_for("x.onnx")
    merged, mapping = diarization.merge_by_roster(turns, centers, roster, MODEL, gates)
    assert mapping["g1"] == "g0" and mapping["g2"] == "g2"
    assert diarization.merge_by_roster(turns, centers, [], MODEL, gates)[1] == {"g0": "g0", "g1": "g1", "g2": "g2"}


def test_consolidation_can_be_switched_off(monkeypatch):
    turns = turns_for((0, 100, "g0"), (100, 110, "g1"))
    embed = lookup({(0, 100): (1, 0, 0), (100, 110): (1, .02, 0)})
    merged, info = diarization.consolidate_groups(turns, embed, [], MODEL, diarization.gates_for("x"))
    assert info["small_merged"] == 1 and info["groups_after"] == 1
    monkeypatch.setenv("TP_DIARIZATION_MERGE_SMALL", "0")
    _, info = diarization.consolidate_groups(turns, embed, [], MODEL, diarization.gates_for("x"))
    assert info["small_merged"] == 0 and info["groups_after"] == 2


def test_forced_match_never_names_two_groups_with_one_person():
    cache = {"binding": {}, "vectors": {"g0": [unit(1, .2, 0).tolist()] * 2, "g1": [unit(1, .3, 0).tolist()] * 2, "g2": [unit(0, 0, 1).tolist()] * 2}}
    roster = [profile("alice", (1, 0, 0)), profile("bob", (0, 1, 0))]
    forced = diarization.match_groups(cache, roster, MODEL, "forced")
    named = [g["speaker_id"] for g in forced.values() if g["speaker_id"]]
    assert len(named) == len(set(named)) == 2
    assert forced["g0"]["speaker_id"] == "alice" and forced["g0"]["match_reason"] == "forced"
    assert forced["g0"]["similarity_percent"] is not None
    assert sum(1 for g in forced.values() if g["match_reason"] == "forced_unassigned") == 1
    # limited attendance: only Bob is considered
    only_bob = diarization.match_groups(cache, roster, MODEL, "forced", candidate_ids=["bob"])
    assert {g["speaker_id"] for g in only_bob.values()} - {None} == {"bob"}
    with pytest.raises(ValueError):
        diarization.match_groups(cache, roster, MODEL, "bogus")


def test_hungarian_picks_the_best_global_pairing():
    scores = [[.9, .8], [.85, .1]]
    assert sorted(diarization.hungarian_max(scores)) == [(0, 1), (1, 0)]
    assert sorted(diarization.hungarian_max([[.5, .6, .1], [.4, .9, .2], [.3, .2, .8], [.1, .1, .1]])) == [(0, 0), (1, 1), (2, 2)]


def test_gates_follow_the_voiceprint_model():
    assert diarization.gates_for("/m/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")["threshold"] == .45
    assert diarization.gates_for("nemo_en_titanet_small.onnx")["threshold"] == .5
    assert diarization.gates_for("unknown.onnx")["threshold"] == .72  # uncalibrated models stay conservative
    # a cached gate lowers the bar for a borderline voice that the legacy default would reject
    vectors = [unit(1, 1.3, 0).tolist()] * 2
    roster = [profile("alice", (1, 0, 0))]
    strict = diarization.match_groups({"binding": {}, "vectors": {"g": vectors}}, roster, MODEL)
    loose = diarization.match_groups({"binding": {}, "vectors": {"g": vectors}, "gates": diarization.gates_for("nemo_en_titanet_small.onnx")}, roster, MODEL)
    assert strict["g"]["speaker_id"] is None and loose["g"]["speaker_id"] == "alice"


def test_voiceprint_model_falls_back_to_the_clustering_model():
    assert diarization.voiceprint_model({"embedding": "t.onnx"}) == "t.onnx"
    assert diarization.voiceprint_model({"embedding": "t.onnx", "voiceprint": "e.onnx"}) == "e.onnx"


def test_speaker_folder_detects_the_optional_chinese_voiceprint_model(tmp_path):
    (tmp_path / "segmentation").mkdir()
    (tmp_path / "segmentation" / "model.onnx").write_bytes(b"s")
    (tmp_path / "nemo_en_titanet_small.onnx").write_bytes(b"t")
    assert "voiceprint" not in models.find_speaker_models(tmp_path)
    (tmp_path / models.VOICEPRINT_DEFAULT).write_bytes(b"v")
    found = models.find_speaker_models(tmp_path)
    assert found["voiceprint"].endswith(models.VOICEPRINT_DEFAULT) and "voiceprint" in found["hashes"]


def test_merging_groups_merges_assignment_centers():
    turns = turns_for((0, 20, "speaker_00"), (20, 40, "speaker_01"))
    vectors = {"speaker_00": [unit(1, 0, 0).tolist()] * 3, "speaker_01": [unit(1, .1, 0).tolist()] * 3}
    centers = {"speaker_00": unit(1, 0, 0).tolist(), "speaker_01": unit(1, .2, 0).tolist()}
    cache = {"binding": diarization.cache_binding("h", turns, MODEL), "vectors": vectors, "centers": centers}
    state = speakers.new_state({"turns": turns, "groups": diarization.match_groups(cache, [], MODEL), "cache": cache, "metrics": {}})
    doc = {"segments": []}
    _, state = speakers.merge_groups(doc, state, "speaker_00", "speaker_01", "h")
    assert list(state["cache"]["centers"]) == ["speaker_01"]
    assert abs(np.linalg.norm(state["cache"]["centers"]["speaker_01"]) - 1) < 1e-9


def test_assign_uses_stored_clustering_centers(monkeypatch):
    class Fake:
        pass
    monkeypatch.setattr(diarization, "extractor", lambda *a, **k: Fake())
    monkeypatch.setattr(diarization, "embedding", lambda engine, samples: unit(1, 0))
    cache = {"vectors": {"speaker_00": [unit(0, 1).tolist()], "speaker_01": [unit(0, 1).tolist()]},
             "centers": {"speaker_00": unit(1, 0).tolist(), "speaker_01": unit(0, 1).tolist()}}
    turns = turns_for((0, 10, "speaker_00"), (0, 10, "speaker_01"))  # tie on overlap: voice decides
    result = diarization.assign(np.zeros(16000 * 10, dtype=np.int16), {"embedding": "e"}, [{"start": 1, "end": 5}],
                                {"turns": turns, "cache": cache})
    assert result[0]["speaker_group"] == "speaker_00"
