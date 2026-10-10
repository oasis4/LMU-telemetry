"""Portable comparison data. Archives are read in memory, never extracted."""
from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np

from ..core.geometry import _EARTH_RADIUS_M, grid_for, project_enu
from ..core.laps import Lap
from ..core.session import SessionInfo
from ..core.trace import LapTrace
from ..core.track_model import MODEL_FORMAT_VERSION, TrackModel

VERSION = 1
MAX_BYTES = 32 * 1024 * 1024
MAX_POINTS = 100_000
ARRAYS = ('grid', 'time_s', 'speed_kmh', 'throttle', 'brake', 'steering', 'x', 'y')
MEMBERS = {'metadata.json', *(f'{name}.npy' for name in ARRAYS)}


@dataclass(frozen=True)
class SharedLap:
    identity: str
    info: SessionInfo
    model: TrackModel
    trace: LapTrace


def _number(value, label, low=0, high=1e9):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not low <= value <= high:
        raise ValueError(f'invalid {label}')
    return value


def validate(shared: SharedLap) -> None:
    if not isinstance(shared.identity, str) or len(shared.identity) != 64 or any(c not in '0123456789abcdef' for c in shared.identity):
        raise ValueError('invalid lap identity')
    if any(not isinstance(v, str) or len(v) > 1024 for v in asdict(shared.info).values()):
        raise ValueError('invalid lap metadata')
    model, trace, lap = shared.model, shared.trace, shared.trace.lap
    length = _number(model.track_length_m, 'track length', 10, 200_000)
    if model.key.track != shared.info.track or model.key.layout != (shared.info.layout or shared.info.track):
        raise ValueError('circuit metadata does not match geometry')
    _number(lap.number, 'lap number', 1, 1_000_000)
    if not isinstance(lap.number, int) or lap.touched_pits is not False:
        raise ValueError('only usable recorded laps can be shared')
    _number(lap.duration_s, 'duration', 0.001, 86_400)
    _number(lap.t_start, 'start time')
    _number(lap.t_end, 'end time')
    if abs(lap.t_end - lap.t_start - lap.duration_s) > 0.001:
        raise ValueError('invalid lap boundaries')
    _number(lap.distance_m, 'lap distance', 1, 200_000)
    if lap.recorded_time_s is not None:
        _number(lap.recorded_time_s, 'recorded time', 0, 86_400)
    if lap.sectors_s is not None:
        if len(lap.sectors_s) != 3:
            raise ValueError('expected three sector times')
        for value in lap.sectors_s:
            _number(value, 'sector time', 0, 86_400)
    n = len(trace.grid)
    if not 2 <= n <= MAX_POINTS:
        raise ValueError('invalid sample count')
    for name in ARRAYS:
        arr = getattr(trace, name)
        if not isinstance(arr, np.ndarray) or arr.ndim != 1 or arr.dtype.kind not in 'fiu' or len(arr) != n or not np.isfinite(arr).all():
            raise ValueError(f'invalid {name} array')
        if np.any(np.abs(arr) > 1e9):
            raise ValueError(f'{name} values exceed bounds')
    if not np.array_equal(trace.grid, grid_for(length)):
        raise ValueError('invalid distance grid')
    if np.any(np.diff(trace.time_s) <= 0) or abs(trace.time_s[0]) > 1e-6 or not 0 < trace.time_s[-1] <= lap.duration_s * 1.05:
        raise ValueError('invalid lap clock')
    if model.origin is None or len(model.origin) != 2:
        raise ValueError('missing projection origin')
    _number(model.origin[0], 'latitude', -89, 89)
    _number(model.origin[1], 'longitude', -180, 180)
    for arr in (model.line_x, model.line_y):
        if arr is None or arr.ndim != 1 or len(arr) != n or not np.isfinite(arr).all() or np.any(np.abs(arr) > 1e7):
            raise ValueError('invalid track geometry')
    _number(model.closure_deg, 'closure', -1e6, 1e6)
    _number(model.lap_count, 'model lap count', 1, 1e6)
    if not isinstance(model.confident, bool) or (model.warning is not None and not isinstance(model.warning, str)):
        raise ValueError('invalid model metadata')
    if len(model.corners) > 1000:
        raise ValueError('too many corners')
    indices = set()
    for corner in model.corners:
        if not isinstance(corner.index, int) or corner.index in indices or not isinstance(corner.name, str) or len(corner.name) > 1024 or corner.direction not in ('L', 'R'):
            raise ValueError('invalid corner')
        indices.add(corner.index)
        for field in ('start_m', 'apex_m', 'end_m'):
            _number(getattr(corner, field), field, 0, length)
        _number(corner.radius_m, 'radius', 0, 1e9)
        _number(corner.heading_deg, 'heading', -1e6, 1e6)


