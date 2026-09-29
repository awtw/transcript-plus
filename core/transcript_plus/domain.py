"""Transcript and captions share text. Timing is never inferred from character count."""
from copy import deepcopy
import json
import re
import uuid

import regex

from .errors import AppError, require


def uid():
    return uuid.uuid4().hex


def graphemes(text):
    return regex.findall(r"\X", text)


def lexical(text):
    return regex.sub(r"[\p{P}\p{Z}\s]", "", text)


def valid_time(start, end, duration):
    return type(start) is int and type(end) is int and 0 <= start < end <= duration


def validate_document(doc):
    require(isinstance(doc, dict) and doc.get("schema_version") == 1,
            "INVALID_DOCUMENT", "不支援的逐字稿格式。")
    duration = doc.get("duration_ms")
    require(type(duration) is int and 0 < duration <= 7_200_000,
            "INVALID_TIMING", "影音長度必須介於 0 與 120 分鐘。")
    segments = doc.get("segments")
    require(isinstance(segments, list) and len(segments) <= 50000,
            "INVALID_DOCUMENT", "逐字稿段落數超過限制。")
    seen = set()
    for s in segments:
        require(isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] not in seen,
                "INVALID_DOCUMENT", "逐字稿段落識別碼重複或遺失。")
        seen.add(s["id"])
        require(valid_time(s.get("start_ms"), s.get("end_ms"), duration),
                "INVALID_TIMING", "逐字稿時間超出影音範圍。")
        require(isinstance(s.get("text"), str) and bool(s["text"].strip()) and len(s["text"]) <= 20000,
                "INVALID_DOCUMENT", "逐字稿文字不可空白或超過 20,000 字元。")


def edit_segment(doc, segment_id, text, speaker=None):
    result = deepcopy(doc)
    segment = next((s for s in result["segments"] if s["id"] == segment_id), None)
    require(segment is not None, "NOT_FOUND", "找不到逐字稿段落。")
    require(isinstance(text, str) and text.strip() and len(text) <= 20000,
            "INVALID_DOCUMENT", "文字不可空白或超過 20,000 字元。")
    segment["text"] = text.strip()
    raw = segment.get("raw_text", "")
    words = segment.get("words", [])
    # Restoring the original text restores timing only when the full original word map is valid.
    complete = bool(words) and lexical("".join(w["text"] for w in words)) == lexical(raw)
    segment["alignment_status"] = "valid" if complete and lexical(text) == lexical(raw) else "dirty"
    if speaker is not None:
        require(isinstance(speaker, str) and len(speaker) <= 80,
                "INVALID_DOCUMENT", "講者名稱最多 80 字。")
        segment["speaker"] = speaker.strip()
    validate_document(result)
    return result


def word_spans(segment):
    """Map current text (including punctuation edits) to the original timed words."""
    if segment.get("alignment_status") != "valid":
        return []
    text = segment["text"]
    positions = [i for i, ch in enumerate(text) if lexical(ch)]
    words = segment.get("words", [])
    if lexical("".join(w["text"] for w in words)) != lexical(text):
        return []
    spans, consumed, previous_end = [], 0, segment["start_ms"]
    for word in words:
        count = len(lexical(word["text"]))
        if count == 0:
            continue
        if not valid_time(word.get("start_ms"), word.get("end_ms"), segment["end_ms"]) or word["start_ms"] < previous_end:
            return []
        consumed += count
        end = positions[consumed] if consumed < len(positions) else len(text)
        spans.append({"end": end, "word": word})
        previous_end = word["end_ms"]
    return spans


def cue_from_range(segment, char_start, char_end, start, end, status, words=None):
    return {"id": uid(), "segment_id": segment["id"], "char_start": char_start,
            "char_end": char_end, "text": segment["text"][char_start:char_end],
            "start_ms": start, "end_ms": end, "timing_status": status,
            "source_word_ids": words or [], "manual_override": False}


def make_captions(doc, max_chars=18):
    require(type(max_chars) is int and 8 <= max_chars <= 42,
            "INVALID_INPUT", "每行字數需介於 8～42。")
    cues = []
    for segment in doc["segments"]:
        spans = word_spans(segment)
        if not spans:
            # Segment timing is real, even if word-level alignment is unavailable.
            cues.append(cue_from_range(segment, 0, len(segment["text"]), segment["start_ms"],
                                       segment["end_ms"], "segment"))
            continue
        first, char_start = 0, 0
        for index, span in enumerate(spans):
            chunk = segment["text"][char_start:span["end"]]
            next_too_long = index + 1 < len(spans) and len(graphemes(segment["text"][char_start:spans[index+1]["end"]])) > max_chars * 2
            pause = index + 1 < len(spans) and spans[index+1]["word"]["start_ms"] - span["word"]["end_ms"] >= 600
            if index == len(spans)-1 or next_too_long or pause or re.search(r"[。！？!?；;]$", chunk.strip()):
                cues.append(cue_from_range(segment, char_start, span["end"], spans[first]["word"]["start_ms"],
                                           span["word"]["end_ms"], "valid",
                                           [s["word"]["id"] for s in spans[first:index+1]]))
                char_start, first = span["end"], index + 1
    return {"revision": 1, "max_chars": max_chars, "cues": cues}


