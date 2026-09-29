import importlib.util
from pathlib import Path

from .errors import require
from .media import file_hash


REQUIRED = ("model.bin", "config.json", "tokenizer.json")


def inspect_model(path):
    directory = Path(path).resolve(strict=True)
    require(directory.is_dir(), "MODEL_MISSING", "請選擇本機 CTranslate2 模型資料夾。")
    require(all((directory / name).is_file() for name in REQUIRED), "MODEL_MISSING",
            "模型資料夾必須包含 model.bin、config.json 與 tokenizer.json。")
    files = {name: file_hash(directory / name) for name in REQUIRED}
    return {"path": str(directory), "name": directory.name, "engine": "faster-whisper",
            "files": files, "model_hash": files["model.bin"],
            "size_bytes": sum((directory / name).stat().st_size for name in REQUIRED)}


def status(store):
    model = store.setting("asr_model")
    available = bool(model and all((Path(model["path"]) / n).is_file() for n in REQUIRED))
    return {"model": model, "available": available,
            "runtime_available": importlib.util.find_spec("faster_whisper") is not None,
            "diarization_available": False, "summary_available": False}