def write_package(path: Path, shared: SharedLap) -> None:
    validate(shared)
    model = shared.model.to_dict()
    # Model cache JSON rounds coordinates; shared packages retain full precision.
    model.update(line_x=shared.model.line_x.tolist(), line_y=shared.model.line_y.tolist())
    meta = dict(version=VERSION, identity=shared.identity, info=asdict(shared.info), lap=asdict(shared.trace.lap), model=model)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.lap-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('metadata.json', json.dumps(meta, allow_nan=False))
                for name in ARRAYS:
                    buffer = io.BytesIO()
                    np.save(buffer, getattr(shared.trace, name), allow_pickle=False)
                    archive.writestr(f'{name}.npy', buffer.getvalue())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_package(path: Path) -> SharedLap:
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('lap package exceeds 32 MiB')
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) != len(MEMBERS) or {m.filename for m in members} != MEMBERS:
                raise ValueError('unexpected lap package members')
            if sum(m.file_size for m in members) > MAX_BYTES or archive.getinfo('metadata.json').file_size > 4 * 1024 * 1024:
                raise ValueError('expanded lap package exceeds size limit')
            meta = json.loads(archive.read('metadata.json'))
            if type(meta['version']) is not int or meta['version'] != VERSION or meta['model']['format_version'] != MODEL_FORMAT_VERSION:
                raise ValueError('unsupported lap package version')
            arrays = {}
            for name in ARRAYS:
                data = io.BytesIO(archive.read(f'{name}.npy'))
                # Check the declared shape BEFORE numpy allocates an array.
                major, minor = np.lib.format.read_magic(data)
                if (major, minor) == (1, 0):
                    shape, _, dtype = np.lib.format.read_array_header_1_0(data)
                elif (major, minor) == (2, 0):
                    shape, _, dtype = np.lib.format.read_array_header_2_0(data)
                else:
                    raise ValueError('unsupported array format')
                if len(shape) != 1 or not 2 <= shape[0] <= MAX_POINTS or dtype.kind not in 'fiu' or dtype.itemsize > 8:
                    raise ValueError(f'invalid {name} array header')
                data.seek(0)
                arrays[name] = np.load(data, allow_pickle=False)
            if meta['lap'].get('sectors_s') is not None:
                meta['lap']['sectors_s'] = tuple(meta['lap']['sectors_s'])
            shared = SharedLap(meta['identity'], SessionInfo(**meta['info']), TrackModel.from_dict(meta['model']), LapTrace(Lap(**meta['lap']), **arrays))
            validate(shared)
            return shared
    except (KeyError, TypeError, AttributeError, OSError, zipfile.BadZipFile, EOFError, OverflowError, RecursionError) as exc:
        raise ValueError(f'invalid lap package: {exc}') from exc


def align_trace(trace: LapTrace, source: TrackModel, reference: TrackModel) -> LapTrace:
    """Resample onto the reference grid and transform the original ENU frame."""
    if source.key != reference.key:
        raise ValueError('laps are on different circuits')
    if abs(source.track_length_m - reference.track_length_m) / reference.track_length_m > 0.02:
        raise ValueError('track lengths disagree by more than 2%')
    if source.origin is None or reference.origin is None:
        raise ValueError('Missing track projection origin')
    grid = grid_for(reference.track_length_m)
    # Normalize distance for the small measurement scatter between track models.
    distances = grid * (source.track_length_m / reference.track_length_m)
    arrays = {name: np.interp(distances, trace.grid, getattr(trace, name)) for name in ARRAYS if name not in ('grid', 'x', 'y')}
    x, y = trace.x, trace.y
    if x is not None and y is not None and source.origin != reference.origin:
        lat0, lon0 = source.origin
        lat = lat0 + np.degrees(y / _EARTH_RADIUS_M)
        lon = lon0 + np.degrees(x / (_EARTH_RADIUS_M * np.cos(np.radians(lat0))))
        x, y = project_enu(lat, lon, reference.origin)
    arrays['x'] = None if x is None else np.interp(distances, trace.grid, x)
    arrays['y'] = None if y is None else np.interp(distances, trace.grid, y)
    return replace(trace, grid=grid, **arrays)
