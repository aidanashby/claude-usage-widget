"""Always-on-top Claude usage widget: session + weekly limit bars."""
__version__ = "1.0.1"

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import shutil
import subprocess
import sys
import random
import re
import struct
import threading
import time
import traceback
import webbrowser
import tkinter as tk
from collections import namedtuple
from datetime import datetime
import urllib.request
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
PORTABLE_MARKER = "portable.txt"
APP_FOLDER = "ClaudeUsageWidget"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
RELEASES_API = (
    "https://api.github.com/repos/aidanashby/claude-usage-widget/releases/latest"
)
RELEASES_PAGE = "https://github.com/aidanashby/claude-usage-widget/releases/latest"


def app_dir():
    """Where the program itself lives -- the exe's folder once packaged."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return HERE


def data_dir():
    """Where settings and the log belong.

    Beside the program if a portable.txt marker is there -- for USB sticks and
    synced folders -- otherwise the user's roaming profile, because an
    installed copy may sit somewhere it isn't allowed to write.
    """
    here = app_dir()
    if os.path.exists(os.path.join(here, PORTABLE_MARKER)):
        return here
    roaming = os.environ.get("APPDATA")
    if not roaming:
        return here  # no profile to speak of; better than nowhere to write
    folder = os.path.join(roaming, APP_FOLDER)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return here
    return folder


DATA_DIR = data_dir()
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
LOG_PATH = os.path.join(DATA_DIR, "widget.log")

ORANGE = "#d17552"
GREY = "#7a7a7a"
TRACK = "#3a3a3a"
BAR_LENGTH = 120
MIN_BAR_LENGTH = 20
POLL_SECONDS = 300
MARKER_REFRESH_MS = 30000
TOOLTIP_DELAY_MS = 450
SESSION_WINDOW_SECONDS = 5 * 3600
WEEKLY_WINDOW_SECONDS = 7 * 24 * 3600
MARKER_ON_TRACK = "#ffffff"
MARKER_ON_FILL = "#000000"
MAX_BACKOFF_SECONDS = 30 * 60
ALERT_THRESHOLDS = (80, 95)
UPDATE_CHECK_SECONDS = 24 * 3600

# Bar, track and panel colours. draw() reads these rather than constants so a
# preset can change the look without touching the drawing code.
THEMES = {
    "claude": {"bar": "#d17552", "track": "#3a3a3a", "panel": "#000000"},
    "monochrome": {"bar": "#d0d0d0", "track": "#333333", "panel": "#000000"},
    "contrast": {"bar": "#ffff00", "track": "#4d4d4d", "panel": "#000000"},
}
STARTUP_DELAY_SECONDS = 8
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "ClaudeUsageWidget"
WINDOW_TITLE = "Claude Usage Widget"
IPC_CLASS = "ClaudeUsageWidgetIPC"

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_TRAY = 0x8000  # WM_APP, our tray callback
WM_RESET_POSITION = 0x8001  # WM_APP+1, sent by --reset
MENU_SETTINGS, MENU_RESET, MENU_QUIT, MENU_WELCOME = 1, 2, 3, 4
MENU_UPDATE = 5

DEFAULTS = {
    "thickness": 3,
    "spacing": 5,
    "padding": 6,
    "alpha": 0.7,
    "edge_gap": 12,
    "start_on_login": False,
    "vertical": False,
    "launch_cmd": "",
    "last_session": 0.0,
    "last_weekly": 0.0,
    "pos": None,
    "edge": "right",
    "last_session_reset": None,
    "last_weekly_reset": None,
    "bar_length": BAR_LENGTH,
    "theme": "claude",
    "click_through": False,
    "alerts": True,
    "alerted_session": None,
    "alerted_weekly": None,
    "seen_welcome": False,
    "update_check": True,
    "last_update_check": 0,
    "available_version": "",
}


def single_instance():
    """False if another copy is already running. Named mutex, released on exit."""
    kernel32 = ctypes.windll.kernel32
    global _MUTEX
    _MUTEX = kernel32.CreateMutexW(None, False, "ClaudeUsageWidget")
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def log(*parts):
    """Append a line to widget.log. Never raises.

    Under pythonw.exe with no console, sys.stderr is None, so printing to it
    from an exception handler raises AttributeError and turns a handled error
    into a fatal one. A log file is also the only way to see what happened
    when the app is started by Windows at login.
    """
    try:
        line = "%s  %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"),
            " ".join(str(p) for p in parts),
        )
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def log_exception(kind, exc):
    log("%s: %s" % (kind, exc))
    try:
        log(traceback.format_exc().rstrip())
    except Exception:
        pass


def parse_reset(value):
    """ISO-8601 reset timestamp from the API to epoch seconds, or None."""
    if not value:
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):  # fromisoformat only learned 'Z' in 3.11
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except (ValueError, AttributeError, TypeError):
        return None


def window_progress(reset_epoch, window_seconds, now=None):
    """How far through a fixed-length window we are, 0.0-1.0, or None.

    Both limits run for a fixed span ending at resets_at, so the elapsed
    fraction follows from the reset time alone -- and because resets_at comes
    from the API it reflects this user's actual window, not an assumed one.
    """
    if not reset_epoch or window_seconds <= 0:
        return None
    now = time.time() if now is None else now
    remaining = reset_epoch - now
    # Clamped so a stale cached reset can never push the marker off the bar.
    return max(0.0, min(1.0, 1.0 - remaining / float(window_seconds)))


def format_countdown(seconds):
    """The tail of 'resets ...': 'in 31 min', 'in 2h 5min', 'any moment now'."""
    if seconds is None:
        return "at an unknown time"
    seconds = int(seconds)
    if seconds <= 0:
        return "any moment now"
    if seconds < 60:
        return "in less than a minute"
    minutes = seconds // 60
    if minutes < 60:
        return "in %d min" % minutes
    hours, mins = divmod(minutes, 60)
    return "in %dh" % hours if mins == 0 else "in %dh %dmin" % (hours, mins)


def format_clock(epoch):
    """Just the time: '8:45am', or '4am' when it lands exactly on the hour."""
    lt = time.localtime(epoch)
    hour = lt.tm_hour % 12 or 12  # 0 -> 12am, 12 -> 12pm
    meridiem = "am" if lt.tm_hour < 12 else "pm"
    if lt.tm_min == 0:
        return "%d%s" % (hour, meridiem)
    return "%d:%02d%s" % (hour, lt.tm_min, meridiem)


def format_reset_time(epoch, now=None):
    """Local wall-clock reset, e.g. 'Sun 8:45am' -- or just '8:45am' if today.

    Naming the day is useful a week out and noise half an hour out.
    """
    if not epoch:
        return "at an unknown time"
    lt = time.localtime(epoch)
    today = time.localtime(time.time() if now is None else now)
    if (lt.tm_year, lt.tm_yday) == (today.tm_year, today.tm_yday):
        return format_clock(epoch)
    return "%s %s" % (time.strftime("%a", lt), format_clock(epoch))


def backoff_delay(failures, retry_after=None, base=None, jitter=0.0):
    """How long to wait before the next poll attempt.

    Doubles per consecutive failure up to a ceiling, and honours a server's
    Retry-After when it gives one. The jitter fraction keeps many installations
    from synchronising into a burst -- passed in rather than drawn here so the
    result stays testable.
    """
    base = POLL_SECONDS if base is None else base
    if failures <= 0:
        delay = base
    else:
        delay = min(MAX_BACKOFF_SECONDS, base * (2 ** min(failures, 16)))
    if retry_after:
        delay = max(delay, min(MAX_BACKOFF_SECONDS, retry_after))
    return max(1.0, delay * (1.0 + jitter))


def parse_retry_after(value):
    """Seconds from a Retry-After header. Only the numeric form; None if absent."""
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def due_alerts(pct, reset_epoch, already, thresholds=ALERT_THRESHOLDS):
    """Which thresholds this reading has newly crossed.

    `already` is the bookkeeping from settings: [reset_epoch, [fired...]]. A
    different reset means a new window, so everything is eligible again.
    """
    window, fired = (already or [None, []])[:2]
    if window != reset_epoch:
        fired = []
    due = [t for t in thresholds if pct >= t and t not in fired]
    return due, [reset_epoch, sorted(set(fired) | set(due))]


def project_exhaustion(pct, progress, window_seconds, now=None):
    """When usage would reach 100% at the current rate, or None.

    None means either not enough of the window has elapsed to judge, or the
    projection lands after the window resets anyway -- both mean "on pace".
    """
    if not progress or progress <= 0.02 or pct <= 0:
        return None  # too early in the window for the rate to mean anything
    if pct >= 100:
        return now if now is not None else time.time()
    now = time.time() if now is None else now
    elapsed = window_seconds * progress
    remaining_window = window_seconds - elapsed
    seconds_to_full = (100.0 - pct) * (elapsed / pct)
    if seconds_to_full >= remaining_window:
        return None  # won't run out before it resets
    return now + seconds_to_full


def parse_version(text):
    """'v1.2.3' -> (1, 2, 3). Unparseable pieces become 0."""
    parts = re.findall(r"\d+", str(text or ""))[:3]
    numbers = [int(p) for p in parts]
    return tuple(numbers + [0] * (3 - len(numbers))) if numbers else (0, 0, 0)


def is_newer(candidate, current):
    """Compare as numbers, not as text: 0.10.0 is newer than 0.9.0."""
    return parse_version(candidate) > parse_version(current)


def fetch_latest_version():
    """Latest released tag from GitHub, or None. Sends nothing about the user."""
    req = urllib.request.Request(
        RELEASES_API,
        headers={
            # GitHub rejects requests without one.
            "User-Agent": "claude-usage-widget/%s" % __version__,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r).get("tag_name")
    except Exception:
        return None  # offline, rate limited, no releases yet -- all fine


def widget_size(padding, thickness, spacing, vertical, length=BAR_LENGTH):
    """Outer size of the widget. Vertical is the horizontal case transposed."""
    long_side = length + padding * 2
    short_side = thickness * 2 + spacing + padding * 2
    return (short_side, long_side) if vertical else (long_side, short_side)


def bar_rect(along0, along1, index, padding, thickness, spacing, vertical,
             length=BAR_LENGTH):
    """Canvas rectangle for part of a bar, in along/across terms.

    'along' is distance from the bar's start on its long axis, 'across' is its
    thickness. Keeping every rectangle in those terms means orientation is
    handled exactly once, here, instead of throughout the drawing code.
    """
    across0 = padding + index * (thickness + spacing)
    across1 = across0 + thickness
    if vertical:
        # Bottom-up, so along counts from the foot of the bar.
        foot = padding + length
        return (across0, foot - along1, across1, foot - along0)
    return (padding + along0, across0, padding + along1, across1)


def max_bar_length(rect, padding, vertical):
    """Longest bar that fits the monitor's work area on the relevant axis."""
    left, top, right, bottom = rect
    span = (bottom - top) if vertical else (right - left)
    return max(MIN_BAR_LENGTH, span - padding * 2)


