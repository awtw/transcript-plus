"""Speaker groups on a transcript: naming, manual correction, merging and voiceprint rematching.

`state` is the project's stored analysis:
  turns   [{start, end, speaker_group}]            seconds
  groups  {label: voiceprint match result}
  names   {label: {name, source: auto|voiceprint|manual}}
  cache   {binding, vectors}                        clean-excerpt embeddings for registration
Segments carry speaker_group / needs_confirmation / speaker_source (manual = typed name).
"""
from copy import deepcopy
import time

import numpy as np

from . import diarization
from .domain import uid
from .errors import require


def seconds_by_group(state):
    totals = {}
    for turn in state["turns"]:
        totals[turn["speaker_group"]] = totals.get(turn["speaker_group"], 0.) + turn["end"] - turn["start"]
    return totals


def resolve_names(state, doc):
    """Keep manual names; voiceprint matches name a group; the rest are 講者 1…N by first appearance."""
    labels, seen = [], set()
    for segment in doc["segments"]:
        label = segment.get("speaker_group")
        if label and label in state["groups"] and label not in seen:
            seen.add(label)
            labels.append(label)
    labels += [label for label in sorted(state["groups"]) if label not in seen]
    names = {}
    for index, label in enumerate(labels, 1):
        current = state["names"].get(label)
        match = state["groups"].get(label, {})
        if current and current["source"] == "manual":
            names[label] = current
        elif match.get("speaker_name"):
            names[label] = {"name": match["speaker_name"], "source": "voiceprint"}
        else:
            names[label] = {"name": f"講者 {index}", "source": "auto"}
    state["names"] = names
    return names


def sync_segment_names(doc, state):
    names = state["names"]
    for segment in doc["segments"]:
        label = segment.get("speaker_group")
        if label in names and segment.get("speaker_source") != "manual":
            segment["speaker"] = names[label]["name"]
            segment["speaker_source"] = "model"


def new_state(analysis, speaker_count=None):
    return {"version": 1, "turns": analysis["turns"], "groups": analysis["groups"], "names": {},
            "cache": analysis["cache"], "metrics": analysis["metrics"], "speaker_count": speaker_count,
            "created": time.time()}


def split_segments(doc, turns):
    """Split untouched, word-aligned segments where the speaker changes between words.

    A word spanning two speakers cannot be divided without inventing timing, so such segments stay whole.
    """
    output = []
    spans = [(t["start"] * 1000, t["end"] * 1000, t["speaker_group"]) for t in turns]
    for segment in doc["segments"]:
        words = segment.get("words") or []
        if (segment.get("speaker_source") == "manual" or segment.get("alignment_status") != "valid"
                or segment["text"] != segment.get("raw_text") or len(words) < 2
                or "".join(w["text"] for w in words).strip() != segment["text"]):
            output.append(segment)
            continue
        labels = []
        for word in words:
            active = {g for a, b, g in spans if min(word["end_ms"], b) > max(word["start_ms"], a)}
            labels.append(next(iter(active)) if len(active) == 1 else None)
        if any(label is None for label in labels) or len(set(labels)) < 2:
            output.append(segment)
            continue
        batches = []
        for word, label in zip(words, labels):
            if not batches or batches[-1][0] != label:
                batches.append((label, []))
            batches[-1][1].append(word)
        parts = []
        for _, selected in batches:
            text = "".join(w["text"] for w in selected).strip()
            if not text:
                parts = []
                break
            parts.append({**segment, "id": uid(), "start_ms": selected[0]["start_ms"], "end_ms": selected[-1]["end_ms"],
                          "text": text, "raw_text": text, "words": selected})
        output.extend(parts or [segment])
    result = {**doc, "segments": output}
    return result


def label_segments(doc, state, assignments):
    """assignments: {segment_id: {speaker_group, needs_confirmation}} → mutate doc in place."""
    for segment in doc["segments"]:
        found = assignments.get(segment["id"])
        if found is None:
            continue
        segment["speaker_group"] = found["speaker_group"]
        segment["needs_confirmation"] = bool(found["needs_confirmation"])
        segment.pop("speaker_group_source", None)
        if segment.get("speaker_source") != "manual" and found["speaker_group"] is None:
            segment["speaker"] = ""
    resolve_names(state, doc)
    sync_segment_names(doc, state)
    return doc


def assignments_for(doc, results):
    return {s["id"]: r for s, r in zip(doc["segments"], results)}


