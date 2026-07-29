"""Always-on-top Claude usage widget: session + weekly limit bars."""
__version__ = "0.7.0"

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

ORANGE = "#d17552"
GREY = "#7a7a7a"
TRACK = "#3a3a3a"
BAR_LENGTH = 120
POLL_SECONDS = 60
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "ClaudeUsageWidget"
WINDOW_TITLE = "Claude Usage Widget"
IPC_CLASS = "ClaudeUsageWidgetIPC"

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_TRAY = 0x8000  # WM_APP, our tray callback
WM_RESET_POSITION = 0x8001  # WM_APP+1, sent by --reset
MENU_SETTINGS, MENU_RESET, MENU_QUIT = 1, 2, 3

DEFAULTS = {
    "thickness": 3,
    "spacing": 5,
    "padding": 6,
    "alpha": 0.7,
    "edge_gap": 12,
    "start_on_login": False,
    "launch_cmd": "",
    "last_session": 0.0,
    "last_weekly": 0.0,
    "pos": None,
    "edge": "right",
}


def single_instance():
    """False if another copy is already running. Named mutex, released on exit."""
    kernel32 = ctypes.windll.kernel32
    global _MUTEX
    _MUTEX = kernel32.CreateMutexW(None, False, "ClaudeUsageWidget")
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def load_settings():
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
        print("could not save settings:", e, file=sys.stderr)


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


def fetch_usage():
    """Return (session_pct, weekly_pct), or None if usage can't be read.

    Uses the OAuth token Claude already stores. Deliberately does not refresh
    it -- racing Claude's own refresh can invalidate its session. Launching
    Claude is the refresh path.
    """
    token = find_token()
    if not token:
        return None
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
        return (
            float(data["five_hour"]["utilization"]),
            float(data["seven_day"]["utilization"]),
        )
    except Exception:
        return None  # ponytail: offline, 401, schema drift -- all mean "go grey"


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
            pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.exists(pythonw):
                pythonw = sys.executable
            cmd = '"%s" "%s"' % (pythonw, os.path.abspath(__file__))
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
    g.CreateBitmap.restype = wintypes.HBITMAP


def _bar_icon_bits():
    """16x16 BGRA buffer: two orange bars on transparent, echoing the widget."""
    r, g, b = int(ORANGE[1:3], 16), int(ORANGE[3:5], 16), int(ORANGE[5:7], 16)
    rows = []
    for y in range(16):
        row = bytearray()
        drawn = y in (5, 6, 7, 9, 10, 11)
        for x in range(16):
            if drawn and 2 <= x <= 13:
                row += bytes((b, g, r, 255))
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    return b"".join(rows)


def _make_icon():
    """Build the tray icon, or fall back to the stock application icon."""
    u, g = ctypes.windll.user32, ctypes.windll.gdi32

    class ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    try:
        bits = _bar_icon_bits()
        colour = g.CreateBitmap(16, 16, 1, 32, bits)
        mask = g.CreateBitmap(16, 16, 1, 1, b"\0" * 64)
        info = ICONINFO(True, 0, 0, mask, colour)
        u.CreateIconIndirect.restype = wintypes.HICON
        icon = u.CreateIconIndirect(ctypes.byref(info))
        g.DeleteObject(colour)
        g.DeleteObject(mask)
        if icon:
            return icon
    except Exception:
        pass  # ponytail: a generic tray icon beats no tray icon
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
        try:
            self._build()
            self.ok = True
        except Exception as e:
            print("tray icon unavailable:", e, file=sys.stderr)
            return
        self._pump()

    def _build(self):
        _declare_win32()
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        hinst = k.GetModuleHandleW(None)

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
        ctypes.windll.shell32.Shell_NotifyIconW(0, ctypes.byref(self.data))  # NIM_ADD

    def set_tooltip(self, text):
        if not self.ok:
            return
        self.data.szTip = text[:127]
        ctypes.windll.shell32.Shell_NotifyIconW(1, ctypes.byref(self.data))  # NIM_MODIFY

    def remove(self):
        if not self.ok:
            return
        self.ok = False
        ctypes.windll.shell32.Shell_NotifyIconW(2, ctypes.byref(self.data))  # NIM_DELETE

    def _wndproc(self, hwnd, msg, wparam, lparam):
        u = ctypes.windll.user32
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event == 0x0205:  # WM_RBUTTONUP
                self._menu()
            elif event == 0x0203:  # WM_LBUTTONDBLCLK
                self.widget.open_settings()
        elif msg == WM_RESET_POSITION:
            self.widget.reset_position()
        elif msg == WM_CLOSE:
            self.widget.quit()
            return 0
        return u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        u = ctypes.windll.user32
        menu = u.CreatePopupMenu()
        for ident, label in (
            (MENU_SETTINGS, "Settings"),
            (MENU_RESET, "Reset position"),
            (MENU_QUIT, "Quit"),
        ):
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
        elif choice == MENU_QUIT:
            self.widget.quit()

    def _pump(self):
        """Drain our window's messages from Tk's loop.

        Filtered to self.hwnd on purpose: an unfiltered PeekMessage would steal
        messages out from under Tk's own event loop.
        """
        u = ctypes.windll.user32
        msg = wintypes.MSG()
        while u.PeekMessageW(ctypes.byref(msg), self.hwnd, 0, 0, 1):  # PM_REMOVE
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
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