def migrate_settings():
    """Carry a pre-1.0 settings file over from beside the script, once.

    One-way and non-destructive: the original is left where it is, so an older
    copy of the widget keeps working if someone still runs one.
    """
    legacy = os.path.join(HERE, "settings.json")
    if os.path.exists(SETTINGS_PATH) or not os.path.exists(legacy):
        return
    if os.path.abspath(legacy) == os.path.abspath(SETTINGS_PATH):
        return
    try:
        shutil.copyfile(legacy, SETTINGS_PATH)
        log("migrated settings from", legacy)
    except OSError as e:
        log("could not migrate settings:", e)


def load_settings():
    migrate_settings()
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass  # ponytail: any unreadable/corrupt settings file just means defaults
    return s


def save_settings(s):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError as e:
        log("could not save settings:", e)


def detect_launch_cmd():
    """Work out how to start Claude on this machine. Cached in settings."""
    # Start Menu entry. Covers the Store/MSIX build (whose exe lives under the
    # ACL-locked WindowsApps and can only be started by AppUserModelID) as well
    # as ordinary installers, without knowing any version-stamped path.
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-StartApps | Where-Object {$_.Name -match 'Claude'} |"
             " Select-Object -ExpandProperty AppID"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.split()
        # Prefer the desktop app over 'Claude Code'-style entries if both exist.
        for aumid in sorted(out, key=len):
            if "claude" in aumid.lower():
                return "explorer.exe shell:AppsFolder\\" + aumid
    except (OSError, subprocess.SubprocessError):
        pass

    local = os.environ.get("LOCALAPPDATA", "")
    for path in (
        os.path.join(local, "AnthropicClaude", "claude.exe"),
        os.path.join(local, "Programs", "Claude", "Claude.exe"),
        os.path.join(local, "Claude", "Claude.exe"),
    ):
        if os.path.exists(path):
            return '"%s"' % path

    if shutil.which("claude"):
        return "cmd /k claude"
    return ""


def credential_files():
    """Every place Claude Code might keep .credentials.json, best guess first."""
    seen, out = set(), []
    roots = [os.environ.get("CLAUDE_CONFIG_DIR")]
    for home in (os.path.expanduser("~"), os.environ.get("USERPROFILE")):
        if home:
            roots.append(os.path.join(home, ".claude"))
    for root in roots:
        if not root:
            continue
        path = os.path.join(root, ".credentials.json")
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _token_from_blob(text):
    """Pull an unexpired access token out of a credentials JSON document."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    oauth = data.get("claudeAiOauth") or data
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    expires = oauth.get("expiresAt")
    if not token:
        return None
    # Expired is as good as absent: go grey so a click can relaunch Claude,
    # rather than spending a round trip to be told 401.
    if isinstance(expires, (int, float)) and time.time() * 1000 > expires:
        return None
    return token


def _credentials_from_manager():
    """Read the token from Windows Credential Manager, if it lives there.

    Some setups store credentials there rather than on disk. Enumerate and look
    for a Claude entry rather than guessing at the exact target name.
    """
    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
            ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi = ctypes.windll.advapi32
    count = wintypes.DWORD()
    creds = ctypes.POINTER(ctypes.POINTER(CREDENTIAL))()
    if not advapi.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(creds)):
        return None
    try:
        for i in range(count.value):
            cred = creds[i].contents
            if "claude" not in (cred.TargetName or "").lower():
                continue
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            for encoding in ("utf-8", "utf-16-le"):
                try:
                    token = _token_from_blob(raw.decode(encoding))
                except UnicodeDecodeError:
                    continue
                if token:
                    return token
    finally:
        advapi.CredFree(creds)
    return None


def find_token():
    """Locate Claude's OAuth access token, wherever this machine keeps it."""
    for path in credential_files():
        try:
            with open(path, encoding="utf-8") as f:
                token = _token_from_blob(f.read())
        except OSError:
            continue
        if token:
            return token
    try:
        return _credentials_from_manager()
    except Exception:
        return None  # ponytail: no Credential Manager access -> just go grey


Usage = namedtuple("Usage", "session weekly session_reset weekly_reset")
Failure = namedtuple("Failure", "reason retry_after")


def fetch_usage():
    """Return a Usage, or a Failure saying why it couldn't be read.

    The reason is what the tray tooltip shows: being rate limited is a very
    different situation from having no credentials, and telling the user to
    start Claude in the first case is just wrong. retry_after carries the
    server's own request when it makes one.

    Uses the OAuth token Claude already stores. Deliberately does not refresh
    it -- racing Claude's own refresh can invalidate its session. Launching
    Claude is the refresh path.
    """
    token = find_token()
    if not token:
        return Failure("no Claude credentials found", None)
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": "Bearer " + token,
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        return Usage(
            float(data["five_hour"]["utilization"]),
            float(data["seven_day"]["utilization"]),
            parse_reset(data["five_hour"].get("resets_at")),
            parse_reset(data["seven_day"].get("resets_at")),
        )
    except urllib.error.HTTPError as e:
        retry_after = parse_retry_after(e.headers.get("Retry-After"))
        if e.code == 429:
            return Failure("rate limited by the API — will retry", retry_after)
        if e.code in (401, 403):
            return Failure("Claude credentials rejected — sign in again", None)
        return Failure("usage request failed (HTTP %s)" % e.code, retry_after)
    except Exception:
        # ponytail: offline, DNS, schema drift -- all just mean "go grey"
        return Failure("usage unavailable", None)


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _Rect),
                ("rcWork", _Rect), ("dwFlags", ctypes.c_ulong)]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def monitor_work_area(cx, cy, fallback):
    """Work area (left, top, right, bottom) of the monitor under a point.

    Work area rather than full bounds, so snapping respects the taskbar.
    """
    try:
        user32 = ctypes.windll.user32
        handle = user32.MonitorFromPoint(_Point(int(cx), int(cy)), 2)  # NEAREST
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.rcWork
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass  # ponytail: no ctypes/monitor info -> primary screen dimensions
    return fallback


def point_on_monitor(x, y):
    """True if this point falls on a monitor that currently exists.

    MONITOR_DEFAULTTONULL, unlike the DEFAULTTONEAREST used for snapping,
    reports 'nowhere' -- which is what makes off-screen detectable at all.
    """
    try:
        return bool(ctypes.windll.user32.MonitorFromPoint(_Point(int(x), int(y)), 0))
    except Exception:
        return True  # ponytail: can't tell -> assume fine, never hide the widget


def primary_work_area(fallback):
    """Work area of the primary monitor, which is always the one at the origin."""
    return monitor_work_area(0, 0, fallback)


def top_right_of(rect, w, h, gap):
    """Top-right corner position within a monitor's work area."""
    left, top, right, _ = rect
    return (right - w - gap, top + gap)


def nearest_edge(x, y, w, h, rect):
    """Which edge of the containing monitor the widget's centre is closest to."""
    left, top, right, bottom = rect
    cx, cy = x + w / 2, y + h / 2
    dists = {
        "left": cx - left,
        "right": right - cx,
        "top": cy - top,
        "bottom": bottom - cy,
    }
    return min(dists, key=dists.get)


def edge_position(edge, x, y, w, h, rect, gap):
    """Where the widget sits when snapped to `edge` at `gap` from it."""
    left, top, right, bottom = rect
    x = min(max(x, left), right - w)
    y = min(max(y, top), bottom - h)
    return {
        "left": (left + gap, y),
        "right": (right - w - gap, y),
        "top": (x, top + gap),
        "bottom": (x, bottom - h - gap),
    }[edge]


def ease_out(t):
    return 1 - (1 - t) ** 3


def set_start_on_login(enabled):
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            # --startup makes it wait for the shell before showing up.
            if getattr(sys, "frozen", False):
                cmd = '"%s" --startup' % os.path.abspath(sys.executable)
            else:
                pythonw = os.path.join(
                    os.path.dirname(sys.executable), "pythonw.exe"
                )
                if not os.path.exists(pythonw):
                    pythonw = sys.executable
                cmd = '"%s" "%s" --startup' % (pythonw, os.path.abspath(__file__))
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass


LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM)


def _declare_win32():
    """Give every call an explicit signature.

    Without this, handle-returning calls overflow on 64-bit Python and raise
    from inside the window procedure, where the traceback is easy to miss.
    """
    u, g, k = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
    k.GetModuleHandleW.restype = wintypes.HMODULE
    u.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM]
    u.DefWindowProcW.restype = LRESULT
    u.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HMODULE, ctypes.c_void_p,
    ]
    u.CreateWindowExW.restype = wintypes.HWND
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowW.restype = wintypes.HWND
    u.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM]
    u.LoadIconW.restype = wintypes.HICON
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.TrackPopupMenu.argtypes = [
        wintypes.HMENU, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, wintypes.HWND, ctypes.c_void_p,
    ]
    # GDI/shell calls too. Handle values routinely exceed 32 bits, so an
    # undeclared call raises OverflowError -- which previously discarded a
    # perfectly good icon and fell back to the stock one.
    g.CreateBitmap.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
    ]
    g.CreateBitmap.restype = wintypes.HBITMAP
    g.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    g.CreateDIBSection.restype = wintypes.HBITMAP
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g.DeleteObject.restype = wintypes.BOOL
    u.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
    u.CreateIconIndirect.restype = wintypes.HICON
    u.GetSystemMetrics.argtypes = [ctypes.c_int]
    u.GetSystemMetrics.restype = ctypes.c_int
    u.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    u.RegisterWindowMessageW.restype = ctypes.c_uint
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.AppendMenuW.argtypes = [
        wintypes.HMENU, ctypes.c_uint, ctypes.c_size_t, wintypes.LPCWSTR,
    ]
    u.DestroyMenu.argtypes = [wintypes.HMENU]
    u.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
    ctypes.windll.shell32.Shell_NotifyIconW.argtypes = [
        wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATA),
    ]
    ctypes.windll.shell32.Shell_NotifyIconW.restype = wintypes.BOOL


def _bar_icon_bits(size=16):
    """Square BGRA buffer: two orange bars on transparent, echoing the widget."""
    r, g, b = int(ORANGE[1:3], 16), int(ORANGE[3:5], 16), int(ORANGE[5:7], 16)
    # Proportional to the icon so it reads the same at any DPI.
    thick = max(1, size // 6)
    gap = max(1, size // 8)
    inset = max(1, size // 8)
    top = (size - (thick * 2 + gap)) // 2
    bar_rows = set(range(top, top + thick)) | set(
        range(top + thick + gap, top + thick * 2 + gap)
    )
    out = bytearray()
    for y in range(size):
        for x in range(size):
            if y in bar_rows and inset <= x < size - inset:
                out += bytes((b, g, r, 255))
            else:
                out += b"\0\0\0\0"
    return bytes(out)


def ico_bytes(sizes=(16, 32, 48)):
    """A multi-size .ico built from the same pixels as the tray icon.

    Two quirks of the format: each image is a BMP whose header height is twice
    the real height (colour rows plus an AND mask), and its rows run bottom-up
    while our buffer is top-down.
    """
    images = []
    for size in sizes:
        top_down = _bar_icon_bits(size)
        stride = size * 4
        rows = [top_down[i * stride:(i + 1) * stride] for i in range(size)]
        pixels = b"".join(reversed(rows))
        mask_stride = ((size + 31) // 32) * 4  # 1bpp, padded to 4-byte rows
        mask = b"\0" * (mask_stride * size)
        header = struct.pack(
            "<IiiHHIIiiII",
            40, size, size * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0,
        )
        images.append(header + pixels + mask)

    offset = 6 + 16 * len(images)
    out = [struct.pack("<HHH", 0, 1, len(images))]  # reserved, type 1 = icon
    for size, image in zip(sizes, images):
        out.append(struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0, size if size < 256 else 0,
            0, 0, 1, 32, len(image), offset,
        ))
        offset += len(image)
    return b"".join(out + images)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


def _make_icon():
    """Build the tray icon, or fall back to the stock application icon.

    Uses a DIB section rather than CreateBitmap: a 32bpp device-dependent
    bitmap with alpha is unreliable, and when it failed the icon silently
    became the generic Python one.
    """
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    try:
        size = u.GetSystemMetrics(49) or 16  # SM_CXSMICON
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = size
        header.biHeight = -size  # negative: top-down, matching our buffer
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB

        g.CreateDIBSection.restype = wintypes.HBITMAP
        pixels = ctypes.c_void_p()
        colour = g.CreateDIBSection(
            None, ctypes.byref(header), 0, ctypes.byref(pixels), None, 0
        )
        if not colour or not pixels:
            raise OSError("CreateDIBSection failed")
        bits = _bar_icon_bits(size)
        ctypes.memmove(pixels, bits, len(bits))

        mask = g.CreateBitmap(size, size, 1, 1, None)  # 1bpp, contents unused
        info = ICONINFO(True, 0, 0, mask, colour)
        u.CreateIconIndirect.restype = wintypes.HICON
        icon = u.CreateIconIndirect(ctypes.byref(info))
        g.DeleteObject(colour)
        g.DeleteObject(mask)
        if icon:
            return icon
        raise OSError("CreateIconIndirect failed")
    except Exception as e:
        log("falling back to the stock tray icon:", e)
    return u.LoadIconW(None, ctypes.c_wchar_p(32512))  # IDI_APPLICATION


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
        ("uID", ctypes.c_uint), ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint), ("hIcon", wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128), ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD), ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", wintypes.DWORD), ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


class TrayIcon:
    """System tray presence: the way back to a widget you can't see or click."""

    def __init__(self, widget):
        self.widget = widget
        self.ok = False
        self.pending = []
        self.taskbar_created = 0
        self.hwnd = None
        try:
            self._build()
            self.ok = True
        except Exception as e:
            log_exception("tray icon unavailable", e)
            return
        self._pump()

    def _build(self):
        _declare_win32()
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        hinst = k.GetModuleHandleW(None)

        # Broadcast the shell sends when the taskbar appears: at login it can
        # arrive after we do, and it arrives again whenever Explorer restarts.
        # Registered before the window exists so no broadcast is missed.
        self.taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")

        # Held on the instance: Windows keeps the raw pointer, so letting the
        # callback object be collected would crash the process later.
        self.proc = WNDPROC(self._wndproc)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
            ]

        cls = WNDCLASS()
        cls.lpfnWndProc = self.proc
        cls.hInstance = hinst
        cls.lpszClassName = IPC_CLASS
        u.RegisterClassW(ctypes.byref(cls))  # already-registered is fine
        self.hwnd = u.CreateWindowExW(
            0, IPC_CLASS, WINDOW_TITLE, 0, 0, 0, 0, 0, None, None, hinst, None
        )
        if not self.hwnd:
            raise OSError("could not create the tray's message window")

        self.icon = _make_icon()
        self.data = NOTIFYICONDATA()
        self.data.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        self.data.hWnd = self.hwnd
        self.data.uID = 1
        self.data.uFlags = 0x1 | 0x2 | 0x4  # MESSAGE | ICON | TIP
        self.data.uCallbackMessage = WM_TRAY
        self.data.hIcon = self.icon
        self.data.szTip = WINDOW_TITLE
        self._add_icon()

    def _add_icon(self):
        """Register with the tray. Safe to call again after the shell restarts."""
        shell = ctypes.windll.shell32
        shell.Shell_NotifyIconW(2, ctypes.byref(self.data))  # NIM_DELETE, if stale
        if not shell.Shell_NotifyIconW(0, ctypes.byref(self.data)):  # NIM_ADD
            # Usually means the shell isn't up yet; TaskbarCreated will tell us
            # when it is. Not fatal -- the widget itself works regardless.
            log("tray icon not accepted yet; waiting for the shell")

    def set_tooltip(self, text):
        if not self.ok:
            return
        self.data.szTip = text[:127]
        ctypes.windll.shell32.Shell_NotifyIconW(1, ctypes.byref(self.data))  # NIM_MODIFY

    def notify(self, title, message):
        """Balloon from the tray icon. Windows renders these as toasts."""
        if not self.ok:
            return
        try:
            self.data.uFlags |= 0x10  # NIF_INFO
            self.data.szInfoTitle = title[:63]
            self.data.szInfo = message[:255]
            self.data.dwInfoFlags = 0x1  # NIIF_INFO
            ctypes.windll.shell32.Shell_NotifyIconW(1, ctypes.byref(self.data))
        except Exception as e:
            log_exception("tray notification", e)
        finally:
            # Clear, or every later NIM_MODIFY re-shows the same balloon.
            self.data.uFlags &= ~0x10
            self.data.szInfo = ""

    def remove(self):
        if not self.ok:
            return
        self.ok = False
        ctypes.windll.shell32.Shell_NotifyIconW(2, ctypes.byref(self.data))  # NIM_DELETE

    def _wndproc(self, hwnd, msg, wparam, lparam):
        """Record what happened and return. Never touch Tk from in here.

        This runs inside DispatchMessageW, inside the pump, inside a Tk 'after'
        callback. Calling back into Tk at that depth -- opening a Toplevel, say
        -- crashes the process, because Tk is not re-entrant. Everything real
        happens in _pump once this has returned.
        """
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event == 0x0205:  # WM_RBUTTONUP
                    self.pending.append("menu")
                elif event == 0x0203:  # WM_LBUTTONDBLCLK
                    self.pending.append("settings")
            elif msg == WM_RESET_POSITION:
                self.pending.append("reset")
            elif msg == self.taskbar_created:
                # The shell has (re)started -- our icon went with it.
                self.pending.append("readd")
            elif msg == WM_CLOSE:
                self.pending.append("quit")
                return 0
        except Exception as e:
            log_exception("window procedure", e)
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _dispatch(self, action):
        """Run a queued action from clean Tk context."""
        try:
            if action == "menu":
                self._menu()
            elif action == "settings":
                self.widget.open_settings()
            elif action == "reset":
                self.widget.reset_position()
            elif action == "readd":
                self._add_icon()
            elif action == "quit":
                self.widget.quit()
        except Exception as e:
            log_exception("tray action %r" % action, e)

    def _menu(self):
        u = ctypes.windll.user32
        menu = u.CreatePopupMenu()
        entries = [
            (MENU_SETTINGS, "Settings"),
            (MENU_RESET, "Reset position"),
            (MENU_WELCOME, "What is this?"),
            (MENU_QUIT, "Quit"),
        ]
        pending = self.widget.s.get("available_version")
        if pending and is_newer(pending, __version__):
            entries.insert(0, (MENU_UPDATE, "Get update (%s)" % pending))
        for ident, label in entries:
            u.AppendMenuW(menu, 0x0, ident, label)  # MF_STRING
        point = _Point()
        u.GetCursorPos(ctypes.byref(point))
        # Foreground first, and a stray post after, or the menu won't dismiss
        # when the user clicks elsewhere -- a long-standing shell quirk.
        u.SetForegroundWindow(self.hwnd)
        choice = u.TrackPopupMenu(
            menu, 0x0100 | 0x0002, point.x, point.y, 0, self.hwnd, None
        )  # TPM_RETURNCMD | TPM_RIGHTBUTTON
        u.PostMessageW(self.hwnd, 0x0000, 0, 0)  # WM_NULL
        u.DestroyMenu(menu)
        if choice == MENU_SETTINGS:
            self.widget.open_settings()
        elif choice == MENU_RESET:
            self.widget.reset_position()
        elif choice == MENU_WELCOME:
            self.widget.show_welcome()
        elif choice == MENU_UPDATE:
            self.widget.open_release_page()
        elif choice == MENU_QUIT:
            self.widget.quit()

    def _pump(self):
        """Drain our window's messages from Tk's loop, then run what they asked for.

        Filtered to self.hwnd on purpose: an unfiltered PeekMessage would steal
        messages out from under Tk's own event loop. Queued actions are run
        after the dispatch loop, so Tk work never happens inside the wndproc.
        """
        u = ctypes.windll.user32
        msg = wintypes.MSG()
        try:
            while u.PeekMessageW(ctypes.byref(msg), self.hwnd, 0, 0, 1):  # PM_REMOVE
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            log_exception("tray pump", e)
        while self.pending:
            self._dispatch(self.pending.pop(0))
        if self.ok:
            self.widget.root.after(50, self._pump)


