# Plan — diagnosing a disconnected widget

Grey bars currently say nothing about why. `fetch_usage` already works out a specific reason
and `apply_usage` throws it away into the tray tooltip. This surfaces it on hover, and puts a
detail window with a matched remedy behind a click.

All changes are in `widget.pyw`. No new files, no dependencies.

---

## 1. Tell "expired" apart from "absent" — `_token_from_blob`, `find_token` (456-530)

Today an expired token and a missing one both return `None`, so `fetch_usage` cannot tell them
apart. They need opposite advice (expired = restart Claude; absent = you may not have Claude
Code signed in at all), so this split has to happen first.

`_token_from_blob` returns a `(state, token)` pair — `"ok"`, `"expired"` or `"none"`.
`find_token` returns the same, taking the best state across every source: an `"ok"` anywhere
wins, otherwise `"expired"` if any source held an expired token, else `"none"`.

Two call sites move with it: the loop in `_credentials_from_manager` (500-511) currently tests
`if token:`, and `find_token`'s own file loop (519-526).

*Test:* `_token_from_blob` against three synthetic blobs — valid, `expiresAt` in the past,
no `accessToken`. Tokens in the test are the literal `"t"`, as now; no real credential ever
appears in the file.

## 2. Carry the remedy on the failure — `Failure`, `fetch_usage` (534-578)

`Failure = namedtuple("Failure", "reason retry_after detail remedy")`, with
`__new__.__defaults__` so existing short constructions still read cleanly.

`detail` is a sentence for the window; `remedy` is a key the UI switches on:

| Situation | remedy | reason (hover) |
|---|---|---|
| token found but expired | `expired` | Claude sign-in has expired |
| no token anywhere | `missing` | No Claude credentials found |
| 401 / 403 | `rejected` | Claude credentials rejected |
| 429 | `wait` | Rate limited by the API |
| other HTTP | `http` | Usage request failed (HTTP n) |
| exception | `network` | Usage unavailable |

The code that knows what went wrong picks the remedy. Nothing downstream re-parses a string.

## 3. Is Claude actually running — new `claude_processes()`

`CreateToolhelp32Snapshot` / `Process32FirstW` / `Process32NextW` via ctypes, next to
`detect_launch_cmd` (405). Returns a list of `(pid, name)` for executables matching
`claude*.exe` — a list rather than a bool because restart needs the pids.

Declare `argtypes`/`restype` on every call. Undeclared gdi32 argtypes silently corrupted
64-bit handles in 0.7.0 (GOTCHAS.md); the same trap applies to `HANDLE` here.

Fails safe: an unrecognised executable name reads as "not running", which at worst offers a
start that does nothing worse than today's silent click.

## 4. Remedy = reason × running state — new pure `remedy_for(remedy, running)`

Returns one of `start`, `restart`, `signin`, `wait`, `retry`. Pure function, so the whole
matrix is testable without Tk or a live Claude:

| remedy | not running | running |
|---|---|---|
| `expired` | start | restart |
| `missing` | start | signin (no start button — starting again won't create a file it never writes) |
| `rejected` | start | restart |
| `wait` | wait | wait |
| `http`, `network` | retry | retry |

`missing` while Claude is running is the case worth spelling out in the window: the credentials
file is written by Claude **Code**, not the desktop app, so a running desktop app proves
nothing. The window lists the paths checked and whether each exists.

## 5. Restart — new `restart_claude()`

Graceful first: `EnumWindows`, match each window's pid against `claude_processes()`, post
`WM_CLOSE`. Wait up to 5 seconds for the pids to disappear. Only then `OpenProcess` with
`PROCESS_TERMINATE` and `TerminateProcess`, then `launch_claude()`.

Behind a confirmation dialog naming what will be closed. A status widget that kills your Claude
session unasked is a worse bug than the one being fixed.

*Cost, stated plainly:* this is the riskiest code in the change and the only part that can lose
someone's work. The graceful path exists so the terminate path is rare. It is the one thing here
that cannot be covered by `--selftest`.

## 6. Keep the failure — `Widget.__init__`, `apply_usage` (1540)

`self.failure = None`, `self.last_ok = None`, `self.next_retry = None`. `apply_usage` sets
`self.failure = result` when not live and `self.last_ok = time.time()` when live. `poll_loop`
(1531) already computes `delay`; it records `self.next_retry = time.time() + delay`.

## 7. Hover — `tooltip_lines` (1387)

Branch on `self.live`. Disconnected, via a pure `disconnected_lines(failure, last_ok,
next_retry, now)`:

```
Not connected — Claude sign-in has expired
Last read 14 minutes ago  ·  retrying in 4 min
Weekly limit: resets Sun 8:45am
```

The reset lines stay. They are cached wall-clock facts and stay true with no API — that is
exactly why they are cached (DECISIONS.md). What goes is the **pace line**: a projection off
stale numbers, and actively misleading when disconnected.

## 8. Click — `on_click` (1658), new `show_diagnostics()`

`on_click` routes to `show_diagnostics()` instead of straight to `launch_claude()`. Built on the
`show_welcome` Toplevel (1436) — same frame, padding and button placing, no new UI machinery.

Contents: the reason in plain English; `detail`; last successful read; next automatic retry; the
credential paths checked with a present/missing mark against each (**never a token value**); and
one button from `remedy_for`, plus **Retry now** always, plus **Open log folder**
(`os.startfile(data_dir())`).

Costs one extra click to launch Claude. Worth it: today that click is silent and does nothing
visible at all when `launch_cmd` fails to resolve (1674).

## 9. Retry now — `poll_loop` (1538)

Backoff reaches 30 minutes, so someone who has just fixed the problem should not wait for it.
Replace `self.stopping.wait(delay)` with a new `self.wake` event: `self.wake.wait(delay)` then
`self.wake.clear()`. `quit()` sets `stopping` then `wake` so shutdown stays immediate. The
button sets `wake` and zeroes the failure count so backoff starts over.

---

## Verification

`--selftest` gains, all pure, no Tk:

- `_token_from_blob` — valid, expired, malformed
- `remedy_for` — every cell of the matrix in section 4
- `disconnected_lines` — a `Failure` in, expected strings out, including "last read" when
  `last_ok` is `None` (never connected)

Manual, since nothing above can prove them:

1. Rename `.credentials.json` → hover says missing, window lists the paths, button matches
   whether Claude is open.
2. Edit `expiresAt` into the past → expired wording, restart offered with Claude running.
3. **Restart button with unsaved work open in Claude** — confirm the graceful close prompts
   rather than discarding it.
4. Retry now during a long backoff → poll fires immediately.
5. `widget.log` clean throughout.

## Out of scope

No token refresh (DECISIONS.md — racing Claude's own refresh can break the real session), no
connectivity probing, no auto-repair.
