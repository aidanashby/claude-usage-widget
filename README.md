# Claude Usage Widget

A small always-on-top desktop widget for Windows showing how much of your Claude usage limits
you've spent: two thin bars, session and weekly, and nothing else.

No labels, no numbers, no window chrome. It sits in a corner of your screen and you glance at it.

## What the bars mean

| Bar | Limit |
|-----|-------|
| Top | **Session** — your rolling 5-hour usage window |
| Bottom | **Weekly** — your 7-day usage window |

Bar length is percentage of that limit consumed. Orange (`#d17552`) means the reading is live.
Grey means usage couldn't be read just now, and the bars are showing the last known values.

## Requirements

- Windows
- Python 3.8+ (tkinter included — it ships with the standard python.org installer)
- Claude installed and signed in — either the desktop app or the Claude Code CLI, since both
  share the same stored credentials

No third-party packages. Everything used is standard library.

## Install and run

```bash
git clone https://github.com/aidanashby/claude-usage-widget.git
cd claude-usage-widget
pythonw widget.pyw
```

Use `pythonw`, not `python` — that's what keeps a console window from appearing behind it.

To have it start with Windows, open the settings and tick **Open on startup** (off by default).
That writes a `ClaudeUsageWidget` value to
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, and unticking removes it. The entry adds
a `--startup` flag, which makes the widget wait a few seconds for the desktop to finish loading
before it appears — tray icons registered too early are silently dropped by the shell.

## Using it

- **Drag** it anywhere. On release it glides to the nearest edge of whichever monitor it's on,
  with an ease-out animation. Its position is remembered between runs.
- **Left-click** opens settings — or, if the bars are grey, runs the launch command instead
  (see below).
- **Right-click** always opens settings, grey or not.
- **Quit** from the tray icon, or from the settings window.

Only one instance runs at a time. Launching a second copy doesn't start one — it recalls the
existing widget to the top-right of your primary monitor, which is useful if you've lost track
of it.

## Tray icon

The widget has no title bar and can end up somewhere awkward, so it also sits in the system
tray. That's always the way back to it.

- **Hover** — shows the actual percentages, which the bars deliberately don't display
- **Right-click** — Settings · Reset position · Quit
- **Double-click** — opens settings

**Reset position** returns it to the top-right of your primary monitor.

## If it goes missing

It shouldn't any more. The widget checks its saved position against the monitors that actually
exist, both at startup and every two seconds while running, and recalls itself to the primary
monitor's top-right whenever it would otherwise be stranded off-screen. That covers unplugging
an external monitor, changing display settings, and starting up with a different monitor
arrangement than last time.

If you ever need to reach it from a script or a terminal:

```bash
pythonw widget.pyw --reset
pythonw widget.pyw --quit
```

Both act on the running widget and report `not running` if there isn't one.

In Task Manager the process appears as `pythonw.exe`. To tell it apart from other Python
programs, switch to the **Details** tab, right-click the column headers, choose **Select
columns**, and enable **Command line** — the widget's row shows `widget.pyw`.

## When something goes wrong

The widget writes to `widget.log` beside the script. It runs under `pythonw.exe`, which has no
console and no error output of its own, so the log is the only place problems are recorded —
check it first. An empty or missing log means nothing has gone wrong.

If the widget vanishes without writing anything to the log, the failure was below Python: check
**Event Viewer → Windows Logs → Application** for a `pythonw.exe` entry at that time.

## Settings

Changes preview live as you drag a slider. **Save** keeps them; **Cancel** (or closing the
window) puts everything back as it was.

| Setting | Default | Notes |
|---------|---------|-------|
| Line thickness | 3px | Height of each bar |
| Spacing between lines | 5px | Gap between the two bars |
| Padding from edge | 6px | Panel padding around the bars |
| Background opacity | 0.7 | See the caveat below |
| Distance from screen edge | 12px | How far off the edge it parks |
| Open on startup | off | Registry `Run` entry |
| Launch command | auto-detected on first use | What a grey-state click runs |

Everything is written to `settings.json` beside the script, along with the last known usage
values and the widget's position. Delete that file to reset to defaults.

**Opacity caveat:** tkinter applies one alpha value to the entire window, so the bars fade
along with the panel — they aren't independently opaque. Getting true per-element opacity
would mean Win32 layered windows via ctypes, which wasn't worth the complexity. At the default
0.7 the orange still reads clearly.

## Where the data comes from

The widget polls `GET https://api.anthropic.com/api/oauth/usage` every 60 seconds, reading
`five_hour.utilization` and `seven_day.utilization` from the response — the same numbers
`/usage` shows you inside a Claude session.

Claude does **not** need to be running for this to work.

It authenticates with the OAuth access token Claude already stores locally, looking in each of
these in turn:

1. `%CLAUDE_CONFIG_DIR%\.credentials.json`, if you've relocated your config directory
2. `%USERPROFILE%\.claude\.credentials.json` — the usual place
3. Windows Credential Manager, for setups that keep credentials there instead of on disk

The token is read locally, sent only to Anthropic, and never logged, displayed, or written
anywhere by the widget. If the stored token has already expired, the widget doesn't bother
sending it — it goes grey instead.

### Why it goes grey

Grey means the last poll failed. Usually one of:

- the stored access token has expired
- you're offline
- no credentials could be found in any of the locations above
- you're authenticated by API key or via Bedrock/Vertex rather than a Claude subscription, in
  which case there are no session or weekly limits to report

The widget deliberately does **not** refresh the token itself — racing Claude's own refresh can
invalidate its session. Instead, starting Claude refreshes the token, so a grey-state click runs
the launch command, and the bars return to orange on the next poll.

### The launch command

Worked out automatically the first time it's needed, then remembered:

1. Your Start Menu entry for Claude, launched by its AppUserModelID. This covers the Microsoft
   Store / MSIX build — whose executable lives under the permission-locked `WindowsApps`
   directory and can't be run directly — as well as ordinary installers.
2. Common install locations under `%LOCALAPPDATA%`, for older desktop builds.
3. `cmd /k claude`, if the Claude Code CLI is on your `PATH`.

If none of those find it, or you'd rather it opened something else, type your own command into
the settings field and it'll be used as-is.

## Caveats

- **Windows only.** The registry startup entry, monitor detection, and single-instance mutex
  are all Win32.
- The endpoint it uses is Claude Code's internal usage API, not a documented public one. It
  could change without warning; if it does, the bars go grey rather than showing wrong numbers.
- It won't draw over full-screen exclusive applications (games, mostly). That's a Windows
  always-on-top limitation.
- Snapping uses the monitor's *work area*, so it respects the taskbar.
- Tk runs DPI-virtualised, so on setups that mix monitors at different scaling factors the
  widget may sit a few pixels off where you'd expect. It stays on screen and reachable; it's
  just not pixel-exact.

## Development

```bash
python widget.pyw --selftest
```

Covers the edge-snapping geometry (including secondary monitors and monitors at negative
coordinates), the off-screen fallback position, credential discovery and token parsing, the
tray icon's pixel buffer, and the animation easing curve. The GUI and tray are checked by
running it.

The whole thing is one file, `widget.pyw`.

## Licence

MIT — see [LICENSE](LICENSE).
