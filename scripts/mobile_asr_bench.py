"""Benchmark mobile ASR candidates (whisper.cpp GGML builds) on a Mac, against the desktop Breeze model.

This measures wall time, peak memory and *agreement with the desktop model's output*. It is NOT accuracy
against a human transcript and NOT phone performance; run the same GGML files on a real device (M1 gate).

Usage:
  uv run python scripts/mobile_asr_bench.py AUDIO.wav --reference-mlx /path/to/breeze-asr-25-mlx \
      --model q5_0=.local-data/mobile-models/ggml-breeze-asr-25-q5_0.bin [--model name=path ...]
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import regex

RSS = re.compile(r"(\d+)\s+maximum resident set size")


def lexical(text):
    return regex.sub(r"[\p{P}\p{Z}\s]", "", text)


def edit_distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True)
    return float(out.stdout)


def reference_text(audio, model):
    import mlx_whisper
    from faster_whisper.audio import decode_audio
    start = time.time()
    result = mlx_whisper.transcribe(decode_audio(audio), path_or_hf_repo=model, verbose=None)
    return result["text"], time.time() - start


def run_cpp(audio, model, cpu_only):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        command = ["/usr/bin/time", "-l", "whisper-cli", "-m", model, "-f", audio, "-l", "auto", "-oj", "-of", str(out), "-np"]
        if cpu_only:
            command.append("-ng")
        start = time.time()
        proc = subprocess.run(command, capture_output=True, text=True)
        elapsed = time.time() - start
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-500:])
        text = "".join(item["text"] for item in json.loads(out.with_suffix(".json").read_text())["transcription"])
        match = RSS.search(proc.stderr)
        return text, elapsed, int(match.group(1)) / 1e9 if match else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--reference-mlx", required=True)
    parser.add_argument("--model", action="append", required=True, help="name=path to a GGML model")
    args = parser.parse_args()

    seconds = duration(args.audio)
    ref, ref_time = reference_text(args.audio, args.reference_mlx)
    ref_norm = lexical(ref)
    rows = [{"name": "desktop-mlx (reference)", "rtf": ref_time / seconds, "peak_gb": None, "diff": 0.0}]
    for spec in args.model:
        name, path = spec.split("=", 1)
        for cpu_only in (False, True):
            try:
                text, elapsed, peak = run_cpp(args.audio, path, cpu_only)
            except RuntimeError as exc:
                print(f"{name} failed: {exc}", file=sys.stderr)
                continue
            diff = edit_distance(ref_norm, lexical(text)) / max(1, len(ref_norm))
            rows.append({"name": f"{name} {'cpu' if cpu_only else 'gpu'}", "rtf": elapsed / seconds, "peak_gb": peak, "diff": diff})
    print(f"audio: {seconds:.1f}s; reference chars: {len(ref_norm)}")
    print(f"{'candidate':28} {'RTF':>6} {'peak GB':>8} {'diff vs desktop':>16}")
    for row in rows:
        peak = f"{row['peak_gb']:.2f}" if row["peak_gb"] else "-"
        print(f"{row['name']:28} {row['rtf']:6.2f} {peak:>8} {row['diff']:15.1%}")


if __name__ == "__main__":
    main()
