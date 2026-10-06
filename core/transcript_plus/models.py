import importlib.util
import platform
from pathlib import Path

from .errors import require
from .asr import plain_path
from .media import file_hash


REQUIRED = ("model.bin", "config.json", "tokenizer.json")
VOICEPRINT_DEFAULT = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"


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
    return {"path": plain_path(directory), "name": directory.name, "engine": engine,
            "files": files, "model_hash": files["model.bin" if engine == "faster-whisper" else weights],
            "size_bytes": sum((directory / name).stat().st_size for name in required)}


def find_speaker_models(path):
    """Accept the folder fabo-asr uses (segmentation/model.onnx + nemo_en_titanet_small.onnx) or a flat folder."""
    root = Path(path).resolve(strict=True)
    require(root.is_dir(), "MODEL_MISSING", "請選擇講者模型資料夾。")
    segmentation = next((p for p in (root / "segmentation" / "model.onnx", root / "model.onnx",
                                     root / "segmentation" / "model.int8.onnx", root / "model.int8.onnx") if p.is_file()), None)
    embedding = next((p for p in (root / "nemo_en_titanet_small.onnx", *sorted(root.glob("*titanet*.onnx"))) if p.is_file()), None)
    require(segmentation and embedding, "MODEL_MISSING",
            "請選含 segmentation/model.onnx（pyannote 分段）與 nemo_en_titanet_small.onnx（聲紋）的資料夾。")
    # Optional Chinese voiceprint model (ERes2Net): identifies *who* far better than TitaNet, while TitaNet clusters better.
    voiceprint = next((p for p in (root / VOICEPRINT_DEFAULT,) if p.is_file()), None)
    result = {"segmentation": plain_path(segmentation), "embedding": plain_path(embedding), "name": root.name,
              "hashes": {"segmentation": file_hash(segmentation), "embedding": file_hash(embedding)}}
    if voiceprint:
        result["voiceprint"] = plain_path(voiceprint)
        result["hashes"]["voiceprint"] = file_hash(voiceprint)
    return result


def diarization_ready(store):
    models = store.setting("speaker_models")
    runtime = all(importlib.util.find_spec(name) is not None for name in ("sherpa_onnx", "numpy"))
    available = bool(models and all(Path(models[key]).is_file() for key in ("segmentation", "embedding"))
                     and Path(models.get("voiceprint") or models["embedding"]).is_file())
    return models, available, runtime


def status(store):
    model = store.setting("asr_model")
    available = bool(model and all((Path(model["path"]) / n).is_file() for n in model.get("files", REQUIRED)))
    engine = model.get("engine", "faster-whisper") if model else "faster-whisper"
    runtime = importlib.util.find_spec("faster_whisper") is not None
    if engine == "mlx":
        runtime = runtime and platform.system() == "Darwin" and platform.machine().lower() in ("arm64", "aarch64") and importlib.util.find_spec("mlx_whisper") is not None
    speaker_models, speakers_available, speakers_runtime = diarization_ready(store)
    return {"model": model, "available": available,
            "runtime_available": runtime,
            "speaker_model": {"name": speaker_models["name"], "voiceprint": bool(speaker_models.get("voiceprint"))} if speaker_models else None,
            "diarization_available": speakers_available and speakers_runtime,
            "summary_available": False}
