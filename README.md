# Claude Usage Widget

**It gives you two bars.**

Claude limits how much you can use it — one limit that resets every five hours, and another
that resets weekly. Normally you can only check those by asking inside Claude, which means
finding out you're nearly out of usage at the worst possible moment.

This puts both limits on your screen permanently, as two thin bars in a corner:

- The **top bar** fills up as you use your current five-hour session.
- The **bottom bar** fills up as you use your week.

That's the whole idea. No numbers, no labels, no window to manage — just two bars you glance at
while you work. Hover over them if you want the details.

It's about 130 pixels wide and 20 tall, sits on top of your other windows, and stays out of the
way.

> **Not affiliated with Anthropic.** This is an unofficial personal project. It isn't made,
> endorsed, sponsored, or supported by Anthropic, and "Claude" is their trademark, used here
> only to describe what the tool shows you.

## What the bars mean

| Bar | Limit |
|-----|-------|
| Top | **Session** — your rolling 5-hour usage window |
| Bottom | **Weekly** — your 7-day usage window |

Turning on **Vertical layout** in the settings stands the widget on end, which suits parking it
against a left or right screen edge. The bars then sit side by side and fill upward like a
gauge, with session on the left.

Bar length is percentage of that limit consumed. Orange (`#d17552`) means the reading is live.
Grey means usage couldn't be read just now, and the bars are showing the last known values.
Hover to see why, and click for the detail and a way to fix it.

### The vertical marker

Each bar carries a thin vertical line showing how far through *that window* you are — a fifth
of the way along the top bar means an hour into your five-hour session. Comparing the two tells
you whether you're on pace: bar well ahead of the marker means you're burning the limit faster
than the clock.

The marker is white on the empty track and turns black where it crosses the used portion, so it
stays visible either way. Window positions come from the reset times the API reports for your
account, not from an assumed schedule.

### Hover for reset times

Hovering anywhere on the widget spells it out:

```
Current session: resets in 31 min
Weekly limit: resets Sun 8:45am
At this rate: session limit reached by 4:12pm
```

The third line projects forward from how fast you're currently spending. It says "On pace" when
both limits are tracking to last their windows. Once a limit is actually spent there's nothing
left to project, so it tells you when you hit it instead:

```
Session limit reached at 9:15am
```

That's the time the widget first saw 100%, so it only knows if it was running at the time. The
reset times stay on the first two lines either way.

The session is a countdown because it's usually close; the weekly is a wall-clock time because
a countdown in days isn't much use. Both keep working while the bars are grey — a reset time
stays true whether or not the API is reachable.

## Install

You need Windows, and Claude installed and signed in — either the desktop app or the Claude
Code CLI, since both share the same stored credentials.

### Download it