def signal_running_widget(message):
    """Post a message to an already-running widget. False if none is running."""
    _declare_win32()
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(IPC_CLASS, None)
    if not hwnd:
        return False
    u.PostMessageW(hwnd, message, 0, 0)
    return True


class Tooltip:
    """One hover tooltip for the whole widget, carrying both reset times."""

    def __init__(self, widget):
        self.widget = widget
        self.win = None
        self.timer = None
        canvas = widget.canvas
        canvas.bind("<Enter>", self.schedule, add="+")
        canvas.bind("<Leave>", lambda e: self.hide(), add="+")
        canvas.bind("<Button-1>", lambda e: self.hide(), add="+")

    def schedule(self, _=None):
        self.cancel()
        self.timer = self.widget.root.after(TOOLTIP_DELAY_MS, self.show)

    def cancel(self):
        if self.timer:
            try:
                self.widget.root.after_cancel(self.timer)
            except Exception:
                pass
            self.timer = None

    def show(self):
        self.timer = None
        if self.widget.dragging:
            return
        self.hide()
        try:
            win = tk.Toplevel(self.widget.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            try:
                # Non-interactive, so it can never swallow a click meant for
                # the widget underneath or take focus from the active window.
                win.attributes("-disabled", True)
            except tk.TclError:
                pass
            frame = tk.Frame(win, bg="#141414", highlightthickness=1,
                             highlightbackground="#4a4a4a")
            frame.pack()
            for line in self.widget.tooltip_lines():
                tk.Label(
                    frame, text=line, bg="#141414", fg="#e8e8e8",
                    font=("Segoe UI", 8), anchor="w", justify="left",
                    padx=8, pady=1,
                ).pack(fill="x")
            win.update_idletasks()
            win.geometry("+%d+%d" % self._place(win))
            self.win = win
        except Exception as e:
            log_exception("tooltip", e)

    def _place(self, win):
        """Alongside the widget's long edge, flipped if there's no room.

        A wide widget gets the tooltip below it; a tall one gets it to the
        side, which is where the room actually is once it's parked against a
        left or right screen edge.
        """
        tw, th = win.winfo_reqwidth(), win.winfo_reqheight()
        wx, wy = self.widget.root.winfo_x(), self.widget.root.winfo_y()
        left, top, right, bottom = self.widget.current_rect(wx, wy)
        gap = 6
        if self.widget.s["vertical"]:
            x, y = wx + self.widget.w + gap, wy
            if x + tw > right:
                x = wx - tw - gap
        else:
            x, y = wx, wy + self.widget.h + gap
            if y + th > bottom:
                y = wy - th - gap
        return (max(left, min(x, right - tw)), max(top, min(y, bottom - th)))

    def hide(self):
        self.cancel()
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None


class Widget:
    def __init__(self):
        self.s = load_settings()
        self.session = self.s["last_session"]
        self.weekly = self.s["last_weekly"]
        self.live = False
        self.anim = None
        self.dragging = False
        self.press = None
        self.origin = None
        self.stopping = threading.Event()
        self.edge = self.s["edge"]

        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")
        # ponytail: one alpha for the whole window -- bars fade with the panel.
        # Upgrade path if that ever looks wrong: Win32 layered window via ctypes.
        self.root.attributes("-alpha", self.s["alpha"])

        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0, bd=0)
        self.canvas.pack()
        for seq, fn in (
            ("<Button-1>", self.on_press),
            ("<B1-Motion>", self.on_drag),
            ("<ButtonRelease-1>", self.on_release),
            ("<Button-3>", lambda e: self.open_settings()),
        ):
            self.canvas.bind(seq, fn)

        install_error_logging(self.root)

        # Rewrite the Run entry if it's enabled, so an entry written by an
        # older version picks up the current command line.
        if self.s["start_on_login"]:
            try:
                set_start_on_login(True)
            except OSError as e:
                log("could not refresh the startup entry:", e)

        self.layout()
        self.place_initial()
        self.tray = TrayIcon(self)
        self.tooltip = Tooltip(self)
        self.root.after(2000, self.watch_layout)
        self.root.after(MARKER_REFRESH_MS, self.tick_marker)
        self.apply_click_through()
        if not self.s["seen_welcome"]:
            self.root.after(400, self.show_welcome)
        threading.Thread(target=self.poll_loop, daemon=True).start()

    # --- geometry / drawing ---

    def layout(self):
        p, t, sp = self.s["padding"], self.s["thickness"], self.s["spacing"]
        self.w, self.h = widget_size(
            p, t, sp, self.s["vertical"], self.bar_length()
        )
        self.canvas.configure(width=self.w, height=self.h)
        self.root.geometry("%dx%d" % (self.w, self.h))
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        p, t, sp = self.s["padding"], self.s["thickness"], self.s["spacing"]
        vertical = self.s["vertical"]
        theme = THEMES.get(self.s["theme"], THEMES["claude"])
        length = self.bar_length()
        self.canvas.configure(bg=theme["panel"])
        self.root.configure(bg=theme["panel"])
        colour = theme["bar"] if self.live else GREY
        track = theme["track"]
        # Session first: the top bar horizontally, the left one vertically.
        bars = (
            (self.session, self.s["last_session_reset"], SESSION_WINDOW_SECONDS),
            (self.weekly, self.s["last_weekly_reset"], WEEKLY_WINDOW_SECONDS),
        )
        for i, (pct, reset, window) in enumerate(bars):
            def rect(a0, a1, index=i):
                return bar_rect(a0, a1, index, p, t, sp, vertical, length)

            self.canvas.create_rectangle(*rect(0, length), fill=track, width=0)
            fill = length * max(0.0, min(100.0, pct)) / 100.0
            if fill > 0:
                self.canvas.create_rectangle(*rect(0, fill), fill=colour, width=0)
            # How far through the window we are: black over the spent portion,
            # white over the empty track, so it reads against either.
            progress = window_progress(reset, window)
            if progress is not None:
                at = min(length - 1, length * progress)
                self.canvas.create_rectangle(
                    *rect(at, at + 1), width=0,
                    fill=MARKER_ON_FILL if at < fill else MARKER_ON_TRACK,
                )

    def bar_length(self):
        """Configured length, clamped to what the current monitor can show.

        Deliberately avoids self.w/self.h: layout() calls this to work them
        out, so relying on them here would be circular.
        """
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        except Exception:
            x = y = 0
        fallback = (0, 0, self.root.winfo_screenwidth(),
                    self.root.winfo_screenheight())
        longest = max_bar_length(
            monitor_work_area(x, y, fallback), self.s["padding"],
            self.s["vertical"],
        )
        return max(MIN_BAR_LENGTH, min(int(self.s["bar_length"]), longest))

    def current_rect(self, x=None, y=None):
        """Work area of the monitor the widget is currently on."""
        x = self.root.winfo_x() if x is None else x
        y = self.root.winfo_y() if y is None else y
        fallback = (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        return monitor_work_area(x + self.w / 2, y + self.h / 2, fallback)

    def default_position(self):
        """Top-right of the primary monitor -- the always-safe fallback."""
        fallback = (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        self.edge = "right"
        self.s["edge"] = "right"
        return top_right_of(
            primary_work_area(fallback), self.w, self.h, self.s["edge_gap"]
        )

    def place_initial(self):
        # Vet the saved coordinates directly rather than placing the window and
        # asking where it landed: winfo_x/y read 0 until Tk has mapped it, so a
        # check made here would test the wrong point and pass by accident.
        pos = self.s["pos"]
        if not pos or not point_on_monitor(pos[0] + self.w / 2, pos[1] + self.h / 2):
            pos = self.default_position()
            self.s["pos"] = list(pos)
            save_settings(self.s)
        self.root.geometry("+%d+%d" % (pos[0], pos[1]))

    def ensure_visible(self):
        """Recall the widget to the primary monitor if it's stranded off-screen.

        Tests the centre point: if that's on a real monitor at least half the
        widget is visible, and a monitor that shrank underneath it fails too.
        """
        if self.anim or self.dragging:
            return  # don't fight a move in progress
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if point_on_monitor(x + self.w / 2, y + self.h / 2):
            return
        target = self.default_position()
        self.root.geometry("+%d+%d" % target)
        self.s["pos"] = list(target)
        save_settings(self.s)

    def tick_marker(self):
        """Advance the window markers between polls -- cached times, no network."""
        self.draw()
        self.root.after(MARKER_REFRESH_MS, self.tick_marker)

    def watch_layout(self):
        self.ensure_visible()
        self.root.after(2000, self.watch_layout)

    def toggle_vertical(self, value, scales):
        """Standing the widget on end changes which screen dimension bounds it."""
        self.apply_live("vertical", value)
        scale = scales.get("bar_length")
        if scale is not None:
            longest = max_bar_length(
                self.current_rect(), self.s["padding"], value
            )
            scale.configure(to=longest)
            if self.s["bar_length"] > longest:
                self.apply_live("bar_length", longest)

    def apply_click_through(self):
        """Let the mouse pass through to whatever is underneath.

        Costs the hover tooltip -- with no mouse events reaching the canvas it
        can never fire -- so the tray becomes the only way in. Stated in the
        settings window and the README, since it otherwise reads as a bug.
        """
        try:
            user32 = ctypes.windll.user32
            hwnd = self.root.winfo_id()
            # Under overrideredirect winfo_id can be the child; the toplevel is
            # its parent when so.
            parent = user32.GetParent(hwnd)
            if parent:
                hwnd = parent
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_long.restype = ctypes.c_ssize_t
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
            set_long.restype = ctypes.c_ssize_t
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            style = get_long(hwnd, -20)  # GWL_EXSTYLE
            transparent = 0x20 | 0x80000  # WS_EX_TRANSPARENT | WS_EX_LAYERED
            if self.s["click_through"]:
                style |= transparent
            else:
                style &= ~0x20  # keep LAYERED: the alpha setting relies on it
            set_long(hwnd, -20, style)
            if self.s["click_through"]:
                self.tooltip.hide()
        except Exception as e:
            log_exception("click-through", e)

    def tooltip_lines(self):
        """Two lines: the session as a countdown, the week as a wall-clock time."""
        session = self.s["last_session_reset"]
        weekly = self.s["last_weekly_reset"]
        lines = [
            "Current session: resets %s" % (
                format_countdown(session - time.time()) if session
                else "at an unknown time"
            ),
            "Weekly limit: resets %s" % format_reset_time(weekly),
        ]
        lines.append(self.pace_line())
        return lines

    def pace_line(self):
        """Whichever limit runs out first at the current rate, or 'on pace'."""
        soonest, soonest_label = None, ""
        for label, pct, reset, window in (
            ("session", self.session, self.s["last_session_reset"],
             SESSION_WINDOW_SECONDS),
            ("weekly", self.weekly, self.s["last_weekly_reset"],
             WEEKLY_WINDOW_SECONDS),
        ):
            hit = project_exhaustion(pct, window_progress(reset, window), window)
            if hit is not None and (soonest is None or hit < soonest):
                soonest, soonest_label = hit, label
        if soonest is None:
            return "On pace — both limits should last their windows"
        return "At this rate: %s limit reached by %s" % (
            soonest_label, format_reset_time(soonest)
        )

    def show_welcome(self):
        """Once, on first run. The tray icon is undiscoverable otherwise."""
        self.s["seen_welcome"] = True
        save_settings(self.s)
        win = tk.Toplevel(self.root)
        win.title(WINDOW_TITLE)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Two bars, and that's it.",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        for line in (
            "The top bar is your current Claude session — the rolling 5-hour limit.",
            "The bottom bar is your weekly limit.",
            "",
            "The thin line in each bar shows how far through that window you are."
            " If a bar is ahead of its line, you're using it faster than the clock.",
            "",
            "Hover for reset times. Right-click for settings.",
            "It also sits in your system tray — right-click there for settings,"
            " to recall it if you lose it, or to quit.",
        ):
            ttk.Label(frame, text=line, wraplength=380, justify="left").pack(
                anchor="w", pady=(0, 2)
            )

        startup = tk.BooleanVar(value=self.s["start_on_login"])
        ttk.Checkbutton(frame, text="Start with Windows",
                        variable=startup).pack(anchor="w", pady=(12, 0))

        def close():
            if startup.get() != self.s["start_on_login"]:
                try:
                    set_start_on_login(startup.get())
                    self.s["start_on_login"] = startup.get()
                    save_settings(self.s)
                except OSError as e:
                    log("startup registry write failed:", e)
            win.destroy()

        ttk.Button(frame, text="Got it", command=close).pack(anchor="e", pady=(14, 0))
        win.protocol("WM_DELETE_WINDOW", close)

    def reset_position(self):
        """Put the widget back top-right of the primary monitor."""
        target = self.default_position()
        self.root.geometry("+%d+%d" % target)
        self.s["pos"] = list(target)
        save_settings(self.s)

    def quit(self):
        self.stopping.set()  # let the poll thread finish before the interpreter does
        if self.tray:
            self.tray.remove()
        self.root.destroy()

    def reposition(self, save=False):
        """Re-seat the widget against its current edge (e.g. after a gap change)."""
        x, y = self.root.winfo_x(), self.root.winfo_y()
        target = edge_position(
            self.edge, x, y, self.w, self.h, self.current_rect(x, y),
            self.s["edge_gap"],
        )
        self.root.geometry("+%d+%d" % target)
        self.s["pos"] = list(target)
        if save:
            save_settings(self.s)

    # --- polling ---

    def poll_loop(self):
        # Waits on an Event rather than sleeping: a daemon thread parked in
        # time.sleep wakes up during interpreter shutdown to find the GIL gone,
        # which ends the process with a fatal error instead of a clean exit.
        failures = 0
        while not self.stopping.is_set():
            result = fetch_usage()
            if self.stopping.is_set():
                return
            try:
                self.root.after(0, self.apply_usage, result)
            except tk.TclError:
                return  # window went away mid-poll

            if isinstance(result, Usage):
                failures = 0
                retry_after = None
            else:
                failures += 1
                retry_after = result.retry_after
            self.maybe_check_update()
            # Backs off while failing and spreads installations out, so a
            # popular copy of this doesn't become a thundering herd.
            delay = backoff_delay(
                failures, retry_after, jitter=random.uniform(-0.1, 0.1)
            )
            # First failure, then every fifth: enough to diagnose, not a spam log.
            if failures and (failures == 1 or failures % 5 == 0):
                log("poll failed (%s); next attempt in %d min"
                    % (result.reason, round(delay / 60)))
            self.stopping.wait(delay)

    def apply_usage(self, result):
        self.live = isinstance(result, Usage)
        if self.live:
            self.session, self.weekly = result.session, result.weekly
            self.s["last_session"] = result.session
            self.s["last_weekly"] = result.weekly
            # Cached because a reset time stays true without the API: the
            # marker and tooltip keep working while the bars are grey.
            if result.session_reset:
                self.s["last_session_reset"] = result.session_reset
            if result.weekly_reset:
                self.s["last_weekly_reset"] = result.weekly_reset
            save_settings(self.s)
        self.draw()
        # The bars are deliberately unlabelled, so the tooltip carries the numbers.
        if self.live:
            tip = "Session %d%%  ·  Weekly %d%%" % (self.session, self.weekly)
            self.check_alerts()
        else:
            tip = result.reason
        self.tray.set_tooltip("%s\n%s" % (WINDOW_TITLE, tip))

    def maybe_check_update(self):
        """Once a day at most, ask GitHub whether there's a newer release.

        Runs on the poll thread, so the network wait is off the UI. Never
        downloads or replaces anything -- it only offers to open the page.
        """
        if not self.s["update_check"]:
            return
        now = time.time()
        if now - (self.s["last_update_check"] or 0) < UPDATE_CHECK_SECONDS:
            return
        self.s["last_update_check"] = now
        latest = fetch_latest_version()
        if not latest or not is_newer(latest, __version__):
            return
        if latest == self.s["available_version"]:
            return  # already told them about this one
        self.s["available_version"] = latest
        try:
            self.root.after(0, self.announce_update, latest)
        except tk.TclError:
            pass

    def announce_update(self, latest):
        save_settings(self.s)
        self.tray.notify(
            "Update available",
            "%s is out — you have %s. Right-click the tray icon to get it."
            % (latest, __version__),
        )

    def open_release_page(self):
        try:
            webbrowser.open(RELEASES_PAGE)
        except Exception as e:
            log("could not open the releases page:", e)

    def check_alerts(self):
        """Warn once per threshold per window, via a tray balloon."""
        if not self.s["alerts"]:
            return
        for label, pct, reset, key, window in (
            ("Session", self.session, self.s["last_session_reset"],
             "alerted_session", SESSION_WINDOW_SECONDS),
            ("Weekly", self.weekly, self.s["last_weekly_reset"],
             "alerted_weekly", WEEKLY_WINDOW_SECONDS),
        ):
            due, state = due_alerts(pct, reset, self.s[key])
            if state != self.s[key]:
                self.s[key] = state
                save_settings(self.s)
            for threshold in due:
                when = (
                    format_countdown(reset - time.time()) if reset
                    else "at an unknown time"
                )
                self.tray.notify(
                    "%s limit %d%% used" % (label, threshold),
                    "%s resets %s." % (label, when),
                )

    # --- drag / snap ---

    def on_press(self, e):
        self.press = (e.x_root, e.y_root)
        self.origin = (self.root.winfo_x(), self.root.winfo_y())
        self.dragging = True
        self.tooltip.hide()

    def on_drag(self, e):
        # A drag or release can arrive with no press behind it -- press
        # elsewhere and let go over the widget, or have the window appear
        # under the cursor mid-click -- so there may be no anchor to move from.
        if self.press is None:
            return
        dx = e.x_root - self.press[0]
        dy = e.y_root - self.press[1]
        self.root.geometry("+%d+%d" % (self.origin[0] + dx, self.origin[1] + dy))

    def on_release(self, e):
        self.dragging = False
        if self.press is None:
            return
        moved = abs(e.x_root - self.press[0]) + abs(e.y_root - self.press[1])
        self.press = None
        if moved < 5:
            self.on_click()
        else:
            self.snap()

    def on_click(self):
        if self.live:
            self.open_settings()
        else:
            self.launch_claude()

    def ensure_launch_cmd(self):
        """Resolve how to start Claude on first use, then remember it."""
        if not self.s["launch_cmd"]:
            self.s["launch_cmd"] = detect_launch_cmd()
            if self.s["launch_cmd"]:
                save_settings(self.s)
        return self.s["launch_cmd"]

    def launch_claude(self):
        cmd = self.ensure_launch_cmd()
        if not cmd:
            return
        try:
            # Whatever the user has in this field, run as typed -- it is a
            # command line they own, not untrusted input.
            subprocess.Popen(cmd, shell=True)
        except OSError as e:
            log("launch failed:", e)

    def snap(self):
        x, y = self.root.winfo_x(), self.root.winfo_y()
        rect = self.current_rect(x, y)
        self.edge = nearest_edge(x, y, self.w, self.h, rect)
        self.s["edge"] = self.edge
        target = edge_position(
            self.edge, x, y, self.w, self.h, rect, self.s["edge_gap"]
        )
        self.animate_to((x, y), target)

    def animate_to(self, start, target, step=0, steps=16):
        if self.anim:
            self.root.after_cancel(self.anim)
        t = ease_out((step + 1) / steps)
        x = round(start[0] + (target[0] - start[0]) * t)
        y = round(start[1] + (target[1] - start[1]) * t)
        self.root.geometry("+%d+%d" % (x, y))
        if step + 1 < steps:
            self.anim = self.root.after(
                16, self.animate_to, start, target, step + 1, steps
            )
        else:
            self.anim = None
            self.s["pos"] = list(target)
            save_settings(self.s)

    # --- settings modal ---

    def apply_live(self, key, value):
        """Push one setting straight onto the widget, no save."""
        self.s[key] = value
        if key == "alpha":
            self.root.attributes("-alpha", value)
        elif key == "edge_gap":
            self.reposition()
        elif key == "click_through":
            self.apply_click_through()
        elif key == "theme":
            self.draw()
        else:
            self.layout()
            self.reposition()  # size changed, so the edge offset needs redoing

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Claude Usage Widget")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)

        before = dict(self.s)  # for Cancel

        longest = max_bar_length(
            self.current_rect(), self.s["padding"], self.s["vertical"]
        )
        scales = {}
        sliders = [
            ("Line length", "bar_length", MIN_BAR_LENGTH, longest, 0),
            ("Line thickness", "thickness", 1, 12, 0),
            ("Spacing between lines", "spacing", 0, 30, 0),
            ("Padding from edge", "padding", 0, 30, 0),
            ("Background opacity", "alpha", 0.15, 1.0, 2),
            ("Distance from screen edge", "edge_gap", 0, 100, 0),
        ]
        for row, (label, key, lo, hi, places) in enumerate(sliders):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            var = tk.DoubleVar(value=float(self.s[key]))
            scale = ttk.Scale(frame, from_=lo, to=hi, variable=var, length=170)
            scale.grid(row=row, column=1, padx=8)
            scales[key] = scale
            readout = ttk.Label(frame, width=6)
            readout.grid(row=row, column=2, sticky="e")

            def update(*_, v=var, lbl=readout, pl=places, k=key):
                value = round(v.get(), pl) if pl else int(v.get())
                lbl.configure(text=("%.*f" % (pl, value)))
                self.apply_live(k, value)

            var.trace_add("write", update)
            update()

        row = len(sliders)
        ttk.Label(frame, text="Colours").grid(row=row, column=0, sticky="w", pady=3)
        theme = tk.StringVar(value=self.s["theme"])
        ttk.Combobox(
            frame, textvariable=theme, state="readonly", width=14,
            values=sorted(THEMES),
        ).grid(row=row, column=1, padx=8, sticky="w")
        theme.trace_add("write", lambda *_: self.apply_live("theme", theme.get()))

        row += 1
        vertical = tk.BooleanVar(value=self.s["vertical"])
        ttk.Checkbutton(
            frame, text="Vertical layout", variable=vertical,
            command=lambda: self.toggle_vertical(vertical.get(), scales),
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 3))

        row += 1
        alerts = tk.BooleanVar(value=self.s["alerts"])
        ttk.Checkbutton(
            frame, text="Warn me at 80% and 95%", variable=alerts,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 3))

        row += 1
        updates = tk.BooleanVar(value=self.s["update_check"])
        ttk.Checkbutton(
            frame, text="Check GitHub for updates", variable=updates,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 3))

        row += 1
        click_through = tk.BooleanVar(value=self.s["click_through"])
        ttk.Checkbutton(
            frame, text="Click-through (mouse passes to the window beneath)",
            variable=click_through,
            command=lambda: self.apply_live("click_through", click_through.get()),
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 0))
        row += 1
        ttk.Label(
            frame, foreground="#777777", wraplength=330, justify="left",
            text="While click-through is on the widget ignores the mouse, so the"
                 " hover tooltip won't appear and you can't drag it. Use the tray"
                 " icon for settings, to move it back, or to quit.",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))

        row += 1
        startup = tk.BooleanVar(value=self.s["start_on_login"])
        ttk.Checkbutton(frame, text="Open on startup", variable=startup).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 3)
        )

        row += 1
        ttk.Label(frame, text="Launch command (used when grey)").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(8, 2)
        )
        row += 1
        launch = tk.StringVar(value=self.ensure_launch_cmd())
        ttk.Entry(frame, textvariable=launch, width=48).grid(
            row=row, column=0, columnspan=3, sticky="we"
        )

        def save():
            self.s["launch_cmd"] = launch.get().strip()
            self.s["alerts"] = alerts.get()
            self.s["update_check"] = updates.get()
            if startup.get() != self.s["start_on_login"]:
                try:
                    set_start_on_login(startup.get())
                    self.s["start_on_login"] = startup.get()
                except OSError as e:
                    log("startup registry write failed:", e)
            save_settings(self.s)
            win.destroy()

        def cancel():
            self.s.update(before)
            self.root.attributes("-alpha", self.s["alpha"])
            self.apply_click_through()
            self.layout()
            self.reposition()
            save_settings(self.s)
            win.destroy()

        row += 1
        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=3, sticky="we", pady=(14, 0))
        ttk.Button(buttons, text="Quit widget", command=self.quit).pack(side="left")
        ttk.Button(buttons, text="Save", command=save).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=cancel).pack(side="right", padx=6)
        win.protocol("WM_DELETE_WINDOW", cancel)

    def run(self):
        self.root.mainloop()


