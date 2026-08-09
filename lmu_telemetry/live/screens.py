"""Which physical screens exist, and which one the game is on.

Tk answers ``winfo_screenwidth`` with the *primary* monitor's width and
nothing else. On a two-monitor desk that is not a size, it is a guess, and a
panel placed by it lands on whichever screen Windows calls first - which is
routinely not the screen the game is on. A panel on the other monitor is a
panel that does not exist as far as driving is concerned.

So the screens are asked for directly, and the default is not "the primary"
but "wherever Le Mans Ultimate has its window". A driver who moves the game
to the other monitor should not also have to tell this.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from dataclasses import dataclass

#: MonitorFromWindow: give the nearest monitor rather than nothing when a
#: window straddles an edge or sits off-screen.
MONITOR_DEFAULTTONEAREST = 2
MONITORINFOF_PRIMARY = 1

#: The game's executable, lowercased, without the extension. Matched on the
#: *process* and not on the window title: this project's own folder is called
#: LMU-telemetry, so a title search for "lmu" finds the editor it is being
#: written in - which is on the primary screen and is not the game.
GAME_EXECUTABLES = ("le mans ultimate", "lemansultimate")

#: OpenProcess, enough rights to ask a process its name and no more.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class Monitor:
    """One screen, in the virtual desktop's coordinates.

    ``x`` and ``y`` are the top-left corner and are not zero for anything but
    the primary. That offset is the whole point of this module.
    """

    index: int
    x: int
    y: int
    width: int
    height: int
    primary: bool

    @property
    def label(self) -> str:
        where = "primary" if self.primary else f"at {self.x},{self.y}"
        return f"screen {self.index} ({self.width}x{self.height}, {where})"


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", _Rect),
                ("rcWork", _Rect), ("dwFlags", ctypes.c_uint32)]


def monitors() -> "list[Monitor]":
    """Every screen Windows knows about, in enumeration order.

    Returns a single notional screen where the platform cannot be asked, so
    callers do not each need a fallback. That screen is the primary's size,
    which is what Tk would have said anyway.
    """
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return [Monitor(0, 0, 0, 1920, 1080, True)]

    found: "list[Monitor]" = []
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(_Rect), ctypes.c_double,
    )

    def collect(handle, _dc, _rect, _data):
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if user32.GetMonitorInfoW(ctypes.c_void_p(handle), ctypes.byref(info)):
            box = info.rcMonitor
            found.append(Monitor(
                index=len(found),
                x=box.left, y=box.top,
                width=box.right - box.left,
                height=box.bottom - box.top,
                primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
            ))
        return 1

    user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
    if not found:
        return [Monitor(0, 0, 0,
                        user32.GetSystemMetrics(0), user32.GetSystemMetrics(1),
                        True)]
    return found


def monitor_holding(x: int, y: int, screens=None) -> "Monitor | None":
    """The screen containing the point, or None if it is on none of them.

    Half-open on the right and bottom, the way the rectangles themselves are:
    counted closed, a window on the seam between two screens would be held by
    both and the panel would flicker between them.
    """
    for screen in (monitors() if screens is None else screens):
        if (screen.x <= x < screen.x + screen.width
                and screen.y <= y < screen.y + screen.height):
            return screen
    return None


def is_game_image(path: str) -> bool:
    """Whether an executable path is the game's.

    On the file name only, and on the whole stem rather than a substring of
    it. Titles were tried first and were wrong within a minute: this project
    lives in a folder called LMU-telemetry, so the editor writing it announces
    itself as "... - LMU-telemetry - Visual Studio Code" and was picked as the
    game, putting the panel back on the primary screen - the exact fault this
    is meant to cure.
    """
    if not path:
        return False
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    stem = name[:-4] if name.endswith(".exe") else name
    return stem in GAME_EXECUTABLES


def _image_of(pid: int) -> str:
    """The full path of a running process, or "" if it will not say."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(
            ctypes.c_void_p(handle), 0, buffer, ctypes.byref(size)
        ):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def _game_window():
    """The game's top-level window handle, or None.

    A window is wanted rather than just the process, because the process says
    nothing about which screen it is showing on - and a game on the second
    monitor is the whole case this exists for.
    """
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return None

    hit = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

    def look(handle, _data):
        if not user32.IsWindowVisible(ctypes.c_void_p(handle)):
            return 1
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(handle), ctypes.byref(pid))
        if pid.value and is_game_image(_image_of(pid.value)):
            hit.append(handle)
            return 0
        return 1

    user32.EnumWindows(callback_type(look), 0)
    return hit[0] if hit else None


def game_screen() -> "Monitor | None":
    """The screen Le Mans Ultimate has its window on, or None if not found.

    Asked through MonitorFromWindow rather than by comparing rectangles: it
    already knows what to do with a window spanning two screens, and a
    fullscreen game on the second monitor is precisely that kind of edge.
    """
    handle = _game_window()
    if handle is None:
        return None
    user32 = ctypes.windll.user32
    wanted = user32.MonitorFromWindow(
        ctypes.c_void_p(handle), MONITOR_DEFAULTTONEAREST
    )
    if not wanted:
        return None

    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not user32.GetMonitorInfoW(ctypes.c_void_p(wanted), ctypes.byref(info)):
        return None
    box = info.rcMonitor
    # Matched back by position rather than by handle, so the Monitor returned
    # is the same object monitors() hands out and carries the same index.
    return monitor_holding(box.left, box.top)


def choose_screen(wanted: "int | None" = None) -> Monitor:
    """The screen to put the panel on.

    *wanted* is an index from the driver. Without one the game's own screen is
    used, and the primary only when the game cannot be found - which is the
    order of what the driver most likely meant.
    """
    screens = monitors()
    if wanted is not None:
        if not 0 <= wanted < len(screens):
            raise ValueError(
                f"there is no screen {wanted}; this machine has "
                f"{len(screens)} ({', '.join(s.label for s in screens)})"
            )
        return screens[wanted]
    return game_screen() or next(s for s in screens if s.primary)


# Windows' argument and return types, set once. Left to ctypes' defaults, a
# 64-bit window handle comes back truncated to a C int and names some other
# window entirely.
try:
    _u = ctypes.windll.user32
    _u.EnumDisplayMonitors.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double
    ]
    _u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
    _u.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _u.MonitorFromWindow.restype = ctypes.c_void_p
    _u.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _u.IsWindowVisible.argtypes = [ctypes.c_void_p]
    _u.GetWindowThreadProcessId.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)
    ]
    _k = ctypes.windll.kernel32
    _k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _k.OpenProcess.restype = ctypes.c_void_p
    _k.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _k.CloseHandle.argtypes = [ctypes.c_void_p]
except AttributeError:
    pass
