"""Offline speaker grouping (sherpa-onnx) and conservative voiceprint matching.

Ported from fabo-asr's diarization with the same thresholds. Times are seconds here;
the service layer converts to and from transcript milliseconds. Audio is always the
project's preprocessed 16 kHz mono PCM16 WAV, so enrollment and meetings share a frontend.
"""
import gc
import hashlib
import json
import wave

import numpy as np

from . import hardware
from .errors import AppError

RATE = 16000
PREPROCESSING = "tp-pcm16-mono-16000-v1"
MAX_SECONDS = 3 * 3600
DEFAULTS = {"cluster_threshold": .99, "window_shift": .25, "min_duration_on": .3, "min_duration_off": .5}
MATCH_THRESHOLD, MATCH_MARGIN = .72, .12


def model_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_samples(path):
    """Read the preprocessed WAV as int16 (half the memory of float32); slice with `floats`."""
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != RATE or handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("講者分析需要 16 kHz 單聲道 PCM16 音訊。")
        if handle.getnframes() > MAX_SECONDS * RATE:
            raise ValueError(f"音檔長度超過 {MAX_SECONDS // 3600} 小時限制。")
        data = handle.readframes(handle.getnframes())
    return np.frombuffer(data, dtype="<i2")


def floats(samples, start=0., end=None):
    first = max(0, int(start * RATE))
    last = len(samples) if end is None else min(len(samples), int(end * RATE))
    return np.ascontiguousarray(samples[first:last], dtype=np.float32) / 32768.0


def extractor(model_path, threads=None):
    import sherpa_onnx
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(model_path), num_threads=threads or hardware.diarization_threads(), provider="cpu")
    if not config.validate():
        raise ValueError("聲紋模型設定無效。")
    return sherpa_onnx.SpeakerEmbeddingExtractor(config)


def embedding(engine, samples):
    stream = engine.create_stream()
    stream.accept_waveform(sample_rate=RATE, waveform=samples)
    stream.input_finished()
    if not engine.is_ready(stream):
        raise ValueError("有效語音不足以建立聲紋")
    vector = np.asarray(engine.compute(stream), dtype=np.float64)
    norm = np.linalg.norm(vector)
    if not np.isfinite(vector).all() or norm < 1e-8:
        raise ValueError("無效聲紋")
    return vector / norm


def _identity(profile):
    return profile.get("person_id") or profile["id"]


def conservative_match(vectors, profiles, fingerprint, threshold=MATCH_THRESHOLD, margin=MATCH_MARGIN):
    """Require independent excerpts to agree. Similarity is never accuracy."""
    eligible = [p for p in profiles if p.get("enabled", True) and p["model_hash"] == fingerprint
                and p.get("quality", {}).get("preprocessing") == PREPROCESSING]
    result = {"speaker_id": None, "speaker_name": "", "similarity": None, "match_reason": "insufficient_consistent_evidence"}
    if len(vectors) < 2 or not eligible:
        return result
    conflicts = {_identity(a) for a in eligible for b in eligible
                 if _identity(a) != _identity(b) and np.array_equal(np.asarray(a["embedding"]), np.asarray(b["embedding"]))}
    winners, scores = [], []
    for vector in vectors:
        by_person = {}
        for person in eligible:
            reference = np.asarray(person["embedding"], dtype=float)
            if reference.shape != vector.shape or not np.isfinite(reference).all() or np.linalg.norm(reference) < 1e-8:
                continue
            score = float(np.dot(vector, reference / np.linalg.norm(reference)))
            key = _identity(person)
            if key not in by_person or score > by_person[key][0]:
                by_person[key] = (score, person)
        ranked = sorted(by_person.values(), key=lambda value: value[0], reverse=True)
        if not ranked:
            return result
        score, person = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else -1
        if score < threshold or score - second < margin:
            return {**result, "similarity": score,
                    "match_reason": "duplicate_profile_identity_conflict" if _identity(person) in conflicts else "threshold_or_margin"}
        winners.append(_identity(person))
        scores.append(score)
    if len(set(winners)) != 1:
        return {**result, "match_reason": "inconsistent_excerpts"}
    winner = next(p for p in eligible if _identity(p) == winners[0])
    return {"speaker_id": winners[0], "speaker_name": winner["name"], "similarity": min(scores), "match_reason": "consistent_excerpts"}


