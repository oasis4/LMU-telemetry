"""Sharing round trips real traces; sync tests use a deterministic fake provider."""
import hashlib
import io
import json
import shutil
import threading
import time
import zipfile
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lmu_telemetry.api.app import create_app
from lmu_telemetry.core import Session, build_trace
from lmu_telemetry.core.geometry import _EARTH_RADIUS_M, project_enu
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.sharing.library import SharingLibrary
from lmu_telemetry.sharing.package import ARRAYS, SharedLap, align_trace, read_package, write_package
from lmu_telemetry.sharing.providers import GoogleDriveProvider, RemoteFile, folder_url

URL = 'https://drive.google.com/drive/folders/friend-folder'


@pytest.fixture(scope='module')
def shared(monza_q_file):
    with Session.open(monza_q_file) as session:
        model = build_track_model([session])
        lap = next(l for l in session.laps if l.number == 2)
        trace = build_trace(session, lap, model.track_length_m, origin=model.origin)
        return SharedLap('a' * 64, session.info, model, trace)


@pytest.fixture
def package(tmp_path, shared):
    path = tmp_path / 'lap.lmulap'
    write_package(path, shared)
    return path


class FakeProvider:
    def __init__(self, package):
        self.package = package
        self.files = [RemoteFile('lap-one', 'lap.lmulap')]
        self.fail_listing = False
        self.fail_files = set()
        self.calls = 0

    def list_files(self, url, cancel):
        self.calls += 1
        if self.fail_listing:
            raise ValueError('Private folder')
        return self.files

    def download(self, file, destination, cancel):
        if file.id in self.fail_files:
            raise ValueError('Download quota exceeded')
        shutil.copyfile(self.package, destination)


def library_with_friend(tmp_path, package):
    provider = FakeProvider(package)
    library = SharingLibrary(tmp_path / 'library', provider)
    friend = library.add_friend('Alex', URL)
    return library, provider, friend['id']


def test_package_roundtrip_full_precision(package, shared):
    restored = read_package(package)
    assert restored.info == shared.info
    assert restored.model.key == shared.model.key
    for field in ARRAYS:
        np.testing.assert_array_equal(getattr(restored.trace, field), getattr(shared.trace, field))
    np.testing.assert_array_equal(restored.model.line_x, shared.model.line_x)
    assert restored.trace.lap.duration_s == shared.trace.lap.duration_s


def rewrite_package(path, change):
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    change(members)
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in members.items():
            archive.writestr(name, data)


@pytest.mark.parametrize('defect', ['version', 'path', 'pickle', 'nan', 'length', 'origin', 'clock', 'geometry', 'header'])
def test_rejects_malformed_packages(package, defect):
    def change(members):
        meta = json.loads(members['metadata.json'])
        if defect == 'version': meta['version'] = 99
        if defect == 'path': members['../escape'] = b'danger'
        if defect == 'origin': meta['model']['origin'] = [float('nan'), 0]
        if defect == 'geometry': meta['model']['line_x'] = [0]
        if defect in ('pickle', 'nan', 'length', 'clock'):
            array = np.load(io.BytesIO(members['speed_kmh.npy']), allow_pickle=False)
            if defect == 'pickle': array = np.array([{'execute': True}], dtype=object)
            if defect == 'nan': array[0] = np.nan
            if defect == 'length': array = array[:2]
            if defect == 'clock':
                array = np.load(io.BytesIO(members['time_s.npy']), allow_pickle=False)
                array[20] = -1
            buffer = io.BytesIO(); np.save(buffer, array)
            members['time_s.npy' if defect == 'clock' else 'speed_kmh.npy'] = buffer.getvalue()
        if defect == 'header':
            buffer = io.BytesIO()
            np.lib.format.write_array_header_1_0(buffer, {'descr': '<f8', 'fortran_order': False, 'shape': (10**12,)})
            members['speed_kmh.npy'] = buffer.getvalue()
        members['metadata.json'] = json.dumps(meta).encode()
    rewrite_package(package, change)
    with pytest.raises(ValueError): read_package(package)


def test_bounds_archive_before_loading(package, monkeypatch):
    import lmu_telemetry.sharing.package as module
    monkeypatch.setattr(module, 'MAX_BYTES', 100)
    with pytest.raises(ValueError, match='exceeds'): read_package(package)


