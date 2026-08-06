# Changelog

All notable changes to this project are documented here. Versions follow
[semantic versioning](https://semver.org/), loosely — this is a single-file desktop widget.

## [1.0.3] — 2026-08-06

### Changed

- The hover tooltip's third line no longer projects a limit that's already spent. At 100% it
  reported "session limit reached by" the current time, which was both obvious and wrong —
  it now says when the widget first saw 100%, e.g. "Session limit reached at 9:15am". The
  reset time stays on the line that already carried it, so nothing is said twice.

## [1.0.2] — 2026-08-05

### Changed

- The **contrast** theme's bar is now amber rather than a bright lemon yellow — still high
  contrast against black, easier to look at, and no longer close to the grey the bar goes
  when the widget can't read your usage.
- The **monochrome** theme is now straight black and white: a white bar on a black panel.

## [1.0.1] — 2026-07-30

### Fixed

- A mouse release with no press behind it — press elsewhere and let go over the widget, or have
  the window appear under the cursor mid-click — raised `AttributeError` on a missing drag
  anchor. Latent since the first release; found by running the actual published zip rather than
  a local build, and caught by the error log rather than by crashing.

## [1.0.0] — 2026-07-30

Makes the widget installable by people who don't have Python.

### Added

- **A downloadable Windows build.** A zip on Releases containing a standalone
  `ClaudeUsageWidget.exe` — no Python, no installer. Built by GitHub Actions from a tagged
  commit with a provenance attestation and a published SHA-256, so an unsigned build can still
  be verified against its source.
- **A Scoop manifest**, for installing and updating from the command line.
- **An update check**, once a day against the GitHub releases API. It tells you and adds a tray
  menu item; it never downloads or replaces anything. Switchable off, and documented in
  SECURITY.md, which now names both addresses the widget contacts.
- **Portable mode** — a `portable.txt` file beside the program keeps settings local.
- **CI**: the self-test runs on every push and pull request.

### Changed

- **Settings and the log moved to `%APPDATA%\ClaudeUsageWidget`.** An installed program can't
  rely on being able to write beside itself. An existing `settings.json` next to the script is
  migrated automatically the first time, leaving the original untouched.
- The startup registry entry points at the executable when running a packaged build, rather
  than at `pythonw.exe` and a script that isn't there.

## [0.10.0] — 2026-07-30

The first release aimed at people other than its author. Everything here is about being usable,
trustworthy and well-behaved for someone who didn't write it.

### Added

- **Warnings at 80% and 95%** of each limit, as tray notifications, once per threshold per
  window. On by default, and switchable off.
- **A welcome window on first run**, explaining the two bars and pointing out the tray icon,
  which is otherwise undiscoverable. Shown once.
- **Colour presets** — `claude`, `monochrome` and `contrast`.
- **A line length setting**, applying to both bars. It can be dragged up to the full width of
  your screen, or the full height minus the taskbar when vertical.
- **"What is this?" in the tray menu**, which reopens the welcome screen at any time.
- **Click-through**, so the mouse reaches whatever is underneath. Note that this also disables
  the hover tooltip and dragging, since no mouse events reach the widget at all; the tray takes
  over. Stated in the settings window as well as here.
- **A burn-rate line in the tooltip**: "At this rate: session limit reached by 4:12pm", or "On
  pace" when both limits are tracking to last their windows.
- **`SECURITY.md`** — what it reads, the single address it talks to, what it never does, and a
  one-line command to verify that for yourself.
- **A non-affiliation notice**, and a plain-language explanation of what the widget is at the
  top of the README.

### Changed

- Times landing exactly on the hour lose the redundant minutes: "4am", not "4:00am".
- **Failed polls now back off** — doubling to a thirty-minute ceiling, honouring `Retry-After`,
  with jitter so that many installations don't retry in the same instant. Previously a failing
  poll simply retried on the same fixed schedule, which is not a reasonable thing to do to an
  endpoint from thousands of machines.

### Fixed

- The alerts checkbox showed "80%% and 95%%" — a literal string carrying escapes it never needed.
- A failing `--selftest` exited silently: running a `.pyw` suppresses stderr, so the traceback
  went nowhere and only the exit code betrayed it. Failures now report on stdout.

## [0.9.0] — 2026-07-30

### Added

- **Vertical layout** setting, off by default. Stands the widget on end as a tall strip, which
  suits a left or right screen edge. The bars sit side by side and fill upward like a gauge,
  session on the left. The hover tooltip moves to the side of the widget rather than below it,
  flipping to whichever side has room.

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

[1.0.1]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v1.0.1
[1.0.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v1.0.0
[0.10.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.10.0
[0.9.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.9.0
[0.8.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.8.0
[0.7.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.7.0
[0.6.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.6.0
[0.5.0]: https://github.com/aidanashby/claude-usage-widget/releases/tag/v0.5.0