VERIFY_MIN_SECONDS, VERIFY_LOW, VERIFY_HIGH, VERIFY_GAP = 3., .45, .6, .2


def attach_turns(spans, turns, labels, score_segment=None):
    """Assign each (start, end) span by unioned speaking duration, then voice evidence and continuity."""
    valid = [t for t in turns if t.get("speaker_group") is not None
             and np.isfinite([t["start"], t["end"]]).all() and t["end"] > t["start"]]
    mapped = []
    for source in spans:
        intervals = {}
        for turn in valid:
            start, end = max(source["start"], turn["start"]), min(source["end"], turn["end"])
            if end > start:
                intervals.setdefault(turn["speaker_group"], []).append((start, end))
        durations = {}
        for label, parts in intervals.items():
            total, right = 0., -float("inf")
            for start, end in sorted(parts):
                total += max(0., end - max(start, right))
                right = max(right, end)
            durations[label] = total
        candidates = sorted(durations)
        reason, scores, distances = "longest_duration", {}, {}
        if candidates:
            maximum = max(durations.values())
            candidates = [g for g in candidates if abs(durations[g] - maximum) <= 1e-8]
        else:
            candidates = sorted(set(labels) | {t["speaker_group"] for t in valid})
            reason = "no_evidence"
        if len(candidates) > 1 or not durations:
            if score_segment:
                try:
                    scores = {g: float(v) for g, v in score_segment(source, candidates).items()
                              if g in candidates and np.isfinite(v)}
                except (ValueError, RuntimeError):
                    scores = {}
            comparable = bool(scores) and len(scores) == len(candidates)
            if comparable:
                best = max(scores.values())
                candidates = [g for g in candidates if g in scores and abs(scores[g] - best) <= 1e-8]
                reason = "voice_similarity"
            if len(candidates) > 1 or not comparable:
                for group in candidates:
                    distances[group] = min((min(abs(source["start"] - t["end"]), abs(t["start"] - source["end"]))
                                            if durations else max(0., source["start"] - t["end"], t["start"] - source["end"])
                                            for t in valid if t["speaker_group"] == group), default=float("inf"))
                nearest = min(distances.values(), default=float("inf"))
                if np.isfinite(nearest):
                    candidates = [g for g in candidates if abs(distances[g] - nearest) <= 1e-8]
                    reason = "temporal_continuity" if len(candidates) == 1 else "stable_order"
                elif not comparable:
                    candidates, reason = [], "no_evidence"
        group = candidates[0] if candidates else None
        if score_segment and group is not None and reason == "longest_duration" and source["end"] - source["start"] >= VERIFY_MIN_SECONDS:
            # Time overlap says who the segmentation model blamed; the voice must still agree.
            try:
                heard = {g: float(v) for g, v in score_segment(source, sorted(labels)).items() if np.isfinite(v)}
            except (ValueError, RuntimeError):
                heard = {}
            rival = max((g for g in heard if g != group), key=heard.get, default=None)
            if group in heard and rival and heard[group] < VERIFY_LOW and heard[rival] >= VERIFY_HIGH and heard[rival] - heard[group] >= VERIFY_GAP:
                group, reason, scores = rival, "voice_override", heard
        mapped.append({"speaker_group": group, "needs_confirmation": group is None or len(durations) > 1,
                       "reason": reason, "mixed_speakers": len(durations) > 1})
    return mapped


# Intra-turn voice check. The segmentation model can chain two speakers into one long turn
# (e.g. a 30 s turn that is mostly someone else). Each window is compared with its own group's
# centroid; a sustained run of windows that do not sound like the group is split out.
REFINE_WINDOW, REFINE_HOP, REFINE_MIN_TURN = 1.6, .8, 4.
FOREIGN_SIM, EXTEND_SIM, MOVE_SIM, MOVE_MARGIN, NEW_GROUP_SIM = .35, .55, .55, .15, .6
MIN_RUN_WINDOWS, MIN_NEW_GROUP_WINDOWS, MIN_NEW_GROUP_SECONDS = 3, 6, 8.


def _unit(vectors):
    center = np.mean(vectors, axis=0)
    norm = np.linalg.norm(center)
    return center / norm if np.isfinite(center).all() and norm > 1e-8 else None


