"""Provider boundary. gdown internals are isolated here and pinned to 6.4.2."""
from __future__ import annotations

import importlib
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlencode, urlparse

from .package import MAX_BYTES


@dataclass(frozen=True)
class RemoteFile:
    id: str
    name: str
    resource_key: str = ''


class Provider(Protocol):
    def list_files(self, url: str, cancel: threading.Event) -> list[RemoteFile]: ...
    def download(self, file: RemoteFile, destination: Path, cancel: threading.Event) -> None: ...


def folder_url(value: str) -> str:
    parsed = urlparse(value.strip())
    match = re.fullmatch(r'/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]+)/*', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'drive.google.com' or not match:
        raise ValueError('Use a public Google Drive folder URL: https://drive.google.com/drive/folders/…')
    key = parse_qs(parsed.query).get('resourcekey', [''])[0]
    if key and not re.fullmatch(r'[A-Za-z0-9_-]+', key):
        raise ValueError('Invalid Drive resource key')
    return f'https://drive.google.com/drive/folders/{match[1]}' + ('?' + urlencode({'resourcekey': key}) if key else '')


class GoogleDriveProvider:
    def list_files(self, url, cancel):
        from bs4 import BeautifulSoup
        # The public folder helper recurses. Its parser lets us list only direct
        # children and fail atomically instead of accepting a partial traversal.
        module = importlib.import_module('gdown.download_folder')
        import requests
        parsed = urlparse(folder_url(url))
        key = parse_qs(parsed.query).get('resourcekey', [''])[0]
        resources = {}

        class FolderSession(requests.Session):
            def get(self, request_url, **kwargs):
                if cancel.is_set():
                    raise RuntimeError('Sync cancelled')
                if key:
                    request_url += '&' + urlencode({'resourcekey': key})
                response = super().get(request_url, **kwargs)
                soup = BeautifulSoup(response.text, 'html.parser')
                title = soup.title.get_text() if soup.title else ''
                if urlparse(response.url).hostname != 'drive.google.com' or re.search(r'error|not found|sign in|access denied', title, re.I):
                    raise ValueError('Folder unavailable. Set its sharing to Anyone with the link, then retry.')
                # A folder listing is an embedded view, not a Google login or
                # quota page with a title that the upstream parser might accept.
                if not soup.select('#flip-contents .flip-entries'):
                    raise ValueError('Drive folder listing could not be verified. Check public access or retry later.')
                for anchor in soup.find_all('a', href=True):
                    link = urlparse(anchor['href'])
                    match = re.match(r'/file/d/([A-Za-z0-9_-]+)/', link.path)
                    if match:
                        resources[match[1]] = parse_qs(link.query).get('resourcekey', [''])[0]
                return response

        with FolderSession() as session:
            session.headers['User-Agent'] = 'Mozilla/5.0'
            _, children = module._parse_embedded_folder_view(sess=session, folder_id=parsed.path.rsplit('/', 1)[-1], verify=True, timeout=(10, 30))
        return [RemoteFile(id, name, resources.get(id, '')) for id, name, mime in children
                if mime == 'application/octet-stream' and name.endswith('.lmulap')]

    def download(self, file, destination, cancel):
        import gdown

        class LimitedOutput:
            def __init__(self, handle):
                self.handle = handle
                self.size = 0
            def write(self, data):
                if cancel.is_set():
                    raise RuntimeError('Sync cancelled')
                self.size += len(data)
                if self.size > MAX_BYTES:
                    raise ValueError('Lap download exceeds 32 MiB')
                return self.handle.write(data)
            def flush(self):
                return self.handle.flush()

        url = 'https://drive.google.com/uc?' + urlencode({'id': file.id, **({'resourcekey': file.resource_key} if file.resource_key else {})})
        with destination.open('wb') as output:
            gdown.download(url=url, output=LimitedOutput(output), quiet=True, use_cookies=False, timeout=(10, 30), cancel=cancel)