def test_publish_idempotent_and_unpublish_only_owned(tmp_path, shared):
    library = SharingLibrary(tmp_path / 'library')
    library.settings(str(tmp_path / 'published'), URL)
    first = library.publish(shared, 'source.duckdb')
    path = tmp_path / 'published' / first['filename']
    bytes_before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    assert library.publish(shared, 'source.duckdb') == first
    assert path.stat().st_mtime_ns == mtime
    other = path.parent / 'unrelated.txt'; other.write_text('keep')
    path.write_bytes(b'modified')
    with pytest.raises(ValueError, match='modified'): library.unpublish(first['id'])
    path.write_bytes(bytes_before)
    library.unpublish(first['id'])
    assert not path.exists() and other.exists()
    assert not library.snapshot()['published']


def test_sync_keeps_removed_laps_and_survives_restart(tmp_path, package):
    library, provider, friend = library_with_friend(tmp_path, package)
    library.sync_friend(friend)
    first = library.snapshot()['laps'][0]
    assert library.snapshot()['friends'][0]['last_success']
    assert library.snapshot()['friends'][0]['history'][0]['files_downloaded'] == 1
    library.sync_friend(friend)
    assert len(list((library.root / 'packages').glob('*.lmulap'))) == 1
    provider.files = []
    library.sync_friend(friend)
    assert library.snapshot()['laps'][0]['sharing_status'] == 'no_longer_shared'
    restarted = SharingLibrary(library.root)
    assert restarted.get(first['id']).info.driver
    restarted.remove_friend(friend)
    assert restarted.get(first['id']).trace.lap.number == 2
    assert restarted.snapshot()['laps'][0]['sharing_status'] == 'friend_removed'


def test_partial_failure_and_listing_failure_preserve_old_laps(tmp_path, package):
    library, provider, friend = library_with_friend(tmp_path, package)
    library.sync_friend(friend)
    first = library.snapshot()['laps'][0]
    provider.files += [RemoteFile('lap-two', 'bad.lmulap')]
    provider.fail_files.add('lap-two')
    library.sync_friend(friend)
    assert 'quota' in library.snapshot()['friends'][0]['error']
    assert library.get(first['id']).trace.lap.number == 2
    provider.files = []
    provider.fail_listing = True
    library.sync_friend(friend)
    assert library.snapshot()['laps'][0]['sharing_status'] == 'shared'
    assert library.snapshot()['friends'][0]['history'][-1]['files_found'] is None


def test_failed_replacement_keeps_previous_copy(tmp_path, package):
    library, provider, friend = library_with_friend(tmp_path, package)
    library.sync_friend(friend)
    old = library.snapshot()['laps'][0]
    package.write_bytes(b'not a package')
    library.sync_friend(friend)
    assert library.snapshot()['laps'][0]['hash'] == old['hash']
    assert library.get(old['id']).trace.lap.number == 2


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        if time.monotonic() > deadline: pytest.fail('sync worker timed out')
        time.sleep(0.01)


def test_worker_startup_manual_periodic_and_no_overlap(tmp_path, package, monkeypatch):
    import lmu_telemetry.sharing.library as module
    monkeypatch.setattr(module, 'SYNC_INTERVAL', 0.05)
    library, provider, friend = library_with_friend(tmp_path, package)
    entered, release = threading.Event(), threading.Event()
    original = provider.list_files
    def blocking(url, cancel):
        entered.set()
        assert release.wait(3)
        return original(url, cancel)
    provider.list_files = blocking
    library.start()
    try:
        assert entered.wait(3)
        assert not library.request_sync(friend)
        release.set()
        wait_until(lambda: provider.calls >= 2)  # startup + scheduled
        wait_until(lambda: not library.running)
        assert library.request_sync(friend)
        wait_until(lambda: provider.calls >= 3)
    finally:
        release.set(); library.close()
    assert library.thread is None


def test_origin_alignment_and_distance_grid(shared):
    target_origin = (shared.model.origin[0] + 0.001, shared.model.origin[1] - 0.001)
    reference = replace(shared.model, origin=target_origin, track_length_m=shared.model.track_length_m + 2)
    aligned = align_trace(shared.trace, shared.model, reference)
    lat0, lon0 = shared.model.origin
    lat = lat0 + np.degrees(shared.trace.y / _EARTH_RADIUS_M)
    lon = lon0 + np.degrees(shared.trace.x / (_EARTH_RADIUS_M * np.cos(np.radians(lat0))))
    expected_x, expected_y = project_enu(lat, lon, target_origin)
    distances = aligned.grid / reference.track_length_m * shared.model.track_length_m
    np.testing.assert_allclose(aligned.x, np.interp(distances, shared.trace.grid, expected_x))
    np.testing.assert_allclose(aligned.y, np.interp(distances, shared.trace.grid, expected_y))
    np.testing.assert_array_equal(align_trace(shared.trace, shared.model, shared.model).time_s, shared.trace.time_s)
    with pytest.raises(ValueError, match='different circuits'):
        align_trace(shared.trace, shared.model, replace(reference, key=replace(reference.key, layout='Other')))
    with pytest.raises(ValueError, match='2%'):
        align_trace(shared.trace, shared.model, replace(reference, track_length_m=1000))


