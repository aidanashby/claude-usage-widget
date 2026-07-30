# Architecture

Everything lives in `widget.pyw`. `build.py` packages it; nothing else is code.

## Why one file

Two reasons, both deliberate. It reads an OAuth token, so being auditable in a single pass
matters more than tidy module boundaries. And it's small enough that splitting it would add
navigation cost without reducing complexity. If it ever passes ~3,000 lines, revisit — the
natural seam is `win32.py` (tray, monitors, click-through, registry) against everything else.

## Layout of the file, top to bottom

1. **Constants and `DEFAULTS`** — every setting has a default here. `load_settings()` merges the
   file over this dict, so adding a key is backwards-compatible automatically and older settings
   files keep working.
2. **Paths** — `app_dir()` / `data_dir()`. Portable marker beats `%APPDATA%`; `%APPDATA%` beats
   sitting beside the program. `migrate_settings()` handles pre-1.0 files.
3. **Logging** — `log()` and `log_exception()`. See GOTCHAS: never use `print()` for errors.
4. **Pure functions** — time formatting, window progress, backoff, alert thresholds, burn-rate
   projection, geometry, versions, icon bytes. **This is where new logic should go.** They have
   no Tk and no Win32 dependency, so `--selftest` can cover them properly.
5. **Networking** — `fetch_usage()` and `fetch_latest_version()`. The only two `urlopen` calls in
   the program; SECURITY.md makes promises about this, so adding a third means updating that doc.
6. **Win32 plumbing** — `_declare_win32()`, icon creation, `TrayIcon`.
7. **`Tooltip`** — one borderless Toplevel, rebuilt each time it's shown.
8. **`Widget`** — the Tk window, drawing, polling, settings UI, welcome screen.
9. **`selftest()`** and the entry point.

## Threading

One background thread, `poll_loop`. It never touches Tk directly — results come back via
`root.after(0, ...)`, which is the only safe way. It waits on a `threading.Event` rather than
sleeping, so shutdown is clean (see GOTCHAS).

Everything else runs on the Tk thread, including the tray message pump, which is driven by a
recurring `root.after`.

## Drawing

`draw()` expresses every rectangle in **along/across** terms — distance along the bar's long
axis, and its thickness — and `bar_rect()` converts that to canvas coordinates exactly once.
This is why horizontal and vertical share one code path, and why the marker's contrast rule
(`along < fill`) is orientation-free. Resist adding orientation branches back into `draw()`.

## Timers

| Interval | What |
|----------|------|
| 5 min | Usage poll (backs off on failure, up to 30 min) |
| 30 s | Marker redraw, from cached reset times — no network |
| 2 s | Off-screen watchdog |
| 50 ms | Tray message pump |
| 24 h | Update check, on the poll thread |

The split between polling and redrawing matters: markers stay smooth while the network is left
alone. Don't collapse them.

## State

`settings.json` holds preferences *and* cache — last known percentages, reset times, window
position, which alerts have fired. Caching reset times is what lets the markers and tooltip keep
working while the bars are grey, since a reset time is a wall-clock fact that doesn't need the
API to stay true.

## Testing

`python widget.pyw --selftest` — pure functions only, no GUI, no credentials, runs in CI.

The GUI is verified by *inspecting the rendered canvas* rather than by screenshots: instantiate
`Widget`, call `draw()`, read back `canvas.coords()` and `itemcget(..., 'fill')`. That catches
real geometry and colour bugs cheaply and is how both orientations and the marker contrast rule
were confirmed.

When you add pure logic, add a case that would **fail** if the logic were wrong. The bottom-up
vertical fill has a mutation-tested assertion behind it for exactly this reason.