Get the zip from [Releases](https://github.com/aidanashby/claude-usage-widget/releases),
unpack it anywhere, and run `ClaudeUsageWidget.exe`. No Python needed, no installer, nothing
written outside your own profile.

**Windows will warn you the first time.** The build isn't code-signed — certificates cost money
and this is a free personal project — so SmartScreen shows "Windows protected your PC". Click
**More info → Run anyway** if you're happy to.

You don't have to take that on faith. Every release is built in public by GitHub Actions from a
tagged commit, with a provenance attestation, so you can confirm the zip really came from this
source:

```bash
gh attestation verify ClaudeUsageWidget-v1.0.1-win64.zip --repo aidanashby/claude-usage-widget
```

A `.sha256` is published alongside each zip too.

### Or with Scoop

```bash
scoop install https://raw.githubusercontent.com/aidanashby/claude-usage-widget/main/scoop/claude-usage-widget.json
```

### Or run the source

One file, standard library only, no third-party packages. Needs Python 3.8+ with tkinter, which
the standard python.org installer includes.

```bash
git clone https://github.com/aidanashby/claude-usage-widget.git
cd claude-usage-widget
pythonw widget.pyw
```

Use `pythonw`, not `python` — that's what keeps a console window from appearing behind it.

### Where it keeps things

Settings and the log live in `%APPDATA%\ClaudeUsageWidget`. For a portable install — a USB
stick, or a synced folder — put a file named `portable.txt` beside the program and it keeps
everything local instead.

To have it start with Windows, open the settings and tick **Open on startup** (off by default).
That writes a `ClaudeUsageWidget` value to
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, and unticking removes it. The entry adds
a `--startup` flag, which makes the widget wait a few seconds for the desktop to finish loading
before it appears — tray icons registered too early are silently dropped by the shell.

## Using it

- **Drag** it anywhere. On release it glides to the nearest edge of whichever monitor it's on,
  with an ease-out animation. Its position is remembered between runs.
- **Left-click** opens settings — or, if the bars are grey, opens the diagnostics window
  explaining why and offering the fix (see below).
- **Right-click the widget** always opens settings, grey or not.
- **Quit** from the tray icon, or from the settings window.

Only one instance runs at a time. Launching a second copy doesn't start one — it recalls the
existing widget to the top-right of your primary monitor, which is useful if you've lost track
of it.

## Tray icon

The widget has no title bar and can end up somewhere awkward, so it also sits in the system
tray. That's always the way back to it.

- **Hover** — shows the actual percentages, which the bars deliberately don't display
- **Right-click** — Settings · Reset position · What is this? · Quit
- **Double-click** — opens settings

**Reset position** returns it to the top-right of your primary monitor. **What is this?**
reopens the welcome screen you saw on first run.

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

In Task Manager the packaged build appears as `ClaudeUsageWidget.exe`. Running from source it's
`pythonw.exe`; to tell it apart from other Python programs, switch to the **Details** tab,
right-click the column headers, choose **Select columns**, and enable **Command line** — the
widget's row shows `widget.pyw`.

## When something goes wrong

The widget writes to `widget.log` in `%APPDATA%\ClaudeUsageWidget` (or beside the program in
portable mode). It runs without a console and has no error output of its own, so the log is the
only place problems are recorded — check it first. An empty or missing log means nothing has
gone wrong.

If it vanishes without writing anything to the log, the failure was below Python: check
**Event Viewer → Windows Logs → Application** for an entry at that time.

## Settings

Changes preview live as you drag a slider. **Save** keeps them; **Cancel** (or closing the
window) puts everything back as it was.

| Setting | Default | Notes |
|---------|---------|-------|
| Line length | 120px | Up to your screen's width, or its height when vertical |
| Line thickness | 3px | Height of each bar |
| Spacing between lines | 5px | Gap between the two bars |
| Padding from edge | 6px | Panel padding around the bars |
| Background opacity | 0.7 | See the caveat below |
| Distance from screen edge | 12px | How far off the edge it parks |
| Colours | claude | `claude`, `monochrome`, or `contrast` |
| Vertical layout | off | Tall strip instead of a wide one |
| Warn me at 80% and 95% | on | Tray notification, once per threshold per window |
| Click-through | off | Mouse passes through — see the warning below |
| Check GitHub for updates | on | Daily; tells you, never installs |
| Open on startup | off | Registry `Run` entry |
| Launch command | auto-detected on first use | What a grey-state click runs |

Everything is written to `settings.json` in `%APPDATA%\ClaudeUsageWidget`, along with the last
known usage values and the widget's position. Delete that file to reset to defaults.

**Opacity caveat:** tkinter applies one alpha value to the entire window, so the bars fade
along with the panel — they aren't independently opaque. Getting true per-element opacity
would mean Win32 layered windows via ctypes, which wasn't worth the complexity. At the default
0.7 the orange still reads clearly.

**Click-through caveat:** when it's on, the widget ignores the mouse completely. Clicks reach
whatever is underneath, which is the point — but it also means you can't drag it, and the hover
tooltip can't appear, because no mouse events reach it at all. Everything moves to the tray
icon: settings, reset position, quit, and the percentages in its own tooltip.

## Warnings

By default you get a notification the first time you cross 80% and 95% of each limit, once per
window. Turn them off with **Warn me at 80% and 95%** in settings.

## Where the data comes from

The widget polls `GET https://api.anthropic.com/api/oauth/usage` every five minutes, reading
`five_hour` and `seven_day` from the response — the same numbers `/usage` shows you inside a
Claude session, plus each window's `resets_at`.

Five minutes rather than one: the endpoint rate-limits, and polling every minute got roughly
one request in three rejected. The markers don't need it either, since they're redrawn from
the cached reset times every 30 seconds without touching the network.

When a request does fail, the wait doubles each time up to a thirty-minute ceiling, honours a
`Retry-After` if the server sends one, and adds a little randomness so that many copies of this
running on many machines don't all retry in the same instant.

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

Grey means the last poll failed. **Hover** and the tooltip names the reason; **click** and you
get a window with the detail, when the last good reading was, when the next attempt is due, and
a button for whatever would actually help. Usually it's one of:

- the stored access token has expired
- you're offline
- no credentials could be found in any of the locations above — that file is written by Claude
  Code when you sign in, so having the desktop app open doesn't by itself create one
- the API is rate limiting, in which case nothing is wrong and nothing needs doing
- you're authenticated by API key or via Bedrock/Vertex rather than a Claude subscription, in
  which case there are no session or weekly limits to report

The widget deliberately does **not** refresh the token itself — racing Claude's own refresh can
invalidate its session. Starting Claude refreshes it properly, so that's what the window offers
when Claude isn't running. When it *is* running, it offers **Restart Claude** instead: an already
running app won't be helped by being started again. That asks for confirmation first, closes the
desktop app the polite way so unsaved work can prompt, and only forces it after five seconds.
Claude Code sessions in a terminal are never touched — the two share the name `claude.exe`, so
the widget tells them apart by where they're installed.

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
coordinates), the off-screen fallback position, credential discovery and token parsing, window
progress and the marker's contrast rule, the countdown and clock formatting, the tray icon's
pixel buffer, and the animation easing curve. The GUI and tray are checked by running it.

