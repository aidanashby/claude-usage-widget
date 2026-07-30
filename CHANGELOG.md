# Changelog

All notable changes to this project are documented here. Versions follow
[semantic versioning](https://semver.org/), loosely — this is a single-file desktop widget.

## [0.8.0] — 2026-07-30

Shows how far through each limit window you are, not just how much you've spent.

### Added

- **Window progress marker.** A 1px vertical line in each bar showing elapsed time through that
  window — white on the empty track, black where it crosses the used portion. Positions come
  from the `resets_at` the API reports for your account, so they reflect your real windows
  rather than an assumed schedule. Redrawn every 30 seconds from cached times, no network
  needed.
- **Hover tooltip** over the whole widget, giving both reset times: the session as a countdown
  (`resets in 31 min`), the week as a wall-clock time (`resets Sun 8:45am`). Works while the
  bars are grey, since a reset time stays true without the API.

### Changed

- **Polling moved from every 60 seconds to every 5 minutes.** The endpoint rate-limits, and at
  one-minute intervals roughly one request in three came back `429` — which is what made usage
  appear to stop updating. The markers don't need frequent polling, as they run off cached
  reset times.

### Fixed

- Being rate limited no longer reports itself as "click the widget to start Claude". The tray
  tooltip now distinguishes rate limiting, rejected credentials, missing credentials and
  network failures. Bars still go grey in every case.

## [0.7.0] — 2026-07-30

Adds a system tray icon, makes the widget recover from monitor layout changes, and fixes three
faults found in testing.

### Added

- **System tray icon.** Right-click for Settings · Reset position · Quit; double-click opens
  settings; hover shows the actual session and weekly percentages, which the bars deliberately
  don't display. The widget has no title bar, so this is the reliable way back to it.
- **`--quit` and `--reset`** command-line flags, acting on the running widget and reporting
  `not running` if there isn't one.
- **`widget.log`**, written beside the script. The widget runs under `pythonw.exe`, which has
  no error output of its own, so this is the only place problems are recorded.
- Launching a second copy now recalls the running widget to the primary monitor's top-right
  instead of exiting silently.

### Fixed

- **The widget could disappear when monitor layouts changed.** Its saved position was trusted
  unconditionally, and the monitor lookup used `MONITOR_DEFAULTTONEAREST`, which never reports
  "nowhere" — so a position on a monitor that no longer existed resolved to a valid rectangle
  and nothing could detect the window was off-screen. Position is now checked against
  `MONITOR_DEFAULTTONULL` at startup and on a two-second watchdog, falling back to the primary
  monitor's top-right.
- **Tray menu items crashed the process.** The window procedure called Tk directly from inside
  a ctypes callback nested in `DispatchMessageW`, inside a Tk `after` callback. Tk isn't
  re-entrant there, and the result was a CRT abort with no Python traceback. The procedure now
  only records what happened; the message pump performs the work once it has returned.
- **Errors were invisible and often fatal.** Every error path printed to `sys.stderr`, which is
  `None` under `pythonw` with no console — so each handler raised `AttributeError` and turned a
  handled error into a fatal one. Errors now go to `widget.log`, with `sys.excepthook` and Tk's
  callback hook routed there too.
- **The tray sometimes showed the generic Python icon.** The gdi32 calls had no `argtypes`, so
  64-bit GDI handles overflowed and `DeleteObject` discarded an icon that had been built
  correctly. The icon now comes from a DIB section sized to `SM_CXSMICON`, rather than a
  32bpp device-dependent bitmap.
- **Start on login didn't work.** The registry entry was correct, but the app died on launch
  for the reasons above. The entry now also carries a `--startup` flag that waits for the shell
  before appearing, and the widget re-registers its tray icon on the shell's `TaskbarCreated`
  broadcast, so it survives Explorer restarting. Entries written by earlier versions are
  rewritten automatically.
- **The process aborted at shutdown.** A daemon thread parked in `time.sleep` woke during
  interpreter finalization to find the GIL gone. It now waits on an event that `quit()` sets.

## [0.6.0] — 2026-07-29

Makes the widget work regardless of how Claude is installed.

### Fixed

- Credentials are looked for in `%CLAUDE_CONFIG_DIR%`, then
  `%USERPROFILE%\.claude\.credentials.json`, then Windows Credential Manager — enumerated and
  matched rather than looked up by a guessed target name. An expired token is treated as absent
  rather than spending a request to be told 401.
- Claude is launched via its Start Menu AppUserModelID, which is the only way to start the
  Microsoft Store / MSIX build: its executable lives under the permission-locked `WindowsApps`
  directory at a version-stamped path. `%LOCALAPPDATA%` locations and the CLI remain as
  fallbacks, resolved lazily so startup isn't delayed.
- No assumption of a `~/Projects` directory anywhere in the code or documentation.

## [0.5.0] — 2026-07-28

First release. Two thin bars showing Claude session (rolling 5-hour) and weekly usage.

- Claude orange bars on a semi-transparent black panel, always on top, no labels
- Reads usage directly from the OAuth usage endpoint, so Claude needn't be running
- Drag anywhere; snaps to the nearest edge of the current monitor with an ease-out glide
- Settings preview live while dragging a slider; settings and position persist between runs
- Bars grey out when usage can't be read, keeping the last known values; clicking then launches
  Claude to refresh the token
- Single instance only

[0.8.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.8.0
[0.7.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.7.0
[0.6.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.6.0
[0.5.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.5.0
