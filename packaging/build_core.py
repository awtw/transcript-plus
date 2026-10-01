"""Run with the project venv on the target OS. Produces a self-contained onedir core."""
import os
import importlib.util
import platform
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "apps/desktop/src-tauri/resources/core"


def main():
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "transcript-core",
               "--distpath", str(ROOT / "dist/core"), "--workpath", str(ROOT / "build/core"),
               "--specpath", str(ROOT / "build"), "--paths", str(ROOT / "core"),
               "--collect-all", "faster_whisper", "--collect-all", "ctranslate2", "--collect-all", "onnxruntime",
               "--collect-all", "tokenizers", "--collect-all", "av", "--collect-all", "regex",
               "--collect-all", "sherpa_onnx", "--collect-all", "psutil",
               "--hidden-import", "transcript_plus.worker", "--hidden-import", "transcript_plus.service",
               "--hidden-import", "transcript_plus.diarization", "--hidden-import", "transcript_plus.speakers"]
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        # Pin the wheel's JACCL: dyld discovery may otherwise pick Homebrew's
        # incompatible libjaccl.dylib when resolving MLX's @rpath dependency.
        mlx_root = Path(next(iter(importlib.util.find_spec("mlx").submodule_search_locations)))
        # Resource copying may dereference libmlx's root symlink. Keep the
        # Metal kernels alongside both the root and nested library locations.
        command.extend(["--add-data", f"{mlx_root / 'lib' / 'mlx.metallib'}{os.pathsep}."])
        jaccl = mlx_root / "lib" / "libjaccl.dylib"
        if jaccl.is_file():
            command.extend(["--add-binary", f"{jaccl}{os.pathsep}."])
        for package in ("mlx_whisper", "mlx", "tiktoken"):
            command.extend(["--collect-all", package])
    for name in ("ffmpeg", "ffprobe"):
        binary = shutil.which(name)
        if not binary:
            raise SystemExit(f"Missing build dependency: {name}")
        command.extend(["--add-binary", f"{binary}{os.pathsep}bin"])
    command.append(str(ROOT / "packaging/entrypoint.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(ROOT / "dist/core/transcript-core", DEST)
    print(f"Core bundle ready: {DEST}")


if __name__ == "__main__":
    main()