def refine_turns(turns, embed):
    """Split foreign-sounding runs out of long turns. embed(start, end) -> unit vector, may raise ValueError/RuntimeError."""
    width, hop = REFINE_WINDOW, REFINE_HOP
    windows = {}
    for index, turn in enumerate(turns):
        if turn["end"] - turn["start"] < REFINE_MIN_TURN:
            continue
        found, start = [], turn["start"]
        while start + width <= turn["end"] + 1e-9:
            try:
                found.append((start, start + width, embed(start, start + width)))
            except (ValueError, RuntimeError):
                found.append((start, start + width, None))
            start += hop
        windows[index] = found
    centroids = {}
    for group in {t["speaker_group"] for t in turns}:
        pool = [w[2] for i, ws in windows.items() if turns[i]["speaker_group"] == group for w in ws if w[2] is not None]
        center = _unit(pool) if len(pool) >= 5 else None
        for _ in range(3):  # drop outliers so a swallowed speaker does not drag the centroid
            if center is None:
                break
            kept = [v for v in pool if float(v @ center) >= FOREIGN_SIM]
            if len(kept) < 5:
                break
            center = _unit(kept)
        if center is not None:
            centroids[group] = center
    regions = []  # [turn index, start, end, vectors]
    for index, ws in windows.items():
        own = turns[index]["speaker_group"]
        if own not in centroids:
            continue
        sims = [None if w[2] is None else float(w[2] @ centroids[own]) for w in ws]
        # Smooth over three windows (~2.4 s) so one noisy window cannot break a run.
        smooth = [np.mean([v for v in sims[max(0, k - 1):k + 2] if v is not None] or [1.]) for k in range(len(ws))]
        bad = [value < EXTEND_SIM for value in smooth]  # a run may stretch while windows stay doubtful ...
        core = [value < FOREIGN_SIM for value in smooth]  # ... but must contain a sustained, clearly foreign core
        i = 0
        while i < len(ws):
            if not bad[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(ws) and bad[j + 1]:
                j += 1
            streak = best = 0
            for k in range(i, j + 1):
                streak = streak + 1 if core[k] else 0
                best = max(best, streak)
            if best >= MIN_RUN_WINDOWS:
                vectors = [w[2] for w in ws[i:j + 1]]
                start = turns[index]["start"] if i == 0 else ws[i][0] + (width - hop) / 2
                end = turns[index]["end"] if j == len(ws) - 1 else ws[j][1] - (width - hop) / 2
                regions.append([index, start, end, vectors])
            i = j + 1
    if not regions:
        return turns, {"split_turns": 0, "relabeled_seconds": 0., "new_groups": 0}
    own_sim = lambda r: float(_unit(r[3]) @ centroids[turns[r[0]]["speaker_group"]])
    next_id = 1 + max(int(t["speaker_group"].rsplit("_", 1)[1]) for t in turns)
    created, assigned = [], []  # created: [label, vectors]
    for region in regions:
        center = _unit(region[3])
        others = sorted(((float(center @ c), g) for g, c in centroids.items() if g != turns[region[0]]["speaker_group"]), reverse=True)
        label = None
        if others and others[0][0] >= MOVE_SIM and others[0][0] - own_sim(region) >= MOVE_MARGIN:
            label = others[0][1]
        elif len(region[3]) >= MIN_NEW_GROUP_WINDOWS:
            for entry in created:
                if float(center @ _unit(entry[1])) >= NEW_GROUP_SIM:
                    label = entry[0]
                    entry[1].extend(region[3])
                    break
            else:
                label = f"speaker_{next_id:02d}"
                next_id += 1
                created.append([label, list(region[3])])
        if label:
            assigned.append((region[0], region[1], region[2], label))
    # A brand-new group needs corroboration: one isolated short run is more likely noise than a person.
    new_labels = {entry[0] for entry in created}
    seen = {}
    for _, start, end, label in assigned:
        if label in new_labels:
            count, total = seen.get(label, (0, 0.))
            seen[label] = (count + 1, total + end - start)
    weak = {label for label, (count, total) in seen.items() if count < 2 and total < MIN_NEW_GROUP_SECONDS}
    assigned = [a for a in assigned if a[3] not in weak]
    created = [entry for entry in created if entry[0] not in weak]
    by_turn = {}
    for index, start, end, label in assigned:
        by_turn.setdefault(index, []).append((start, end, label))
    output, moved = [], 0.
    for index, turn in enumerate(turns):
        if index not in by_turn:
            output.append(turn)
            continue
        cursor = turn["start"]
        for start, end, label in sorted(by_turn[index]):
            if start - cursor >= .1:
                output.append({**turn, "start": cursor, "end": start})
            output.append({**turn, "start": max(start, cursor), "end": end, "speaker_group": label, "refined_from": turn["speaker_group"]})
            moved += end - max(start, cursor)
            cursor = end
        if turn["end"] - cursor >= .1:
            output.append({**turn, "start": cursor})
    return output, {"split_turns": len(by_turn), "relabeled_seconds": moved, "new_groups": len(created)}


def clean_excerpts(turns, group, maximum=5):
    clean = [t for t in turns if t["speaker_group"] == group and t["end"] - t["start"] >= 2 and not any(
        other["speaker_group"] != group and min(other["end"], t["end"]) > max(other["start"], t["start"]) for other in turns)]
    excerpts = []
    for turn in clean:
        duration = turn["end"] - turn["start"]
        count = max(1, int(duration // 4))
        width = min(6., duration / count)
        for index in range(count):
            start = turn["start"] + index * duration / count
            excerpts.append({"start": start, "end": min(turn["end"], start + width)})
    if not excerpts:
        return []
    return [excerpts[i] for i in sorted(set(np.linspace(0, len(excerpts) - 1, min(maximum, len(excerpts)), dtype=int)))]


def cache_binding(media_hash, turns, model_hash):
    encoded = json.dumps(turns, sort_keys=True, separators=(",", ":")).encode()
    return {"audio_sha256": media_hash, "turns_sha256": hashlib.sha256(encoded).hexdigest(),
            "model_hash": model_hash, "preprocessing": PREPROCESSING, "version": 1}


def valid_cache(cache, binding, labels):
    if not isinstance(cache, dict) or cache.get("binding") != binding or not isinstance(cache.get("vectors"), dict) \
            or set(cache["vectors"]) != set(labels):
        return False
    dimension = None
    for vectors in cache["vectors"].values():
        if not isinstance(vectors, list) or len(vectors) > 5:
            return False
        for raw in vectors:
            try:
                vector = np.asarray(raw, dtype=float)
            except (TypeError, ValueError):
                return False
            if vector.ndim != 1 or not len(vector) or not np.isfinite(vector).all() or abs(np.linalg.norm(vector) - 1) > 1e-5:
                return False
            if dimension is not None and dimension != len(vector):
                return False
            dimension = len(vector)
    return True


def centers_from(cache):
    result = {}
    for label, vectors in cache["vectors"].items():
        if vectors:
            center = _unit([np.asarray(v, dtype=float) for v in vectors])
            if center is not None:
                result[label] = center
    return result


def match_groups(cache, profiles, fingerprint):
    return {label: {**conservative_match([np.asarray(v) for v in vectors], profiles, fingerprint),
                    "excerpt_count": len(vectors)} for label, vectors in cache["vectors"].items()}


def analyze(samples, models, profiles, media_hash, *, speaker_count=None, progress=None, **options):
    """Cluster speakers over the whole recording; independent of the transcript."""
    if speaker_count is not None and (type(speaker_count) is not int or not 1 <= speaker_count <= 32):
        raise ValueError("講者人數需為 1–32 的整數或空白")
    settings = {**DEFAULTS, **{k: v for k, v in options.items() if v is not None}}
    if not .05 <= settings["cluster_threshold"] <= 2 or not .1 <= settings["window_shift"] <= 1:
        raise ValueError("分群門檻需為 0.05–2.0，視窗位移需為 0.1–1.0")
    import sherpa_onnx
    threads = hardware.diarization_threads()
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(models["segmentation"]), window_shift_ratio=settings["window_shift"]),
            num_threads=threads, provider="cpu"),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(models["embedding"]), num_threads=threads, provider="cpu"),
        # A user-supplied head count is the strongest evidence available; otherwise rely on the distance threshold.
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=speaker_count or -1, threshold=settings["cluster_threshold"]),
        min_duration_on=settings["min_duration_on"], min_duration_off=settings["min_duration_off"])
    if not config.validate():
        raise ValueError("講者分段模型設定無效")
    engine = sherpa_onnx.OfflineSpeakerDiarization(config)

    def callback(done, total):
        if progress:
            progress(done, total)
        return 0
    raw = engine.process(floats(samples), callback=callback).sort_by_start_time()
    turns = [{"start": float(t.start), "end": float(t.end), "speaker_group": f"speaker_{t.speaker:02d}"} for t in raw]
    del engine
    gc.collect()
    if not turns:
        raise ValueError("未偵測到可分群的語音")
    fingerprint = model_digest(models["embedding"])
    extract = extractor(models["embedding"], threads)
    refine = {"split_turns": 0, "relabeled_seconds": 0., "new_groups": 0}
    if speaker_count is None:
        turns, refine = refine_turns(turns, lambda a, b: embedding(extract, floats(samples, a, b)))
    vectors = {}
    for group in sorted({t["speaker_group"] for t in turns}):
        vectors[group] = []
        for excerpt in clean_excerpts(turns, group):
            try:
                vectors[group].append(embedding(extract, floats(samples, excerpt["start"], excerpt["end"])).tolist())
            except (ValueError, RuntimeError):
                continue
    cache = {"binding": cache_binding(media_hash, turns, fingerprint), "vectors": vectors}
    return {"turns": turns, "groups": match_groups(cache, profiles, fingerprint), "cache": cache,
            "metrics": {**settings, "speaker_count": speaker_count, "observed_speaker_count": len(vectors), "threads": threads,
                        "audio_duration_seconds": len(samples) / RATE, "embedding_model_hash": fingerprint,
                        "preprocessing": PREPROCESSING, "turn_refinement": refine}}


