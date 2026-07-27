"""Always-on-top Claude usage widget: session + weekly limit bars."""
__version__ = "0.5.0"

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")
CREDS_PATH = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

ORANGE = "#d17552"
GREY = "#7a7a7a"
TRACK = "#3a3a3a"
BAR_LENGTH = 120
POLL_SECONDS = 60
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "ClaudeUsageWidget"

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
    if not s["launch_cmd"]:
        s["launch_cmd"] = detect_launch_cmd()
    return s


def save_settings(s):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError as e:
        print("could not save settings:", e, file=sys.stderr)


def detect_launch_cmd():
    """Best guess at how to start Claude. Editable in settings."""
    local = os.environ.get("LOCALAPPDATA", "")
    for path in (
        os.path.join(local, "AnthropicClaude", "claude.exe"),
        os.path.join(local, "Programs", "Claude", "Claude.exe"),
        os.path.join(local, "Claude", "Claude.exe"),
    ):
        if os.path.exists(path):
            return path
    projects = os.path.join(os.path.expanduser("~"), "Projects")
    return 'wt.exe -d "%s" cmd /k claude' % projects


def fetch_usage():
    """Return (session_pct, weekly_pct), or None if usage can't be read.

    Uses the OAuth token Claude Code already stores. Deliberately does not
    refresh it -- racing Claude Code's own refresh can invalidate its session.
    Launching Claude is the refresh path.
    """
    try:
        with open(CREDS_PATH, encoding="utf-8") as f:
            token = json.load(f)["claudeAiOauth"]["accessToken"]
    except (OSError, ValueError, KeyError):
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


class Widget:
    def __init__(self):
        self.s = load_settings()
        self.session = self.s["last_session"]
        self.weekly = self.s["last_weekly"]
        self.live = False
        self.anim = None
        self.edge = self.s["edge"]

        self.root = tk.Tk()
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

    def place_initial(self):
        pos = self.s["pos"]
        if not pos:
            left, top, right, _ = self.current_rect(0, 0)
            gap = self.s["edge_gap"]
            pos = [right - self.w - gap, top + gap]
        self.root.geometry("+%d+%d" % (pos[0], pos[1]))

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
        while True:
            result = fetch_usage()
            self.root.after(0, self.apply_usage, result)
            time.sleep(POLL_SECONDS)

    def apply_usage(self, result):
        self.live = result is not None
        if result:
            self.session, self.weekly = result
            self.s["last_session"], self.s["last_weekly"] = result
            save_settings(self.s)
        self.draw()

    # --- drag / snap ---

    def on_press(self, e):
        self.press = (e.x_root, e.y_root)
        self.origin = (self.root.winfo_x(), self.root.winfo_y())

    def on_drag(self, e):
        dx = e.x_root - self.press[0]
        dy = e.y_root - self.press[1]
        self.root.geometry("+%d+%d" % (self.origin[0] + dx, self.origin[1] + dy))

    def on_release(self, e):
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

    def launch_claude(self):
        cmd = self.s["launch_cmd"]
        if not cmd:
            return
        try:
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
        launch = tk.StringVar(value=self.s["launch_cmd"])
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
        ttk.Button(buttons, text="Quit widget", command=self.root.destroy).pack(
            side="left"
        )
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
    elif not single_instance():
        sys.exit(0)  # already running
    else:
        Widget().run()