def split_cue(track, doc, cue_id, offset, manual_ms=None):
    result = deepcopy(track)
    index = next((i for i, c in enumerate(result["cues"]) if c["id"] == cue_id), None)
    require(index is not None, "NOT_FOUND", "找不到字幕。")
    cue = result["cues"][index]
    require(type(offset) is int and 0 < offset < len(cue["text"]), "INVALID_INPUT", "請在字幕中間選擇拆分位置。")
    require(cue["text"][:offset].strip() and cue["text"][offset:].strip(), "INVALID_INPUT", "拆分後兩段都需要文字。")
    segment = next(s for s in doc["segments"] if s["id"] == cue["segment_id"])
    split_at = cue["char_start"] + offset
    spans = word_spans(segment)
    boundary = next((i for i, s in enumerate(spans[:-1]) if s["end"] == split_at), None)
    if boundary is not None and not cue.get("manual_override"):
        left_end, right_start = spans[boundary]["word"]["end_ms"], spans[boundary+1]["word"]["start_ms"]
        status = "valid"
    else:
        require(type(manual_ms) is int and cue["start_ms"] < manual_ms < cue["end_ms"],
                "TIMING_REQUIRED", "此處沒有可靠詞界，請輸入拆分時間，或移到詞界再拆分。")
        left_end = right_start = manual_ms
        status = "manual"
    left = cue_from_range(segment, cue["char_start"], split_at, cue["start_ms"], left_end, status)
    right = cue_from_range(segment, split_at, cue["char_end"], right_start, cue["end_ms"], status)
    left["manual_override"] = right["manual_override"] = status == "manual"
    result["cues"][index:index+1] = [left, right]
    result["revision"] += 1
    return result


def merge_cue(track, cue_id):
    result = deepcopy(track)
    index = next((i for i, c in enumerate(result["cues"]) if c["id"] == cue_id), -1)
    require(0 <= index < len(result["cues"])-1, "INVALID_INPUT", "沒有下一則字幕可以合併。")
    left, right = result["cues"][index:index+2]
    require(left["segment_id"] == right["segment_id"] and left["char_end"] == right["char_start"],
            "INVALID_INPUT", "目前只支援合併同一逐字稿段落內相鄰的字幕。")
    left.update(id=uid(), text=left["text"]+right["text"], char_end=right["char_end"], end_ms=right["end_ms"],
                source_word_ids=left["source_word_ids"]+right["source_word_ids"],
                timing_status="manual" if "manual" in (left["timing_status"], right["timing_status"]) else left["timing_status"])
    left["manual_override"] = left.get("manual_override", False) or right.get("manual_override", False)
    result["cues"][index:index+2] = [left]
    result["revision"] += 1
    return result


def caption_warnings(track, duration):
    warnings, previous = [], 0
    for cue in track["cues"]:
        reasons = []
        if not valid_time(cue["start_ms"], cue["end_ms"], duration) or cue["start_ms"] < previous:
            reasons.append("時間無效或與前一則重疊")
        previous = cue["end_ms"]
        count = len(graphemes(regex.sub(r"\s", "", cue["text"])))
        if count > track["max_chars"] * 2:
            reasons.append("超過兩行建議字數")
        length = cue["end_ms"] - cue["start_ms"]
        if length > 0 and count / (length / 1000) > 9:
            reasons.append("閱讀速度偏快")
        if length < 1000 or length > 7000:
            reasons.append("顯示時間不在建議的 1～7 秒")
        if reasons:
            warnings.append({"cue_id": cue["id"], "reasons": reasons})
    return warnings


def wrap_caption(text, max_chars):
    chars = graphemes(text.strip())
    if len(chars) <= max_chars:
        return "".join(chars)
    # Do not silently drop text when it exceeds two lines: keep it and warn.
    midpoint = min(max_chars, (len(chars)+1)//2)
    spaces = [i for i, c in enumerate(chars[:max_chars+1]) if c.isspace() and i > max_chars//3]
    cut = min(spaces, key=lambda i: abs(i-midpoint)) if spaces else midpoint
    return "".join(chars[:cut]).rstrip()+"\n"+"".join(chars[cut:]).lstrip()


def timestamp(ms, sep=","):
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{sep}{millis:03}"


def export_content(project, kind):
    doc = project["transcript"]
    require(doc is not None, "NOT_READY", "請先完成轉錄。")
    if kind == "json":
        return json.dumps({"schema_version": 1, "title": project["title"], "revision": project["revision"],
                           "transcript": doc, "captions": project["captions"]}, ensure_ascii=False, indent=2)
    if kind == "txt":
        return "\n\n".join(f'[{timestamp(s["start_ms"], ".")}] {s.get("speaker") or "講者"}\n{s["text"]}' for s in doc["segments"])+"\n"
    require(kind in ("srt", "vtt"), "INVALID_INPUT", "不支援的匯出格式。")
    track = project["captions"]
    require(track is not None and not project["captions_stale"], "STALE_CAPTIONS", "字幕尚未產生或已過期，請重新產生。")
    previous, blocks = 0, []
    for index, cue in enumerate(track["cues"], 1):
        require(valid_time(cue["start_ms"], cue["end_ms"], doc["duration_ms"]) and cue["start_ms"] >= previous,
                "INVALID_TIMING", "字幕時間無效或重疊，請先調整。")
        previous = cue["end_ms"]
        text = wrap_caption(cue["text"], track["max_chars"])
        # Literal markup must not become WebVTT tags.
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        sep = "." if kind == "vtt" else ","
        blocks.append(f'{index}\n{timestamp(cue["start_ms"], sep)} --> {timestamp(cue["end_ms"], sep)}\n{text}')
    return ("WEBVTT\n\n" if kind == "vtt" else "")+"\n\n".join(blocks)+"\n"
