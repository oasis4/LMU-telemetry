"""Exercise the frozen worker from an unrelated directory with no runtimes on PATH."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

exe = Path(sys.argv[1]).resolve()
fixture = Path(__file__).resolve().parent.parent / 'tests/fixtures/monza_q_3laps.duckdb'
with tempfile.TemporaryDirectory(prefix='LMU smoke é ') as temp:
    root = Path(temp)
    bundle = root / 'App with spaces é'
    shutil.copytree(exe.parent, bundle)
    recordings = root / 'recordings'
    recordings.mkdir()
    shutil.copy2(fixture, recordings)
    ready = root / 'ready.json'
    env = {**os.environ, 'LOCALAPPDATA': str(root / 'state'), 'PATH': ''}
    # The worker must select its own port even when the former fixed port is busy.
    with socket.socket() as occupied:
        try:
            occupied.bind(('127.0.0.1', 8000))
            occupied.listen()
        except OSError:
            pass  # Already occupied is equally useful for this check.
        proc = subprocess.Popen([str(bundle / exe.name), '--worker', 'api',
                                 '--recordings', str(recordings), '--readiness', str(ready)],
                                cwd=root, env=env)
        try:
            deadline = time.monotonic() + 60
            while not ready.exists():
                if proc.poll() is not None or time.monotonic() > deadline:
                    log = root / 'state/LMU Telemetry/api.log'
                    raise RuntimeError(log.read_text(encoding='utf-8') if log.exists() else 'No readiness signal')
                time.sleep(.2)
            url = json.loads(ready.read_text(encoding='utf-8'))['url']
            def get(path):
                with urllib.request.urlopen(url + path, timeout=30) as response:
                    return response.read()
            # Readiness is emitted during startup; allow the socket to begin serving.
            for attempt in range(100):
                try:
                    get('/api/health')
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('Server never became healthy')
            for path in ('/', '/ideal', '/recordings', '/sharing'):
                assert b'<html' in get(path)
            sessions = json.loads(get('/api/sessions'))['sessions']
            assert sessions, 'Fixture recording was not discovered'
            # Force numerical processing and bundled track-data access.
            from urllib.parse import quote
            name = fixture.name
            assert json.loads(get('/api/sessions/' + quote(name) + '/laps'))['laps']
            assert get('/api/sessions/' + quote(name) + '/map')
            def write(method, path, body=None):
                request = urllib.request.Request(url + path, method=method,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.loads(response.read())
            publish_dir = root / 'published laps é'
            write('PUT', '/api/sharing/settings', {'publish_dir': str(publish_dir)})
            published = write('POST', '/api/sessions/' + quote(name) + '/laps/2/share')
            lap_file = publish_dir / published['filename']
            assert lap_file.is_file()
            # Publication validates package data in the frozen process,
            # with no Drive network dependency in this smoke test.
            assert json.loads(get('/api/sharing'))['published'][0]['id'] == published['id']
            write('DELETE', '/api/sharing/published/' + published['id'])
            assert not lap_file.exists()
        finally:
            proc.terminate()
            proc.wait(timeout=15)
    overlay = subprocess.run([str(bundle / exe.name), '--worker', 'overlay',
                              '--recordings', str(recordings)], cwd=root, env=env, timeout=30)
    assert overlay.returncode != 0, 'Expected game-unavailable failure in CI'
    log = (root / 'state/LMU Telemetry/overlay.log').read_text(encoding='utf-8')
    assert 'Traceback' not in log, log
    assert 'Le Mans Ultimate must be running' in log, log
print('Frozen Windows smoke test passed')
