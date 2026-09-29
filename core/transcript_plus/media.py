import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .errors import AppError, require

SUFFIXES = {".wav", ".mp3", ".m4a", ".mp4", ".mov"}
MAX_BYTES = 4 * 1024**3


def binary(name):
    suffix = ".exe" if os.name == "nt" else ""
    # Frozen applications only use bundled executables, never a user's PATH.
    if getattr(sys, "frozen", False):
        candidate = Path(sys._MEIPASS) / "bin" / (name+suffix)
        require(candidate.is_file(), "RUNTIME_MISSING", f"安裝包缺少 {name}，請重新安裝。")
        return str(candidate)
    result = shutil.which(name)
    require(result, "RUNTIME_MISSING", f"開發環境缺少 {name}。")
    return result


def process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path):
    source = Path(path).resolve(strict=True)
    require(source.is_file() and source.suffix.lower() in SUFFIXES,
            "UNSUPPORTED_CODEC", "請選擇 WAV、MP3、M4A、MP4 或 MOV 檔案。")
    require(0 < source.stat().st_size <= MAX_BYTES, "FILE_TOO_LARGE", "檔案不可為空或超過 4 GiB。")
    try:
        result = subprocess.run([binary("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)],
                                capture_output=True, timeout=30, **process_options())
        info = json.loads(result.stdout)
        streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
        require(streams, "NO_AUDIO", "這個檔案沒有可用的音訊軌。")
        duration = float(info.get("format", {}).get("duration") or streams[0].get("duration", 0))
        require(math.isfinite(duration) and 0 < duration <= 7200, "FILE_TOO_LONG", "音訊長度必須介於 0 與 120 分鐘。")
        start = float(streams[0].get("start_time", 0)) - float(info.get("format", {}).get("start_time", 0))
        # Full multi-track / timestamp discontinuity normalization is a later release gate.
        require(abs(start) < 0.1, "UNSUPPORTED_TIMELINE", "這個檔案的音軌起點有偏移，目前請先轉成 WAV 再匯入。")
        return {"duration_ms": round(duration*1000), "audio_stream": streams[0]["index"],
                "codec": streams[0].get("codec_name"),
                "has_video": any(s.get("codec_type") == "video" for s in info.get("streams", [])),
                "timeline_origin": "container_start", "audio_offset_ms": round(start*1000)}
    except (ValueError, KeyError, subprocess.TimeoutExpired):
        raise AppError("UNSUPPORTED_CODEC", "影音無法解析或已損壞。") from None


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix+".partial")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