def summary(doc, state):
    """Public view for the UI; embeddings and turns stay in storage."""
    counts = {}
    for segment in doc["segments"]:
        if segment.get("speaker_group"):
            counts[segment["speaker_group"]] = counts.get(segment["speaker_group"], 0) + 1
    seconds = seconds_by_group(state)
    groups = [{"label": label, "name": state["names"].get(label, {}).get("name", label),
               "name_source": state["names"].get(label, {}).get("source", "auto"),
               "seconds": round(seconds.get(label, 0.), 1), "segments": counts.get(label, 0),
               "match_reason": match.get("match_reason"), "similarity": match.get("similarity"),
               "similarity_percent": match.get("similarity_percent", diarization.similarity_percent(match.get("similarity"))),
               "excerpt_count": match.get("excerpt_count", 0), "speaker_id": match.get("speaker_id")}
              for label, match in state["groups"].items() if counts.get(label)]  # noise clusters own no segments
    groups.sort(key=lambda g: -g["seconds"])
    review = sum(1 for s in doc["segments"] if s.get("needs_confirmation"))
    return {"groups": groups, "needs_review": review, "created": state["created"],
            "speaker_count": state.get("speaker_count"), "observed": len(groups),
            "ignored_groups": len(state["groups"]) - len(groups)}


def rename_group(doc, state, label, name):
    require(label in state["groups"], "NOT_FOUND", "找不到講者分群。")
    require(isinstance(name, str) and name.strip() and len(name.strip()) <= 80, "INVALID_INPUT", "講者名稱需為 1–80 字。")
    result, state = deepcopy(doc), deepcopy(state)
    state["names"][label] = {"name": name.strip(), "source": "manual"}
    sync_segment_names(result, state)
    return result, state


def assign_segment(doc, state, segment_id, label):
    require(label == "" or label in state["groups"], "NOT_FOUND", "找不到講者分群。")
    result = deepcopy(doc)
    segment = next((s for s in result["segments"] if s["id"] == segment_id), None)
    require(segment is not None, "NOT_FOUND", "找不到逐字稿段落。")
    segment["speaker_group"] = label or None
    segment["speaker_group_source"] = "manual"
    segment["needs_confirmation"] = False
    if segment.get("speaker_source") != "manual":
        segment["speaker"] = state["names"][label]["name"] if label else ""
        segment["speaker_source"] = "model"
    return result


def merge_groups(doc, state, source, target, media_hash):
    """Fold an over-split group into another; keep the registration cache valid by merging its excerpts."""
    require(source != target and source in state["groups"] and target in state["groups"], "INVALID_INPUT", "請選擇兩個不同的講者分群。")
    result, state = deepcopy(doc), deepcopy(state)
    for turn in state["turns"]:
        if turn["speaker_group"] == source:
            turn["speaker_group"] = target
    for segment in result["segments"]:
        if segment.get("speaker_group") == source:
            segment["speaker_group"] = target
    vectors = state["cache"]["vectors"]
    merged = vectors.pop(source, []) + vectors.get(target, [])
    if len(merged) > 5:
        merged = [merged[i] for i in sorted(set(np.linspace(0, len(merged) - 1, 5, dtype=int)))]
    vectors[target] = merged
    centers = state["cache"].get("centers")
    if centers:  # clustering-model centers used for assignment follow the merge
        pair = [np.asarray(centers.pop(label), dtype=float) for label in (source, target) if label in centers]
        center = np.mean(pair, axis=0) if pair else None
        if center is not None and np.linalg.norm(center) > 1e-8:
            centers[target] = (center / np.linalg.norm(center)).tolist()
    binding = state["cache"]["binding"]
    state["cache"]["binding"] = diarization.cache_binding(media_hash, state["turns"], binding["model_hash"])
    state["groups"].pop(source)
    state["names"].pop(source, None)
    state["metrics"]["merged_groups"] = state["metrics"].get("merged_groups", 0) + 1
    return result, state


def rematch(doc, state, profiles, match_mode="fuzzy", candidate_ids=None):
    """Re-run voiceprint matching on the cached excerpts, then refresh non-manual names.

    forced pairs each enrolled person with at most one group (optionally limited to candidate_ids); fuzzy stays conservative.
    """
    result, state = deepcopy(doc), deepcopy(state)
    state["groups"] = diarization.match_groups(state["cache"], profiles, state["cache"]["binding"]["model_hash"],
                                               match_mode, candidate_ids)
    resolve_names(state, result)
    sync_segment_names(result, state)
    return result, state


def group_is_registrable(doc, group):
    """Hand-moved segments make a group's cached excerpts unrepresentative of its members."""
    return not any(s.get("speaker_group") == group and s.get("speaker_group_source") == "manual" for s in doc["segments"])

