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
- Claude Code installed and signed in

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
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, and unticking removes it.

## Using it

- **Drag** it anywhere. On release it glides to the nearest edge of whichever monitor it's on,
  with an ease-out animation. Its position is remembered between runs.
- **Left-click** opens settings — or, if the bars are grey, runs the launch command instead
  (see below).
- **Right-click** always opens settings, grey or not.
- **Quit** from the settings window. There's no tray icon and no title bar, so that's the way out.

Only one instance can run at a time. Launching a second one exits silently rather than stacking
a duplicate on top of the first.

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
| Launch command | auto-detected | What a grey-state click runs |

Everything is written to `settings.json` beside the script, along with the last known usage
values and the widget's position. Delete that file to reset to defaults.

**Opacity caveat:** tkinter applies one alpha value to the entire window, so the bars fade
along with the panel — they aren't independently opaque. Getting true per-element opacity
would mean Win32 layered windows via ctypes, which wasn't worth the complexity. At the default
0.7 the orange still reads clearly.

## Where the data comes from

The widget polls `GET https://api.anthropic.com/api/oauth/usage` every 60 seconds. It
authenticates with the OAuth access token Claude Code already stores locally in
`~/.claude/.credentials.json`, reading `five_hour.utilization` and `seven_day.utilization` from
the response — the same numbers `/usage` shows you inside a Claude session.

Claude does **not** need to be running for this to work.

The token is read from disk, sent to Anthropic, and never logged, displayed, or stored anywhere
by the widget.

### Why it goes grey

Grey means the last poll failed. Usually one of:

- the stored access token has expired
- you're offline
- `~/.claude/.credentials.json` is missing or unreadable

The widget deliberately does **not** refresh the token itself — racing Claude Code's own refresh
can invalidate its session. Instead, starting Claude refreshes the token, so a grey-state click
runs the launch command, and the bars return to orange on the next poll.

The launch command defaults to opening Windows Terminal in `~/Projects` running `claude`. If
you'd rather it opened the Claude desktop app, paste that path into the settings field.

## Caveats

- **Windows only.** The registry startup entry, monitor detection, and single-instance mutex
  are all Win32.
- The endpoint it uses is Claude Code's internal usage API, not a documented public one. It
  could change without warning; if it does, the bars go grey rather than showing wrong numbers.
- It won't draw over full-screen exclusive applications (games, mostly). That's a Windows
  always-on-top limitation.
- Snapping uses the monitor's *work area*, so it respects the taskbar.

## Development

```bash
python widget.pyw --selftest
```

Covers the edge-snapping geometry (including secondary monitors and monitors at negative
coordinates) and the animation easing curve. The GUI itself is checked by running it.

The whole thing is one file, `widget.pyw`, at around 350 lines.

## Licence

MIT — see [LICENSE](LICENSE).
