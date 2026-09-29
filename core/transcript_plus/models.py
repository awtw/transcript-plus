import importlib.util
import platform
from pathlib import Path

from .errors import require
from .media import file_hash


REQUIRED = ("model.bin", "config.json", "tokenizer.json")


def inspect_model(path):
    directory = Path(path).resolve(strict=True)
    require(directory.is_dir(), "MODEL_MISSING", "請選擇本機模型資料夾。")
    engine, required = "faster-whisper", REQUIRED
    if not (directory / "model.bin").is_file():
        weights = "weights.safetensors" if (directory / "weights.safetensors").is_file() else "weights.npz"
        engine, required = "mlx", ("config.json", weights)
        require(platform.system() == "Darwin" and platform.machine().lower() in ("arm64", "aarch64"),
                "MODEL_UNSUPPORTED", "MLX 模型需要 Apple Silicon Mac，其他電腦請選 CTranslate2 模型。")
    require(all((directory / name).is_file() for name in required), "MODEL_MISSING",
            "請選 CTranslate2（model.bin、config.json、tokenizer.json）或 MLX（config.json、weights.safetensors／weights.npz）模型。")
    files = {name: file_hash(directory / name) for name in required}
    return {"path": str(directory), "name": directory.name, "engine": engine,
            "files": files, "model_hash": files["model.bin" if engine == "faster-whisper" else weights],
            "size_bytes": sum((directory / name).stat().st_size for name in required)}


def status(store):
    model = store.setting("asr_model")
    available = bool(model and all((Path(model["path"]) / n).is_file() for n in model.get("files", REQUIRED)))
    engine = model.get("engine", "faster-whisper") if model else "faster-whisper"
    runtime = importlib.util.find_spec("faster_whisper") is not None
    if engine == "mlx":
        runtime = runtime and platform.system() == "Darwin" and platform.machine().lower() in ("arm64", "aarch64") and importlib.util.find_spec("mlx_whisper") is not None
    return {"model": model, "available": available,
            "runtime_available": runtime,
            "diarization_available": False, "summary_available": False}
