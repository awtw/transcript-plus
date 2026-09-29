import json
import sys
from types import SimpleNamespace

import pytest

from transcript_plus.asr import parameters, transcribe
from transcript_plus.models import inspect_model, status
from transcript_plus.errors import AppError


def test_ct2_quality_preserves_context_and_quiet_speech(monkeypatch):
    calls = {}
    class Decoder:
        def __init__(self, path, **kw):
            calls.update(init=kw)
        def transcribe(self, audio, **kw):
            calls.update(parameters=kw)
            return iter([SimpleNamespace(start=0, end=1, text="台灣", words=None)]), SimpleNamespace(language="zh")
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Decoder))
    segments, language = transcribe('local.wav', {'path': '/model'}, parameters('faster-whisper'))
    assert list(segments)[0]['text'] == '台灣'
    assert language == 'zh'
    assert calls['init']['local_files_only'] is True
    assert calls['parameters']['condition_on_previous_text'] is True
    assert calls['parameters']['vad_filter'] is False
    assert calls['parameters']['word_timestamps'] is False
    assert calls['parameters']['language'] is None
    assert calls['parameters']['temperature'] == 0
    assert calls['parameters']['task'] == 'transcribe'


def test_mlx_uses_local_model_and_fabo_decoder(monkeypatch):
    calls = {}
    def infer(audio, **kw):
        calls.update(audio=audio, **kw)
        return {'segments': [{'text': '會議', 'start': 0, 'end': 1}], 'language': 'zh'}
    monkeypatch.setitem(sys.modules, 'mlx_whisper', SimpleNamespace(transcribe=infer))
    monkeypatch.setitem(sys.modules, 'faster_whisper.audio', SimpleNamespace(decode_audio=lambda path, sampling_rate: (path, sampling_rate)))
    output, language = transcribe('meeting.m4a', {'path': '/local/breeze', 'engine': 'mlx'}, parameters('mlx'))
    assert list(output)[0]['text'] == '會議' and language == 'zh'
    assert calls['path_or_hf_repo'] == '/local/breeze'
    assert calls['audio'] == ('meeting.m4a', 16000)
    assert calls['fp16'] and calls['condition_on_previous_text']
    assert 'beam_size' not in calls and 'vad_filter' not in calls


@pytest.mark.parametrize('weight', ['weights.safetensors', 'weights.npz'])
def test_inspect_mlx_hashes_weights(tmp_path, monkeypatch, weight):
    monkeypatch.setattr('transcript_plus.models.platform.system', lambda: 'Darwin')
    monkeypatch.setattr('transcript_plus.models.platform.machine', lambda: 'arm64')
    for name in ['config.json', weight]:
        (tmp_path / name).write_text('{}')
    result = inspect_model(tmp_path)
    assert result['engine'] == 'mlx' and result['model_hash'] == result['files'][weight]


def test_job_snapshots_quality_settings(service, tmp_path):
    service.store.set_setting('asr_model', {'path': str(tmp_path), 'engine': 'mlx'})
    service.dispatch('job.start', {'project_id': 'p1', 'word_timestamps': True})
    snapshot = json.loads(service.store.jobs()[0]['parameters'])
    assert snapshot['asr_parameters']['word_timestamps'] is True
    assert snapshot['asr_parameters']['condition_on_previous_text'] is True
    assert snapshot['asr_parameters']['language'] is None
    with pytest.raises(AppError):
        service.dispatch('job.start', {'project_id': 'p1', 'word_timestamps': 'false'})


def test_native_library_failure_is_not_reported_as_missing_engine(monkeypatch):
    import builtins
    original = builtins.__import__
    def fail(name, *args, **kwargs):
        if name == 'mlx_whisper':
            raise ImportError('Failed to load the default metallib.')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', fail)
    with pytest.raises(AppError) as error:
        transcribe('meeting.m4a', {'path': '/local/breeze', 'engine': 'mlx'}, parameters('mlx'))
    assert error.value.code == 'RUNTIME_LOAD_FAILED'


def test_mlx_progress_reports_during_inference_even_when_tqdm_disabled(monkeypatch):
    from transcript_plus.asr import mlx_progress
    original = object()
    module = SimpleNamespace(tqdm=original, HOP_LENGTH=160, SAMPLE_RATE=16000)
    monkeypatch.setitem(sys.modules, 'mlx_whisper.transcribe', module)
    values = []
    with mlx_progress(values.append):
        with module.tqdm.tqdm(total=9000, unit='frames', disable=True) as bar:
            assert values == [0]
            bar.update(3000)
            assert values == [0, 30000]  # Before inference returns, not after.
            bar.update(-100)
            bar.update(200)
            bar.update(90000)
        assert values == [0, 30000, 31000, 90000]
    assert module.tqdm is original


def test_mlx_progress_restores_adapter_on_failure_without_fake_completion(monkeypatch):
    from transcript_plus.asr import mlx_progress
    original = object()
    module = SimpleNamespace(tqdm=original, HOP_LENGTH=160, SAMPLE_RATE=16000)
    monkeypatch.setitem(sys.modules, 'mlx_whisper.transcribe', module)
    values = []
    with pytest.raises(RuntimeError):
        with mlx_progress(values.append):
            with module.tqdm.tqdm(total=9000, disable=True) as bar:
                bar.update(1000)
                raise RuntimeError('inference failed')
    assert module.tqdm is original
    assert values == [0, 10000]