def selftest():
    w, h = 132, 23
    # primary monitor, 1920x1080
    primary = (0, 0, 1920, 1080)
    assert nearest_edge(10, 500, w, h, primary) == "left"
    assert nearest_edge(1700, 500, w, h, primary) == "right"
    assert nearest_edge(900, 20, w, h, primary) == "top"
    assert nearest_edge(900, 1000, w, h, primary) == "bottom"
    assert nearest_edge(894, 528, w, h, primary) in ("top", "bottom")

    # second monitor to the right: edges are relative to that monitor, not the desktop
    right_mon = (1920, 0, 3840, 1080)
    assert nearest_edge(1930, 500, w, h, right_mon) == "left"
    assert nearest_edge(3600, 500, w, h, right_mon) == "right"
    # a monitor at negative coordinates (left of primary) works too
    left_mon = (-1920, 0, 0, 1080)
    assert nearest_edge(-1910, 500, w, h, left_mon) == "left"
    assert nearest_edge(-200, 500, w, h, left_mon) == "right"

    # snapped positions honour the gap and the monitor's own origin
    assert edge_position("right", 3600, 500, w, h, right_mon, 12) == (3696, 500)
    assert edge_position("left", 1930, 500, w, h, right_mon, 12) == (1932, 500)
    assert edge_position("top", -900, 700, w, h, left_mon, 12) == (-900, 12)
    # a taskbar-reduced work area keeps the widget inside it
    x, y = edge_position("bottom", 900, 500, w, h, (0, 0, 1920, 1040), 12)
    assert y + h <= 1040

    # token parsing: both the wrapped and bare shapes, expiry respected
    future = (time.time() + 3600) * 1000
    past = (time.time() - 3600) * 1000
    assert _token_from_blob(
        json.dumps({"claudeAiOauth": {"accessToken": "t", "expiresAt": future}})
    ) == "t"
    assert _token_from_blob(
        json.dumps({"accessToken": "t", "expiresAt": future})
    ) == "t"
    assert _token_from_blob(
        json.dumps({"claudeAiOauth": {"accessToken": "t", "expiresAt": past}})
    ) is None
    assert _token_from_blob(json.dumps({"claudeAiOauth": {}})) is None
    assert _token_from_blob("not json") is None
    # a token with no expiry recorded is used rather than discarded
    assert _token_from_blob(json.dumps({"accessToken": "t"})) == "t"

    # credential search covers CLAUDE_CONFIG_DIR and the default location
    os.environ["CLAUDE_CONFIG_DIR"] = os.path.join("X:", "custom")
    try:
        paths = credential_files()
    finally:
        del os.environ["CLAUDE_CONFIG_DIR"]
    assert paths[0] == os.path.join("X:", "custom", ".credentials.json")
    assert any(p.endswith(os.path.join(".claude", ".credentials.json")) for p in paths)
    assert len(paths) == len(set(paths)), "duplicate paths"
    assert all(os.path.isabs(p) or p[1:2] == ":" for p in credential_files())

    # the off-screen fallback lands top-right of the primary work area
    assert top_right_of(primary, w, h, 12) == (1920 - w - 12, 12)
    # respects a taskbar-reduced work area and a monitor that isn't at the origin
    assert top_right_of((0, 40, 1920, 1080), w, h, 12) == (1920 - w - 12, 52)
    assert top_right_of(right_mon, w, h, 0) == (3840 - w, 0)
    # a stranded position is off every monitor, so it must not survive as-is
    assert not (primary[0] <= -30000 <= primary[2])

    # backoff: steady when healthy, doubling while failing, capped
    assert backoff_delay(0, base=300) == 300
    assert backoff_delay(1, base=300) == 600
    assert backoff_delay(2, base=300) == 1200
    assert backoff_delay(99, base=300) == MAX_BACKOFF_SECONDS, "must cap"
    # a server's Retry-After wins when it asks for longer, and is itself capped
    assert backoff_delay(0, retry_after=900, base=300) == 900
    assert backoff_delay(0, retry_after=10, base=300) == 300, "never poll sooner"
    assert backoff_delay(0, retry_after=99999, base=300) == MAX_BACKOFF_SECONDS
    # jitter stays within its band and never yields a nonsense delay
    assert backoff_delay(0, base=300, jitter=0.1) == 330
    assert backoff_delay(0, base=300, jitter=-0.1) == 270
    assert backoff_delay(0, base=0.001, jitter=-0.99) >= 1.0

    assert parse_retry_after("120") == 120
    assert parse_retry_after(None) is None
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None  # date form
    assert parse_retry_after("-5") is None

    # alerts: each threshold fires once, and a new window makes them eligible again
    due, state = due_alerts(85, 1000, None)
    assert due == [80], due
    assert due_alerts(85, 1000, state)[0] == [], "must not re-fire in same window"
    due, state = due_alerts(96, 1000, state)
    assert due == [95]
    assert due_alerts(96, 1000, state)[0] == []
    # crossing both at once fires both, once
    assert due_alerts(99, 2000, None)[0] == [80, 95]
    # the same percentage in a NEW window fires again
    assert due_alerts(85, 3000, state)[0] == [80], "new window must reset"
    assert due_alerts(50, 1000, None)[0] == []

    # burn rate: only meaningful once some of the window has elapsed
    now = 1_000_000.0
    assert project_exhaustion(50, 0.0, SESSION_WINDOW_SECONDS, now) is None
    assert project_exhaustion(50, 0.01, SESSION_WINDOW_SECONDS, now) is None
    # spending exactly in step with the clock lasts the window: on pace
    assert project_exhaustion(50, 0.5, SESSION_WINDOW_SECONDS, now) is None
    # burning twice as fast as the clock runs out before the window does
    hit = project_exhaustion(50, 0.25, SESSION_WINDOW_SECONDS, now)
    assert hit is not None and now < hit < now + SESSION_WINDOW_SECONDS
    # half the usage rate of the clock is comfortably on pace
    assert project_exhaustion(25, 0.5, SESSION_WINDOW_SECONDS, now) is None
    # already spent
    assert project_exhaustion(100, 0.5, SESSION_WINDOW_SECONDS, now) == now

    # every theme defines every colour the drawing code asks for
    for name, theme in THEMES.items():
        assert set(theme) == {"bar", "track", "panel"}, name
        assert all(v.startswith("#") and len(v) == 7 for v in theme.values()), name

    # versions compare as numbers, not text
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.2") == (1, 2, 0)
    assert parse_version("") == (0, 0, 0) and parse_version(None) == (0, 0, 0)
    assert is_newer("v0.10.0", "0.9.0"), "10 > 9; string comparison gets this wrong"
    assert not is_newer("v0.9.0", "0.10.0")
    assert not is_newer("v1.0.0", "1.0.0"), "same version is not an update"
    assert is_newer("v1.0.1", "1.0.0") and is_newer("v2.0.0", "1.9.9")
    assert not is_newer("garbage", __version__)

    # .ico structure: header, one entry per size, offsets that actually line up
    blob = ico_bytes((16, 32, 48))
    reserved, kind, count = struct.unpack("<HHH", blob[:6])
    assert (reserved, kind) == (0, 1), "must declare itself an icon"
    assert count == 3
    seen = []
    for i in range(count):
        entry = blob[6 + 16 * i:6 + 16 * (i + 1)]
        width, height, _, _, planes, bpp, size, offset = struct.unpack(
            "<BBBBHHII", entry
        )
        seen.append(width)
        assert (planes, bpp) == (1, 32)
        assert offset + size <= len(blob), "image runs past the end of the file"
        # each image is a BMP header declaring double height, for the AND mask
        declared_h = struct.unpack("<i", blob[offset + 8:offset + 12])[0]
        assert declared_h == width * 2, (width, declared_h)
    assert seen == [16, 32, 48]

    # data_dir: the portable marker wins, otherwise the roaming profile
    import tempfile
    real_app_dir = globals()["app_dir"]
    with tempfile.TemporaryDirectory() as tmp:
        globals()["app_dir"] = lambda: tmp
        roaming = os.environ.get("APPDATA")
        try:
            os.environ["APPDATA"] = os.path.join(tmp, "roaming")
            assert data_dir() == os.path.join(tmp, "roaming", APP_FOLDER)

            open(os.path.join(tmp, PORTABLE_MARKER), "w").close()
            assert data_dir() == tmp, "portable.txt must win"

            os.remove(os.path.join(tmp, PORTABLE_MARKER))
            os.environ.pop("APPDATA")
            assert data_dir() == tmp, "no profile: fall back to beside the program"
        finally:
            globals()["app_dir"] = real_app_dir
            if roaming is not None:
                os.environ["APPDATA"] = roaming

    # on-the-hour times drop the ':00' -- '4am', not '4:00am'
    four_am = time.mktime((2026, 8, 2, 4, 0, 0, 0, 0, -1))
    quarter_past = time.mktime((2026, 8, 2, 4, 15, 0, 0, 0, -1))
    midday = time.mktime((2026, 8, 2, 12, 0, 0, 0, 0, -1))
    midnight_exact = time.mktime((2026, 8, 2, 0, 0, 0, 0, 0, -1))
    assert format_clock(four_am) == "4am", format_clock(four_am)
    assert format_clock(quarter_past) == "4:15am", format_clock(quarter_past)
    assert format_clock(midday) == "12pm", format_clock(midday)
    assert format_clock(midnight_exact) == "12am", format_clock(midnight_exact)
    a_different_day = time.mktime((2026, 7, 30, 9, 0, 0, 0, 0, -1))
    assert format_reset_time(four_am, a_different_day) == "Sun 4am"

    # bar length is bounded by the work area on whichever axis it runs along
    screen = (0, 0, 1920, 1040)  # 1040: taskbar already excluded by rcWork
    assert max_bar_length(screen, 0, False) == 1920
    assert max_bar_length(screen, 0, True) == 1040
    assert max_bar_length(screen, 10, False) == 1900, "padding eats into it"
    # a tiny or silly work area still yields something drawable
    assert max_bar_length((0, 0, 10, 10), 50, False) == MIN_BAR_LENGTH

    # geometry honours a custom length rather than the default constant
    assert widget_size(0, 3, 0, False, 500) == (500, 6)
    assert widget_size(0, 3, 0, True, 500) == (6, 500)
    assert bar_rect(0, 500, 0, 0, 3, 0, False, 500) == (0, 0, 500, 3)
    # vertical still anchors the fill to the foot at a custom length
    assert bar_rect(0, 125, 0, 0, 3, 0, True, 500) == (0, 375, 3, 500)

    # orientation: vertical is the horizontal case with its axes transposed
    pad, thick, space = 6, 3, 5
    wide = widget_size(pad, thick, space, False)
    tall = widget_size(pad, thick, space, True)
    assert wide == (BAR_LENGTH + 12, 3 * 2 + 5 + 12)
    assert tall == (wide[1], wide[0]), (wide, tall)

    def rect(a0, a1, index, vertical):
        return bar_rect(a0, a1, index, pad, thick, space, vertical)

    quarter = BAR_LENGTH * 0.25
    # horizontal: full-length track, and a 25% fill sitting on the LEFT
    assert rect(0, BAR_LENGTH, 0, False) == (pad, pad, pad + BAR_LENGTH, pad + thick)
    x0, y0, x1, y1 = rect(0, quarter, 0, False)
    assert (x0, x1) == (pad, pad + quarter), "horizontal fill should start at the left"
    # second bar sits below the first
    assert rect(0, BAR_LENGTH, 1, False)[1] == pad + thick + space

    # vertical: full-height track, and a 25% fill sitting at the BOTTOM
    assert rect(0, BAR_LENGTH, 0, True) == (pad, pad, pad + thick, pad + BAR_LENGTH)
    x0, y0, x1, y1 = rect(0, quarter, 0, True)
    assert y1 == pad + BAR_LENGTH, "vertical fill must be anchored to the foot"
    assert y0 == pad + BAR_LENGTH - quarter, "vertical fill must grow upward"
    assert (x0, x1) == (pad, pad + thick)
    # second bar sits to the RIGHT, which puts the session bar on the left
    assert rect(0, BAR_LENGTH, 1, True)[0] == pad + thick + space
    assert rect(0, BAR_LENGTH, 1, True)[1] == pad, "bars share the same top"

    # a 100% fill covers its track exactly, and an empty one has no area
    for vert in (False, True):
        assert rect(0, BAR_LENGTH, 0, vert) == rect(0, BAR_LENGTH, 0, vert)
        empty = rect(0, 0, 0, vert)
        assert empty[0] == empty[2] or empty[1] == empty[3], empty
        # every rectangle stays inside the widget
        w, h = widget_size(pad, thick, space, vert)
        for r in (rect(0, BAR_LENGTH, 1, vert), rect(0, quarter, 1, vert)):
            assert 0 <= r[0] <= r[2] <= w and 0 <= r[1] <= r[3] <= h, r

    # window progress: derived from the reset time and a fixed window length
    now = 1_000_000.0
    hour = 3600.0
    assert window_progress(now + 2.5 * hour, SESSION_WINDOW_SECONDS, now) == 0.5
    assert window_progress(now + 5 * hour, SESSION_WINDOW_SECONDS, now) == 0.0
    assert window_progress(now, SESSION_WINDOW_SECONDS, now) == 1.0
    # a reset already past, or further out than the window, must stay on the bar
    assert window_progress(now - 9999, SESSION_WINDOW_SECONDS, now) == 1.0
    assert window_progress(now + 99 * hour, SESSION_WINDOW_SECONDS, now) == 0.0
    assert window_progress(None, SESSION_WINDOW_SECONDS, now) is None
    assert 0.5 == window_progress(now + 3.5 * 24 * hour, WEEKLY_WINDOW_SECONDS, now)

    # countdown wording
    assert format_countdown(31 * 60) == "in 31 min"
    assert format_countdown(59) == "in less than a minute"
    assert format_countdown(60) == "in 1 min"
    assert format_countdown(90 * 60) == "in 1h 30min"
    assert format_countdown(2 * 3600) == "in 2h"
    assert format_countdown(0) == "any moment now"
    assert format_countdown(-500) == "any moment now"
    assert format_countdown(None) == "at an unknown time"

    # 12-hour clock: midnight and noon are the classic off-by-twelve
    midnight = time.mktime((2026, 8, 2, 0, 5, 0, 0, 0, -1))
    noon = time.mktime((2026, 8, 2, 12, 5, 0, 0, 0, -1))
    morning = time.mktime((2026, 8, 2, 8, 45, 0, 0, 0, -1))
    other_day = time.mktime((2026, 7, 30, 9, 0, 0, 0, 0, -1))
    assert format_reset_time(midnight, other_day).endswith("12:05am")
    assert format_reset_time(noon, other_day).endswith("12:05pm")
    assert format_reset_time(morning, other_day).endswith("8:45am")
    assert format_reset_time(morning, other_day).startswith("Sun ")
    assert format_reset_time(None) == "at an unknown time"
    # same calendar day drops the day name, which is noise half an hour out
    assert format_reset_time(morning, morning) == "8:45am"
    assert format_clock(noon) == "12:05pm" and format_clock(midnight) == "12:05am"

    # ISO parsing, including the 'Z' form fromisoformat only took in 3.11
    assert parse_reset("2026-08-02T03:00:00.543041+00:00") == parse_reset(
        "2026-08-02T03:00:00.543041Z"
    )
    assert parse_reset(None) is None and parse_reset("nonsense") is None

    # marker colour: black over the spent portion, white over the empty track
    def marker_colour(pct, progress):
        fill = BAR_LENGTH * pct / 100.0
        x = min(BAR_LENGTH - 1, BAR_LENGTH * progress)
        return MARKER_ON_FILL if x < fill else MARKER_ON_TRACK
    assert marker_colour(80, 0.25) == MARKER_ON_FILL   # well inside the fill
    assert marker_colour(20, 0.75) == MARKER_ON_TRACK  # out on the bare track
    assert marker_colour(0, 0.5) == MARKER_ON_TRACK    # nothing used yet
    assert marker_colour(100, 0.5) == MARKER_ON_FILL   # bar completely full

    # tray icon buffer: square, 4 bytes a pixel, at whatever size is asked for
    for size in (16, 20, 32):
        bits = _bar_icon_bits(size)
        assert len(bits) == size * size * 4
        opaque = [i for i in range(0, len(bits), 4) if bits[i + 3]]
        assert opaque, "icon fully transparent at size %d" % size
        # two separate bars, so the opaque rows must come in two runs
        rows = sorted({(i // 4) // size for i in opaque})
        runs = 1 + sum(1 for a, b in zip(rows, rows[1:]) if b - a > 1)
        assert runs == 2, "expected two bars at size %d, got %d" % (size, runs)

    # queued tray actions run once each, and a bad one can't take the rest down
    class FakeTray:
        pending = ["reset", "boom", "settings"]
        done = []
        _dispatch = TrayIcon._dispatch
        widget = type("W", (), {
            "reset_position": lambda self: FakeTray.done.append("reset"),
            "open_settings": lambda self: FakeTray.done.append("settings"),
        })()
    fake = FakeTray()
    while fake.pending:
        fake._dispatch(fake.pending.pop(0))
    assert FakeTray.done == ["reset", "settings"], FakeTray.done

    # easing: anchored at both ends, monotonic, and front-loaded
    assert ease_out(0) == 0 and ease_out(1) == 1
    prev = -1
    for i in range(21):
        v = ease_out(i / 20)
        assert v > prev
        prev = v
    assert ease_out(0.5) > 0.5
    print("selftest ok")


def install_error_logging(root=None):
    """Route unhandled errors to widget.log.

    Without this they go to sys.stderr, which is None under pythonw -- so a
    crash at login leaves no trace anywhere.
    """
    sys.excepthook = lambda kind, exc, tb: log_exception("unhandled", exc)
    if root is not None:
        root.report_callback_exception = lambda kind, exc, tb: log_exception(
            "callback", exc
        )


if __name__ == "__main__":
    install_error_logging()
    if "--startup" in sys.argv:
        # Launched by Windows at login: the shell often isn't ready yet, and a
        # tray icon registered too early is silently dropped. TaskbarCreated
        # covers that too, but waiting avoids the flicker.
        log("starting at login")
        time.sleep(STARTUP_DELAY_SECONDS)
    if "--write-icon" in sys.argv:
        # Used by the build so the packaged icon and the tray icon are the
        # same pixels, and can't drift apart.
        target = sys.argv[sys.argv.index("--write-icon") + 1]
        with open(target, "wb") as f:
            f.write(ico_bytes())
        print("wrote", target)
    elif "--selftest" in sys.argv:
        # Report failures on stdout: running a .pyw suppresses stderr, so an
        # assertion otherwise fails completely silently, with only an exit
        # code to show for it.
        try:
            selftest()
        except Exception:
            print("SELFTEST FAILED")
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)
    elif "--quit" in sys.argv:
        print("closed" if signal_running_widget(WM_CLOSE) else "not running")
    elif "--reset" in sys.argv:
        print("recalled" if signal_running_widget(WM_RESET_POSITION) else "not running")
    elif not single_instance():
        # Already running: recall it, in case it was launched again because it
        # couldn't be found on screen.
        if not signal_running_widget(WM_RESET_POSITION):
            # Mutex held but no window found -- a stuck process from a prior
            # crash/kill is holding the lock. Recall does nothing visible, so
            # log it rather than exiting silently with no trace anywhere.
            log("mutex held but no window found -- a stale process may be "
                "stuck; check Task Manager for pythonw.exe/ClaudeUsageWidget.exe")
        sys.exit(0)
    else:
        Widget().run()