**Test with `pythonw`, not `python`.** Under `pythonw` with no console, `sys.stdout` and
`sys.stderr` are `None`, so anything that writes to them raises — including from inside an
exception handler, which turns a handled error into a fatal one. Bugs that only appear this way
cost a release to find. Launch it the way Windows does:

```bash
powershell -Command "Start-Process pythonw.exe -ArgumentList (Resolve-Path widget.pyw) -WindowStyle Hidden"
```

Use `log()` rather than `print()` for anything that needs to be seen.

Two more things worth knowing before touching the tray code. Every Win32 call needs its
`argtypes`/`restype` declared in `_declare_win32()` — handles routinely exceed 32 bits and an
undeclared call raises `OverflowError` on 64-bit Python. And the window procedure must never
call into Tk: it runs inside a ctypes callback nested in Tk's own event loop, and Tk isn't
re-entrant, so doing so aborts the process with no Python traceback. Queue the action and let
`_pump` run it.

The whole thing is one file, `widget.pyw`. `build.py` packages it with PyInstaller; CI runs the
self-test on every push and builds a release on every `v*` tag. Release history is in
[CHANGELOG.md](CHANGELOG.md).

Before changing anything, read [`.planning/`](.planning/) — architecture, the decisions behind
choices that look arbitrary, a roadmap, and a list of gotchas that each cost real debugging
time. [`.planning/GOTCHAS.md`](.planning/GOTCHAS.md) in particular will save you an afternoon
if you go near the tray or anything Win32.

## Security and privacy

It reads the token Claude already stores on your machine and sends one request to one Anthropic
address. No telemetry, no analytics, no third-party network access. Full detail, and how to
verify it yourself in one command, is in [SECURITY.md](SECURITY.md).

## Licence

MIT — see [LICENSE](LICENSE).

Not affiliated with, endorsed by, or sponsored by Anthropic.