def test_api_export_sync_offline_comparison_and_both_selectors(tmp_path, monza_q_file):
    recordings = tmp_path / 'recordings'; recordings.mkdir()
    shutil.copyfile(monza_q_file, recordings / 'local.duckdb')
    provider = FakeProvider(None)
    app = create_app(recordings, cache_dir=tmp_path / 'cache', sharing_dir=tmp_path / 'sharing', sharing_provider=provider)
    with TestClient(app) as client:
        assert client.put('/api/sharing/settings', json={'publish_dir': str(tmp_path / 'published')}).status_code == 200
        result = client.post('/api/sessions/local.duckdb/laps/2/share')
        assert result.status_code == 200, result.text
        assert client.post('/api/sessions/local.duckdb/laps/0/share').status_code == 422
        provider.package = tmp_path / 'published' / result.json()['filename']
        friend = client.post('/api/sharing/friends', json={'name': 'Alex', 'url': URL}).json()
        wait_until(lambda: bool(app.state.sharing.snapshot()['laps']))
        shared_id = app.state.sharing.snapshot()['laps'][0]['id']
        assert any(s['name'] == shared_id and s['friend'] == 'Alex' for s in client.get('/api/sessions').json()['sessions'])
        assert client.get(f'/api/sessions/{shared_id}/laps').json()['laps'][0]['clean']
        assert client.get(f'/api/sessions/{shared_id}/map').status_code == 200
        assert client.get(f'/api/sessions/{shared_id}/track').status_code == 200
        assert client.get(f'/api/sessions/{shared_id}/ideal').status_code == 422
        provider.fail_listing = True
        params = dict(reference='local.duckdb', reference_lap=2, other=shared_id, other_lap=2, full=True)
        compared = client.get('/api/compare', params=params)
        assert compared.status_code == 200, compared.text
        assert max(abs(v) for v in compared.json()['series']['delta_s']) == 0
        params.update(reference=shared_id, other='local.duckdb')
        assert client.get('/api/compare', params=params).status_code == 200
        assert client.post(f'/api/sessions/{shared_id}/laps/2/share').status_code == 422
        assert client.delete(f'/api/sharing/published/{result.json()["id"]}').status_code == 200
        assert client.get('/api/compare', params=params).status_code == 200
    assert app.state.sharing.thread is None
    reopened = create_app(recordings, cache_dir=tmp_path / 'cache', sharing_dir=tmp_path / 'sharing', sharing_provider=provider)
    with TestClient(reopened) as client:
        assert client.get('/api/compare', params=params).status_code == 200


def test_drive_url_validation():
    assert folder_url(URL + '?usp=sharing&resourcekey=abc') == URL + '?resourcekey=abc'
    for url in ('http://drive.google.com/drive/folders/a', 'https://evil.test/drive/folders/a', 'https://drive.google.com/file/d/a/view'):
        with pytest.raises(ValueError): folder_url(url)


def test_google_provider_filters_direct_children_and_resource_keys(monkeypatch, tmp_path):
    import requests
    file_id = 'a' * 25
    html = f'''<title>Shared laps</title><div id="flip-contents"><div class="flip-entries">
      <a href="https://drive.google.com/file/d/{file_id}/view?resourcekey=filekey">lap.lmulap</a>
      <a href="https://drive.google.com/file/d/{'b' * 25}/view">notes.txt</a>
      <a href="https://drive.google.com/drive/folders/nested">Nested</a></div></div>'''
    urls = []
    def get(self, url, **kwargs):
        urls.append(url)
        response = requests.Response(); response.status_code = 200
        response.url = url; response._content = html.encode()
        return response
    monkeypatch.setattr(requests.Session, 'get', get)
    files = GoogleDriveProvider().list_files(URL + '?resourcekey=folderkey', threading.Event())
    assert files == [RemoteFile(file_id, 'lap.lmulap', 'filekey')]
    assert len(urls) == 1 and 'resourcekey=folderkey' in urls[0]
    html = '<title>Sign in</title>'
    with pytest.raises(ValueError, match='unavailable'):
        GoogleDriveProvider().list_files(URL, threading.Event())


