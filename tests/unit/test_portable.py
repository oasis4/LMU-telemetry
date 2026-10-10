import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from lmu_telemetry.api.app import create_app
import start


def test_static_frontend_does_not_mask_api_or_missing_assets(tmp_path):
    web = tmp_path / 'web'
    web.mkdir()
    (web / 'index.html').write_text('<html>app</html>')
    (web / 'assets').mkdir()
    (web / 'assets/app.js').write_text('console.log(1)')
    client = TestClient(create_app(tmp_path, cache_dir=tmp_path / 'cache', frontend_dir=web))
    for path in ('/', '/ideal', '/recordings', '/sharing'):
        assert client.get(path).text == '<html>app</html>'
    assert client.get('/assets/app.js').text == 'console.log(1)'
    assert client.get('/api/health').status_code == 200
    for path in ('/api', '/api/missing', '/assets/missing.js', '/%2e%2e/secret'):
        assert client.get(path).status_code == 404


def test_missing_frontend_fails_at_startup(tmp_path):
    with pytest.raises(ValueError, match='Built frontend missing'):
        create_app(tmp_path, frontend_dir=tmp_path)


def test_frozen_command_never_invokes_python_module_or_npm(monkeypatch, tmp_path):
    monkeypatch.setattr(start.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(start.sys, 'executable', 'LMU Telemetry.exe')
    assert start.worker_command('overlay', tmp_path) == [
        'LMU Telemetry.exe', '--worker', 'overlay', '--recordings', str(tmp_path)]
    assert '--readiness' in start.worker_command('api', tmp_path, tmp_path / 'ready')


def test_saved_folder_is_user_local_and_validated(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    folder = tmp_path / 'recordings é'
    folder.mkdir()
    state = start.state_dir()
    state.mkdir()
    settings = state / 'settings.json'
    settings.write_text(json.dumps({'telemetry_dir': str(folder)}))
    assert start.load_folder() == str(folder)
    folder.rmdir()
    assert start.load_folder() == ''
    settings.write_text('{broken')
    assert start.load_folder() == ''


def test_stop_escalates_only_for_owned_running_process():
    proc = Mock()
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired('worker', 5), 0]
    start.stop_process(proc)
    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()
    done = Mock()
    done.poll.return_value = 1
    start.stop_process(done)
    done.terminate.assert_not_called()


def launcher_without_window(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    app = start.LauncherApp.__new__(start.LauncherApp)
    app.processes = {'api': None, 'overlay': None}
    app.status = {mode: Mock() for mode in app.processes}
    app.buttons = {mode: (Mock(), Mock()) for mode in app.processes}
    app.open_button = Mock()
    app.root = Mock()
    app.readiness = tmp_path / 'ready'
    app.url = 'http://127.0.0.1:12345'
    app.started = {}
    app.folder = Mock()
    return app


def test_independent_stop_and_close(monkeypatch, tmp_path):
    app = launcher_without_window(tmp_path, monkeypatch)
    api, overlay = Mock(), Mock()
    api.poll.return_value = overlay.poll.return_value = None
    app.processes.update(api=api, overlay=overlay)
    app.stop('api')
    api.terminate.assert_called_once()
    overlay.terminate.assert_not_called()
    app.close()
    overlay.terminate.assert_called_once()
    app.root.destroy.assert_called_once()


def test_startup_failure_is_visible(monkeypatch, tmp_path):
    app = launcher_without_window(tmp_path, monkeypatch)
    (tmp_path / 'session.duckdb').touch()
    app.folder.get.return_value = str(tmp_path)
    monkeypatch.setattr(start.subprocess, 'Popen', Mock(side_effect=OSError('cannot launch')))
    app.start('api')
    assert 'cannot launch' in app.status['api'].set.call_args.args[0]
    assert app.processes['api'] is None


def test_unexpected_exit_shows_log(monkeypatch, tmp_path):
    app = launcher_without_window(tmp_path, monkeypatch)
    start.state_dir().mkdir()
    (start.state_dir() / 'overlay.log').write_text('game is unavailable')
    proc = Mock(returncode=1)
    proc.poll.return_value = 1
    app.processes['overlay'] = proc
    app.poll()
    assert 'game is unavailable' in app.status['overlay'].set.call_args.args[0]
    assert app.processes['overlay'] is None


def test_browser_opens_only_after_worker_health_succeeds(monkeypatch, tmp_path):
    app = launcher_without_window(tmp_path, monkeypatch)
    app.url = None
    proc = Mock()
    proc.poll.return_value = None
    app.processes['api'] = proc
    app.started['api'] = start.time.monotonic()
    app.readiness.write_text(json.dumps({'url': 'http://127.0.0.1:43210'}))
    opener = Mock()
    monkeypatch.setattr(start.webbrowser, 'open', opener)
    health = Mock(side_effect=OSError('not listening yet'))
    monkeypatch.setattr(start.urllib.request, 'urlopen', health)
    app.poll()
    opener.assert_not_called()
    response = Mock()
    response.__enter__ = Mock(return_value=Mock(status=200))
    response.__exit__ = Mock(return_value=False)
    health.side_effect = None
    health.return_value = response
    app.poll()
    opener.assert_called_once_with('http://127.0.0.1:43210')


def test_startup_timeout_stops_only_analyzer(monkeypatch, tmp_path):
    app = launcher_without_window(tmp_path, monkeypatch)
    api, overlay = Mock(), Mock()
    api.poll.return_value = overlay.poll.return_value = None
    app.processes.update(api=api, overlay=overlay)
    app.url = None
    app.started['api'] = start.time.monotonic() - 61
    app.poll()
    api.terminate.assert_called_once()
    overlay.terminate.assert_not_called()
    assert 'timed out' in app.status['api'].set.call_args.args[0]
