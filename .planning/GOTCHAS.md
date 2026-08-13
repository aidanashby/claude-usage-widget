# Gotchas

## The desktop app and Claude Code are both `claude.exe`

Matching processes by name alone finds both, and on a working machine there may be a dozen: the
desktop app is Electron and runs many helper processes under one name. Anything that *closes*
Claude has to identify the desktop app by install location (`WindowsApps`, `AnthropicClaude`,
`Programs\Claude`) via `QueryFullProcessImageNameW`, or it can reach live CLI sessions. A process
whose path can't be read is never claimed as the desktop app — see `is_desktop_app`.

Every one of these cost real debugging time. Several produced no error message at all.

## Never `print()` an error — use `log()`

Under `pythonw.exe` with no console, `sys.stdout` and `sys.stderr` are **`None`**. A
`print(..., file=sys.stderr)` inside an `except` block raises `AttributeError` *from within the
handler*, turning a handled error into a fatal one.

This is what made "doesn't start on login" invisible: the app died silently with nothing
anywhere. Errors go to `widget.log` via `log()`, which is written to never raise.

**Corollary:** test with `pythonw`, not `python`. From a shell, `pythonw` inherits pipes and the
streams are real, which hides the bug. To reproduce login conditions:

```bash
powershell -Command "Start-Process pythonw.exe -ArgumentList (Resolve-Path widget.pyw) -WindowStyle Hidden"
```

## Never call Tk from the tray window procedure

`TrayIcon._wndproc` runs inside a ctypes callback, inside `DispatchMessageW`, inside a Tk
`after` callback. Tk is not re-entrant at that depth. Creating a `Toplevel` there aborts the
process via `Tcl_Panic` — a **CRT abort with no Python traceback**, which surfaces only as a
`BEX64` entry in Event Viewer.

The procedure appends an action name to `self.pending` and returns. `_pump` runs it afterwards,
back in clean Tk context. Keep it that way.

Diagnosing this needed Windows Error Reporting, not the log:
**Event Viewer → Windows Logs → Application**, filtered for the process name.

## Declare `argtypes` on every Win32 call

64-bit handles routinely exceed 32 bits. An undeclared ctypes call raises
`OverflowError: int too long to convert`. This silently discarded a correctly built tray icon —
`CreateIconIndirect` succeeded, then `DeleteObject` threw and the fallback stock icon was used
instead, which looked like "the icon is sometimes wrong".

All declarations live in `_declare_win32()`. Add yours there.

## `MONITOR_DEFAULTTONEAREST` never returns null

That's the point of it, but it means you cannot use it to ask "is this position on a real
monitor?" — an off-screen point at (-30000, -30000) resolves to a perfectly valid monitor rect.
Use `MONITOR_DEFAULTTONULL` (flag `0`) for visibility tests; `point_on_monitor()` does.

This is why the widget used to vanish when a monitor was unplugged.

## `winfo_x()` reads 0 until Tk maps the window

A visibility check made straight after `geometry()` tests the wrong point and passes by
accident. `place_initial()` therefore vets the *saved coordinates* rather than asking the window
where it landed.

## A failing `--selftest` used to exit silently

Running a `.pyw` suppresses stderr, so an assertion failure produced exit code 1 and **no
output**. A broken test was indistinguishable from a passing one. The entry point now catches
and prints to stdout. If you change that block, verify a deliberately broken copy still reports.

## Daemon threads and interpreter shutdown

A daemon thread parked in `time.sleep` wakes during finalization to find the GIL gone and kills
the process with a fatal error. `poll_loop` waits on a `threading.Event` that `quit()` sets.

## `%` in Tk widget text

Widget text is a plain string, not a format string. `"80%% and 95%%"` renders both signs
literally. Use single `%`.

## PyInstaller won't take a `.pyw` entry point

`build.py` copies `widget.pyw` to a temporary `_entry.py` and freezes that. Don't rename the
source to work around it.

## Frozen builds and paths

Inside a frozen build `__file__` points into the bundle, not at anyone's checkout. So:

- `app_dir()` uses `sys.executable` when `sys.frozen` is set.
- `set_start_on_login()` must register the exe, not `pythonw` plus a script that isn't there.
- Settings migration only fires when running from source, which is correct — a stranger's
  machine has nothing to migrate. Someone moving from source to exe should run the source
  version once first, which lands their settings in `%APPDATA%` where the exe will find them.

## The usage endpoint rate-limits

`/api/oauth/usage` returns 429 more readily than you'd expect. Polling every 60 seconds got
roughly one request in three rejected — which is what made usage appear to stop updating.
Five minutes plus exponential backoff plus jitter. Don't lower it.