def test_google_download_limits_output_and_disables_cookies(monkeypatch, tmp_path):
    import gdown
    import lmu_telemetry.sharing.providers as module
    def download(**kwargs):
        assert not kwargs['use_cookies']
        assert 'resourcekey=key' in kwargs['url']
        kwargs['output'].write(b'x' * 101)
    monkeypatch.setattr(gdown, 'download', download)
    monkeypatch.setattr(module, 'MAX_BYTES', 100)
    with pytest.raises(ValueError, match='exceeds'):
        GoogleDriveProvider().download(RemoteFile('id', 'lap.lmulap', 'key'), tmp_path / 'test', threading.Event())


def test_shared_trace_endpoint_aligns_corner_map_frame(tmp_path, package, shared, monza_q_file):
    # Model origin changes while the measured line remains in world coordinates.
    shifted_origin = (shared.model.origin[0] + .001, shared.model.origin[1] + .001)
    shifted_model = replace(shared.model, origin=shifted_origin)
    shifted_trace = align_trace(shared.trace, shared.model, shifted_model)
    line_trace = replace(shared.trace, x=shared.model.line_x, y=shared.model.line_y)
    shifted_line = align_trace(line_trace, shared.model, shifted_model)
    shifted_model = replace(shifted_model, line_x=shifted_line.x, line_y=shifted_line.y)
    write_package(package, replace(shared, model=shifted_model, trace=shifted_trace))
    provider = FakeProvider(package)
    recordings = tmp_path / 'recordings'; recordings.mkdir()
    shutil.copyfile(monza_q_file, recordings / monza_q_file.name)
    shutil.copyfile(monza_q_file.parent / 'imola_r_fused_formation_lap.duckdb', recordings / 'imola_r_fused_formation_lap.duckdb')
    app = create_app(recordings, cache_dir=tmp_path / 'cache', sharing_dir=tmp_path / 'library', sharing_provider=provider)
    friend = app.state.sharing.add_friend('Alex', URL)
    app.state.sharing.sync_friend(friend['id'])
    identity = app.state.sharing.snapshot()['laps'][0]['id']
    client = TestClient(app)
    local = client.get(f'/api/sessions/{monza_q_file.name}/laps/2/trace', params={'full': True}).json()
    aligned = client.get(f'/api/sessions/{identity}/laps/2/trace', params={'full': True, 'reference': monza_q_file.name})
    assert aligned.status_code == 200, aligned.text
    np.testing.assert_allclose(aligned.json()['series']['x'], local['series']['x'], atol=.002)
    np.testing.assert_allclose(aligned.json()['series']['y'], local['series']['y'], atol=.002)
    assert client.get(f'/api/sessions/{identity}/laps/2/trace', params={'reference': 'imola_r_fused_formation_lap.duckdb'}).status_code == 422


def test_sharing_mutations_reject_foreign_browser_origin(tmp_path):
    app = create_app(tmp_path, cache_dir=tmp_path / 'cache', sharing_dir=tmp_path / 'sharing')
    client = TestClient(app)
    assert client.post('/api/sharing/sync', headers={'Origin': 'https://unrelated.example'}).status_code == 403
    assert client.post('/api/sharing/sync', headers={'Origin': 'http://localhost:5173'}).status_code == 200
    preflight = client.options('/api/sharing/settings', headers={
        'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'PUT', 'Access-Control-Request-Headers': 'content-type'})
    assert preflight.status_code == 200
    assert 'PUT' in preflight.headers['access-control-allow-methods']


def test_local_recording_with_shared_prefix_is_still_accessible(tmp_path, monza_q_file):
    shutil.copyfile(monza_q_file, tmp_path / 'shared-local.duckdb')
    client = TestClient(create_app(tmp_path, cache_dir=tmp_path / 'cache', sharing_dir=tmp_path / 'sharing'))
    assert client.get('/api/sessions/shared-local.duckdb/laps').status_code == 200


def test_rejects_expansion_bomb_and_duplicate_members(tmp_path, package, monkeypatch):
    import lmu_telemetry.sharing.package as module
    bomb = tmp_path / 'bomb.lmulap'
    with zipfile.ZipFile(bomb, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('metadata.json', '{}')
        for name in ARRAYS:
            archive.writestr(f'{name}.npy', b'0' * 1_000_000)
    assert bomb.stat().st_size < 20_000
    monkeypatch.setattr(module, 'MAX_BYTES', 20_000)
    with pytest.raises(ValueError, match='expanded'): read_package(bomb)
    monkeypatch.setattr(module, 'MAX_BYTES', 32 * 1024 * 1024)
    with zipfile.ZipFile(package, 'a') as archive:
        with pytest.warns(UserWarning, match='Duplicate name'):
            archive.writestr('metadata.json', '{}')
    with pytest.raises(ValueError, match='members'): read_package(package)
