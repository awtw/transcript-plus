"""Exercise the final app's embedded core, not the pre-bundle dist directory."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--core', required=True, help='Final .app/Contents/Resources/core/transcript-core')
    parser.add_argument('--model', required=True)
    parser.add_argument('--audio', required=True)
    parser.add_argument('--data-dir', required=True, help='Isolated smoke workspace')
    parser.add_argument('--speaker-models', help='Folder with segmentation/model.onnx and nemo_en_titanet_small.onnx; also checks speaker grouping')
    parser.add_argument('--require-progress', action='store_true', help='Use a 60–90 second clip to observe intermediate ASR progress')
    args = parser.parse_args()
    root = Path(args.data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'core.log').open('w') as log:
        env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
        if os.name != 'nt':
            env['PATH'] = '/usr/bin:/bin'
        process = subprocess.Popen([str(Path(args.core).resolve()), '--data-dir', str(root)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                   cwd=root, env=env, text=True)
        def rpc(method, params=None):
            process.stdin.write(json.dumps({'protocol_version': 1, 'request_id': 1,
                                           'method': method, 'params': params or {}}) + '\n')
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                raise RuntimeError('Packaged core exited; inspect core.log')
            result = json.loads(line)
            if 'error' in result:
                raise RuntimeError(result['error'])
            return result['result']
        try:
            rpc('model.configure', {'path': str(Path(args.model).resolve())})
            project = rpc('project.import', {'path': str(Path(args.audio).resolve())})
            playback = rpc('project.playback', {'project_id': project['id']})
            if args.speaker_models:
                rpc('model.configure_speakers', {'path': str(Path(args.speaker_models).resolve())})
            job_id = rpc('job.start', {'project_id': project['id'], 'diarize': bool(args.speaker_models)})['job_id']
            saw_progress = False
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                job = next(j for j in rpc('job.list') if j['id'] == job_id)
                if job['status'] == 'running' and job['stage'] == 'asr' and 0 < (job['processed_ms'] or 0) < project['duration_ms']:
                    saw_progress = True
                if job['status'] not in ('queued', 'running'):
                    if job['status'] != 'completed':
                        raise RuntimeError(job)
                    doc = rpc('project.get', {'project_id': project['id']})['transcript']
                    if args.require_progress:
                        assert saw_progress, 'No intermediate progress observed in the final app core'
                    assert doc['segments'], 'Use a short audible speech clip'
                    summary = rpc('project.get', {'project_id': project['id']})['speaker_summary']
                    if args.speaker_models:
                        assert summary and summary['groups'], f'Speaker analysis produced no groups: {job}'
                    assert Path(playback['media_path']).is_file()
                    print(json.dumps({'status': job['status'], 'engine': doc['engine'],
                                      'segments': len(doc['segments']), 'playback': True, 'intermediate_progress': saw_progress,
                                      'speaker_groups': len(summary['groups']) if summary else 0}))
                    return
                time.sleep(1)
            raise TimeoutError('Packaged ASR exceeded 300 seconds')
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()


if __name__ == '__main__':
    main()
