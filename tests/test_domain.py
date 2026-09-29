from copy import deepcopy

import pytest

from transcript_plus import domain
from transcript_plus.errors import AppError


def test_word_boundary_split_preserves_real_gap(document):
    track = domain.make_captions(document)
    result = domain.split_cue(track, document, track["cues"][0]["id"], 4)
    left, right = result["cues"]
    assert (left["start_ms"], left["end_ms"]) == (1000, 2000)
    assert (right["start_ms"], right["end_ms"]) == (2100, 4000)
    assert left["text"]+right["text"] == document["segments"][0]["text"]
    assert len(track["cues"]) == 1


def test_split_inside_word_does_not_guess_time(document):
    track = domain.make_captions(document)
    with pytest.raises(AppError, match="可靠詞界"):
        domain.split_cue(track, document, track["cues"][0]["id"], 1)
    result = domain.split_cue(track, document, track["cues"][0]["id"], 1, 1500)
    assert result["cues"][0]["timing_status"] == "manual"
    assert result["cues"][1]["start_ms"] == 1500


def test_changed_text_invalidates_words_but_preserves_audio(document):
    updated = domain.edit_segment(document, "segment-a", "大家好，明天開會。")
    segment = updated["segments"][0]
    assert segment["alignment_status"] == "dirty"
    assert segment["words"] == document["segments"][0]["words"]
    assert not domain.word_spans(segment)
    track = domain.make_captions(updated)
    assert track["cues"][0]["timing_status"] == "segment"
    assert (track["cues"][0]["start_ms"], track["cues"][0]["end_ms"]) == (1000,4000)


def test_punctuation_edit_keeps_mapping_and_new_text(document):
    updated = domain.edit_segment(document, "segment-a", "大家好！今天開會？")
    assert updated["segments"][0]["alignment_status"] == "valid"
    track = domain.make_captions(updated)
    assert "".join(c["text"] for c in track["cues"]) == "大家好！今天開會？"


def test_merge_roundtrip_keeps_text(document):
    track = domain.make_captions(document)
    split = domain.split_cue(track, document, track["cues"][0]["id"], 4)
    merged = domain.merge_cue(split, split["cues"][0]["id"])
    assert merged["cues"][0]["text"] == track["cues"][0]["text"]
    assert merged["cues"][0]["end_ms"] == 4000


def test_export_rejects_overlapping_cues(document):
    track = domain.make_captions(document)
    track["cues"] += deepcopy(track["cues"])
    project = {"transcript":document,"captions":track,"captions_stale":False}
    with pytest.raises(AppError, match="重疊"):
        domain.export_content(project, "srt")


def test_export_uses_distinct_srt_vtt_header_and_clock(document):
    project = {"transcript":document,"captions":domain.make_captions(document),"captions_stale":False}
    assert "00:00:01,000 --> 00:00:04,000" in domain.export_content(project,"srt")
    vtt = domain.export_content(project,"vtt")
    assert vtt.startswith("WEBVTT\n\n") and "00:00:01.000 --> 00:00:04.000" in vtt


@pytest.mark.parametrize("start,end", [(True,2000),(-1,2000),(1000,1000),(1000,10001),(float('nan'),2000)])
def test_invalid_times_rejected(document,start,end):
    document["segments"][0].update(start_ms=start,end_ms=end)
    with pytest.raises(AppError): domain.validate_document(document)


def test_long_text_and_emoji_never_truncated():
    text = "我們👨‍👩‍👧‍👦一起討論這次的字幕功能與內容編輯操作"*3
    wrapped = domain.wrap_caption(text,18)
    assert wrapped.replace("\n","") == text
    assert len(wrapped.splitlines()) == 2
    assert "👨‍👩‍👧‍👦" in wrapped


def test_malformed_word_map_downgrades_to_segment(document):
    document["segments"][0]["words"][1]["start_ms"] = 1500
    track = domain.make_captions(document)
    assert track["cues"][0]["timing_status"] == "segment"


def test_manual_time_not_overwritten_by_split(document):
    track = domain.make_captions(document)
    track["cues"][0].update(start_ms=900, manual_override=True)
    with pytest.raises(AppError):
        domain.split_cue(track,document,track["cues"][0]["id"],4)