def assign(samples, models, spans, analysis):
    """Label transcript spans. Loads the embedding model once for voice-evidence tie-breaks."""
    cache = analysis["cache"]
    centers = centers_from(cache)
    engine = [None]

    def score(span, candidates):
        available = [g for g in candidates if g in centers]
        if not available:
            return {}
        if engine[0] is None:
            engine[0] = extractor(models["embedding"])
        vector = embedding(engine[0], floats(samples, span["start"], span["end"]))
        return {g: float(np.dot(vector, centers[g])) for g in available}
    return attach_turns(spans, analysis["turns"], sorted(cache["vectors"]), score if centers else None)


def build_voiceprint(media_hash, turns, cache, group, model_hash):
    """Voiceprint from the clean excerpts already embedded during analysis. Conservative: refuse weak evidence."""
    labels = sorted({t["speaker_group"] for t in turns if t.get("speaker_group") is not None})
    if group not in labels:
        raise AppError("NOT_FOUND", "找不到此講者分群，請先執行講者分析。")
    if not valid_cache(cache, cache_binding(media_hash, turns, model_hash), labels):
        raise AppError("STALE_ANALYSIS", "講者分析快取已失效（模型或分段有變），請重新分析講者後再註冊。")
    vectors = [np.asarray(v, dtype=float) for v in cache["vectors"][group]]
    if len(vectors) < 3:
        raise AppError("INSUFFICIENT_AUDIO", f"此講者可用的乾淨語音不足（{len(vectors)} 段，至少需要 3 段）。")
    center = np.mean(vectors, axis=0)
    norm = np.linalg.norm(center)
    if not np.isfinite(center).all() or norm < 1e-8:
        raise AppError("INSUFFICIENT_AUDIO", "無法由會議語音建立有效聲紋。")
    center = center / norm
    consistency = min(float(v @ center) for v in vectors)
    if consistency < .5:
        raise AppError("INCONSISTENT_AUDIO", "此分群的語音彼此差異過大，可能混入多位講者；請先調整分群。")
    excerpts = clean_excerpts(turns, group)
    return {"embedding": center.tolist(), "model_hash": model_hash,
            "quality": {"preprocessing": PREPROCESSING, "source": "project", "speaker_group": group,
                        "excerpt_count": len(vectors), "consistency": consistency,
                        "duration_seconds": float(sum(e["end"] - e["start"] for e in excerpts))}}


def conflicting_person(embedding_vector, others):
    """others: voiceprint rows of other people. Returns (person_id, name) when voices are too alike to coexist."""
    vector = np.asarray(embedding_vector, dtype=float)
    for row in others:
        reference = np.asarray(row["embedding"], dtype=float)
        if reference.shape != vector.shape or np.linalg.norm(reference) < 1e-8:
            continue
        if float(vector @ (reference / np.linalg.norm(reference))) >= MATCH_THRESHOLD:
            return row["person_id"], row["name"]
    return None
