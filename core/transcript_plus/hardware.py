"""Hardware detection shared by ASR, diarization and the worker. Stdlib only; never raises."""
import functools
import os
import platform


def _integer(name):
    try:
        return max(1, int(os.environ[name]))
    except (KeyError, ValueError):
        return None


def is_apple_silicon():
    return platform.system() == "Darwin" and platform.machine().lower() in ("arm64", "aarch64")


@functools.lru_cache(maxsize=1)
def physical_cores():
    try:
        import psutil
        count = psutil.cpu_count(logical=False)
        if count:
            return count
    except Exception:
        pass
    return max(1, os.cpu_count() or 1)


@functools.lru_cache(maxsize=1)
def memory_bytes():
    try:
        import psutil
        return psutil.virtual_memory().total
    except Exception:
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        return 0


@functools.lru_cache(maxsize=1)
def cuda_device_count():
    """CTranslate2 only: CUDA is usable by faster-whisper exactly when its own build sees a device."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def concurrent_stages():
    """Run ASR and speaker analysis side by side. TP_CONCURRENT_STAGES=0/1 overrides auto."""
    setting = os.environ.get("TP_CONCURRENT_STAGES", "auto").lower()
    if setting in ("0", "false"):
        return False
    if setting in ("1", "true"):
        return True
    return physical_cores() >= 4 and memory_bytes() >= 12 * 1024 ** 3


def _asr_on_cpu():
    return os.environ.get("TP_DEVICE", "auto").lower() == "cpu" or (cuda_device_count() == 0 and not is_apple_silicon())


def diarization_threads():
    explicit = _integer("TP_DIARIZATION_THREADS")
    if explicit:
        return min(explicit, 32)
    cores = physical_cores()
    # ASR on a GPU/Metal leaves the CPU free; otherwise share it with the ASR lane.
    if concurrent_stages() and _asr_on_cpu():
        return max(2, cores // 3)
    return max(2, min(cores, 8))


def ct2_runtime(prefer_cuda=True):
    """Device, compute type and CPU threads for faster-whisper. TP_DEVICE=auto|cuda|cpu."""
    requested = os.environ.get("TP_DEVICE", "auto").lower()
    if requested not in ("auto", "cuda", "cpu"):
        raise ValueError("TP_DEVICE 必須是 auto、cuda 或 cpu")
    cores = physical_cores()
    if prefer_cuda and requested != "cpu" and cuda_device_count() > 0:
        return {"device": "cuda", "compute_type": os.environ.get("TP_CUDA_COMPUTE_TYPE", "float16"),
                "cpu_threads": min(cores, 4)}
    # Leave cores for the diarization lane when both stages run at once.
    default = max(2, cores - diarization_threads()) if concurrent_stages() else cores
    return {"device": "cpu", "compute_type": "int8", "cpu_threads": _integer("TP_CPU_THREADS") or default}