class Widget:
    def __init__(self):
        self.s = load_settings()
        self.session = self.s["last_session"]
        self.weekly = self.s["last_weekly"]
        self.live = False
        self.anim = None
        self.dragging = False
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

        self.layout()
        self.place_initial()
        self.tray = TrayIcon(self)
        self.root.after(2000, self.watch_layout)
        threading.Thread(target=self.poll_loop, daemon=True).start()

    # --- geometry / drawing ---

    def layout(self):
        p, t, sp = self.s["padding"], self.s["thickness"], self.s["spacing"]
        self.w = BAR_LENGTH + p * 2
        self.h = t * 2 + sp + p * 2
        self.canvas.configure(width=self.w, height=self.h)
        self.root.geometry("%dx%d" % (self.w, self.h))
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        p, t, sp = self.s["padding"], self.s["thickness"], self.s["spacing"]
        colour = ORANGE if self.live else GREY
        for i, pct in enumerate((self.session, self.weekly)):
            top = p + i * (t + sp)
            self.canvas.create_rectangle(
                p, top, p + BAR_LENGTH, top + t, fill=TRACK, width=0
            )
            fill = BAR_LENGTH * max(0.0, min(100.0, pct)) / 100.0
            if fill > 0:
                self.canvas.create_rectangle(
                    p, top, p + fill, top + t, fill=colour, width=0
                )

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

    def watch_layout(self):
        self.ensure_visible()
        self.root.after(2000, self.watch_layout)

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
        while not self.stopping.is_set():
            result = fetch_usage()
            if self.stopping.is_set():
                return
            try:
                self.root.after(0, self.apply_usage, result)
            except tk.TclError:
                return  # window went away mid-poll
            self.stopping.wait(POLL_SECONDS)

    def apply_usage(self, result):
        self.live = result is not None
        if result:
            self.session, self.weekly = result
            self.s["last_session"], self.s["last_weekly"] = result
            save_settings(self.s)
        self.draw()
        # The bars are deliberately unlabelled, so the tooltip carries the numbers.
        if result:
            tip = "Session %d%%  ·  Weekly %d%%" % (self.session, self.weekly)
        else:
            tip = "Usage unavailable — click the widget to start Claude"
        self.tray.set_tooltip("%s\n%s" % (WINDOW_TITLE, tip))

    # --- drag / snap ---

    def on_press(self, e):
        self.press = (e.x_root, e.y_root)
        self.origin = (self.root.winfo_x(), self.root.winfo_y())
        self.dragging = True

    def on_drag(self, e):
        dx = e.x_root - self.press[0]
        dy = e.y_root - self.press[1]
        self.root.geometry("+%d+%d" % (self.origin[0] + dx, self.origin[1] + dy))

    def on_release(self, e):
        self.dragging = False
        moved = abs(e.x_root - self.press[0]) + abs(e.y_root - self.press[1])
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
            print("launch failed:", e, file=sys.stderr)

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

        sliders = [
            ("Line thickness", "thickness", 1, 12, 0),
            ("Spacing between lines", "spacing", 0, 30, 0),
            ("Padding from edge", "padding", 0, 30, 0),
            ("Background opacity", "alpha", 0.15, 1.0, 2),
            ("Distance from screen edge", "edge_gap", 0, 100, 0),
        ]
        for row, (label, key, lo, hi, places) in enumerate(sliders):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            var = tk.DoubleVar(value=float(self.s[key]))
            ttk.Scale(frame, from_=lo, to=hi, variable=var, length=170).grid(
                row=row, column=1, padx=8
            )
            readout = ttk.Label(frame, width=5)
            readout.grid(row=row, column=2, sticky="e")

            def update(*_, v=var, lbl=readout, pl=places, k=key):
                value = round(v.get(), pl) if pl else int(v.get())
                lbl.configure(text=("%.*f" % (pl, value)))
                self.apply_live(k, value)

            var.trace_add("write", update)
            update()

        row = len(sliders)
        startup = tk.BooleanVar(value=self.s["start_on_login"])
        ttk.Checkbutton(frame, text="Open on startup", variable=startup).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(8, 3)
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
            if startup.get() != self.s["start_on_login"]:
                try:
                    set_start_on_login(startup.get())
                    self.s["start_on_login"] = startup.get()
                except OSError as e:
                    print("startup registry write failed:", e, file=sys.stderr)
            save_settings(self.s)
            win.destroy()

        def cancel():
            self.s.update(before)
            self.root.attributes("-alpha", self.s["alpha"])
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

    # tray icon buffer: 16x16 pixels, 4 bytes each
    bits = _bar_icon_bits()
    assert len(bits) == 16 * 16 * 4
    assert any(bits[i + 3] for i in range(0, len(bits), 4)), "icon fully transparent"

    # easing: anchored at both ends, monotonic, and front-loaded
    assert ease_out(0) == 0 and ease_out(1) == 1
    prev = -1
    for i in range(21):
        v = ease_out(i / 20)
        assert v > prev
        prev = v
    assert ease_out(0.5) > 0.5
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--quit" in sys.argv:
        print("closed" if signal_running_widget(WM_CLOSE) else "not running")
    elif "--reset" in sys.argv:
        print("recalled" if signal_running_widget(WM_RESET_POSITION) else "not running")
    elif not single_instance():
        # Already running: recall it, in case it was launched again because it
        # couldn't be found on screen.
        signal_running_widget(WM_RESET_POSITION)
        sys.exit(0)
    else:
        Widget().run()
