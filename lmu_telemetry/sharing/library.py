"""Persistent publishing/library state and a single lifecycle-owned sync worker."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .package import SharedLap, read_package, write_package
from .providers import GoogleDriveProvider, folder_url

SYNC_INTERVAL = 300


def state_dir() -> Path:
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / 'LMU Telemetry'


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SharingLibrary:
    def __init__(self, root: Path, provider=None):
        self.root = Path(root)
        self.provider = provider or GoogleDriveProvider()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.running = False
        self.pending = None
        self.active_friend = None
        self.progress = None
        path = self.root / 'state.json'
        self.data = json.loads(path.read_text('utf-8')) if path.exists() else {
            'settings': {'publish_dir': '', 'public_url': ''}, 'published': {}, 'friends': {}, 'laps': {},
        }

    def _save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.state-', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(self.data, handle, allow_nan=False)
            os.replace(temporary, self.root / 'state.json')
        finally:
            Path(temporary).unlink(missing_ok=True)

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.data)
            result.update(running=self.running, queued=self.pending is not None, active_friend=self.active_friend, progress=self.progress)
            result['published'] = list(result['published'].values())
            result['friends'] = list(result['friends'].values())
            result['laps'] = list(result['laps'].values())
            return result

    def settings(self, publish_dir, public_url):
        if public_url:
            public_url = folder_url(public_url)
        directory = Path(publish_dir).expanduser()
        if not publish_dir or not directory.is_absolute():
            raise ValueError('Choose an absolute local sharing folder path')
        directory.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if self.data['published'] and str(directory.resolve()) != self.data['settings']['publish_dir']:
                raise ValueError('Stop sharing your published laps before changing the sharing folder')
            self.data['settings'] = dict(publish_dir=str(directory.resolve()), public_url=public_url)
            self._save()

    def publish(self, shared: SharedLap, source: str):
        with self.lock:
            folder = self.data['settings']['publish_dir']
            if not folder:
                raise ValueError('Configure your local sharing folder on the Sharing page first')
            identity = shared.identity
            filename = f'{identity}.lmulap'
            path = Path(folder) / filename
            existing = self.data['published'].get(identity)
            if existing and path.exists():
                return copy.deepcopy(existing)
            if path.exists():
                raise ValueError('A file with this name already exists; it will not be overwritten')
            write_package(path, shared)
            item = dict(id=identity, filename=filename, source=source, lap=shared.trace.lap.number,
                        duration_s=shared.trace.lap.duration_s, driver=shared.info.driver,
                        track=shared.info.track, car=shared.info.car, published_at=now(),
                        hash=hashlib.sha256(path.read_bytes()).hexdigest())
            self.data['published'][identity] = item
            self._save()
            return copy.deepcopy(item)

    def unpublish(self, identity):
        with self.lock:
            item = self.data['published'].get(identity)
            if item is None:
                raise KeyError('Published lap not found')
            path = Path(self.data['settings']['publish_dir']) / item['filename']
            if path.is_symlink():
                raise ValueError('The published file was replaced with a symbolic link')
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != item['hash']:
                    raise ValueError('The published file was modified; it will not be deleted')
                path.unlink()
            del self.data['published'][identity]
            self._save()

    def add_friend(self, name, url):
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError('Enter a friend name of at most 100 characters')
        url = folder_url(url)
        with self.lock:
            if any(urlparse_id(f['url']) == urlparse_id(url) for f in self.data['friends'].values()):
                raise ValueError('This folder is already in your friends list')
            identity = uuid.uuid4().hex
            friend = dict(id=identity, name=name, url=url, last_success=None, last_attempt=None, error=None, history=[])
            self.data['friends'][identity] = friend
            self._save()
            return copy.deepcopy(friend)

    def remove_friend(self, identity):
        with self.lock:
            if identity not in self.data['friends']:
                raise KeyError('Friend not found')
            del self.data['friends'][identity]
            for lap in self.data['laps'].values():
                if lap['friend_id'] == identity:
                    lap['sharing_status'] = 'friend_removed'
            self._save()

    def get(self, identity):
        with self.lock:
            if identity not in self.data['laps']:
                raise KeyError('Shared lap not found')
            digest = self.data['laps'][identity]['hash']
        return read_package(self.root / 'packages' / f'{digest}.lmulap')

    def label(self, identity):
        with self.lock:
            entry = self.data['laps'][identity]
            return f"{entry['friend_name']} · {entry['info']['driver']}"

    def summaries(self):
        with self.lock:
            entries = copy.deepcopy(list(self.data['laps'].values()))
        return [dict(**entry['info'], name=entry['id'], shared=True, friend=entry['friend_name'],
                     sharing_status=entry['sharing_status'], laps=1, clean_laps=1,
                     best_lap=entry['lap'], best_lap_s=entry['duration_s'], track_length_m=entry['track_length_m']) for entry in entries]

    def request_sync(self, friend_id=None):
        with self.lock:
            if friend_id is not None and friend_id not in self.data['friends']:
                raise KeyError('Friend not found')
            if self.running or self.pending is not None:
                return False
            self.pending = [friend_id] if friend_id else list(self.data['friends'])
            self.wake.set()
            return True

    def start(self):
        with self.lock:
            if self.thread is not None:
                return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, name='lap-folder-sync', daemon=True)
            self.thread.start()
        self.request_sync()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=35)
            if self.thread.is_alive():
                raise RuntimeError('Lap sync worker did not stop within its network timeout')
            self.thread = None

    def _loop(self):
        while not self.stop_event.is_set():
            self.wake.wait(SYNC_INTERVAL)
            self.wake.clear()
            if self.stop_event.is_set():
                break
            with self.lock:
                targets = self.pending if self.pending is not None else list(self.data['friends'])
                self.pending = None
                self.running = True
            try:
                for identity in targets:
                    if self.stop_event.is_set():
                        break
                    try:
                        self.sync_friend(identity)
                    except Exception as exc:
                        # Disk/persistence errors must not kill the scheduler.
                        # The in-memory status can still explain the failure.
                        with self.lock:
                            if identity in self.data['friends']:
                                self.data['friends'][identity]['error'] = f'Sync failed: {exc}'
            finally:
                with self.lock:
                    self.running = False
                    self.active_friend = None
                    self.progress = None

    def _record_sync(self, friend, found, downloaded, error):
        history = friend.setdefault('history', [])
        history.append(dict(started_at=friend['last_attempt'], finished_at=now(),
                            files_found=found, files_downloaded=downloaded, error=error))
        del history[:-20]

    def sync_friend(self, identity):
        """One complete listing; failed files do not invalidate old local copies."""
        with self.lock:
            friend = copy.deepcopy(self.data['friends'].get(identity))
            if friend is None:
                return
            self.active_friend = identity
            self.data['friends'][identity]['last_attempt'] = now()
        errors = []
        downloaded = 0
        try:
            files = self.provider.list_files(friend['url'], self.stop_event)
            if self.stop_event.is_set():
                return
            seen = {file.id for file in files}
            for index, file in enumerate(files):
                if self.stop_event.is_set():
                    return
                with self.lock:
                    if identity not in self.data['friends']:
                        return
                    self.progress = f'{index + 1}/{len(files)}: {file.name}'
                try:
                    # Re-download immutable packages to detect external replacements;
                    # content hashes avoid duplicate storage and comparison cache churn.
                    self.root.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory(prefix='.sync-', dir=self.root) as staging:
                        path = Path(staging) / 'lap.lmulap'
                        self.provider.download(file, path, self.stop_event)
                        shared = read_package(path)
                        digest = hashlib.sha256(path.read_bytes()).hexdigest()
                        from dataclasses import asdict
                        key = 'shared-' + hashlib.sha256(f'{identity}:{file.id}'.encode()).hexdigest()
                        with self.lock:
                            if identity not in self.data['friends'] or self.stop_event.is_set():
                                return
                            destination = self.root / 'packages' / f'{digest}.lmulap'
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            if not destination.exists():
                                os.replace(path, destination)
                            self.data['laps'][key] = dict(id=key, friend_id=identity, friend_name=friend['name'], remote_id=file.id,
                                hash=digest, info=asdict(shared.info), lap=shared.trace.lap.number,
                                duration_s=shared.trace.lap.duration_s, track_length_m=shared.model.track_length_m,
                                sharing_status='shared', downloaded_at=now())
                            self._save()
                            downloaded += 1
                except Exception as exc:
                    errors.append(f'{file.name}: {exc}')
            with self.lock:
                if identity not in self.data['friends']:
                    return
                for lap in self.data['laps'].values():
                    if lap['friend_id'] == identity:
                        lap['sharing_status'] = 'shared' if lap['remote_id'] in seen else 'no_longer_shared'
                current = self.data['friends'][identity]
                current['error'] = '; '.join(errors) or None
                if not errors:
                    current['last_success'] = now()
                self._record_sync(current, len(files), downloaded, current['error'])
                self._save()
        except Exception as exc:
            with self.lock:
                if identity in self.data['friends']:
                    current = self.data['friends'][identity]
                    current['error'] = f'{exc}. Check public folder access and retry; existing laps are retained.'
                    self._record_sync(current, None, downloaded, current['error'])
                    self._save()


def urlparse_id(url):
    from urllib.parse import urlparse
    return urlparse(url).path.rsplit('/', 1)[-1]
