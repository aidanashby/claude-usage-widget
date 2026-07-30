# Decisions

Choices that look arbitrary without the reasoning, and what was rejected.

## Read the API rather than parse Claude's logs

`GET /api/oauth/usage`, authenticated with the token Claude already stores, returns exactly the
two percentages plus each window's `resets_at`. The alternative — totting up token counts from
JSONL transcripts — can't know the actual limits and so can't produce a percentage.

**Cost:** the endpoint is internal and undocumented. It may change without warning. Everything
is built so that failure shows grey bars, never wrong numbers.

## Don't refresh the OAuth token

Racing Claude's own refresh can invalidate its session, which would break the user's actual
Claude install to keep a status widget alive. An expired token is treated as absent: bars go
grey, and clicking launches Claude, which refreshes it properly.

## Window progress is derived from `resets_at`, not from a guessed schedule

Both limits run a fixed span (5 hours, 7 days) ending at `resets_at`, so elapsed fraction
follows from the reset time alone — and it's per-user because `resets_at` is per-user.

Confirmed empirically: a session that had just reset read 0.022 progress, i.e. a window that
began about seven minutes earlier.

## Reset times are cached in settings

A reset time is wall-clock fact and stays true whether or not the API answers. Caching it is why
the markers and tooltip keep working while the bars are grey.

## One alpha for the whole window

Tk applies a single alpha to a toplevel, so the bars fade with the panel; they are not
independently opaque. True per-element alpha would mean `UpdateLayeredWindow` and hand-composed
bitmaps — a large amount of Win32 for a cosmetic gain. Rejected. At the default 0.7 the orange
still reads clearly.

## Click-through gives up the tooltip

With `WS_EX_TRANSPARENT` the widget receives no mouse events at all, so `<Enter>` never fires
and the hover tooltip cannot appear. That's inherent, not a bug. The tray takes over every
interaction, and this is stated in the settings window, the README and the changelog — because
undocumented it reads as a defect.

## Tray notifications, not toast APIs

Balloons via `Shell_NotifyIconW` with `NIF_INFO` cost nothing extra: the `NOTIFYICONDATA` is
already there. Modern Windows renders them as ordinary toasts. A real toast API would mean a
dependency or a COM/AppUserModelID dance for no visible gain.

## Update check notifies, never installs

A tool that reads your OAuth token silently replacing its own binary is a hard trust sell, and
the trust posture is a feature here rather than an afterthought. It tells you and offers to open
the page.

## Unsigned, but attested

Code signing was deferred on cost. Unsigned *and* unverifiable is what a credential stealer
looks like, so releases are built by GitHub Actions from a tagged commit with
`actions/attest-build-provenance` and a published SHA-256. The README says plainly that
SmartScreen will warn and how to verify instead — hiding it would cost more trust than admitting
it.

## `--onedir`, not `--onefile`

Faster startup, and far fewer antivirus false positives, which matter more than a tidy
single-file download for an unsigned tool.

## Settings in `%APPDATA%`, with a portable escape hatch

An installed program can't assume it may write beside itself. A `portable.txt` marker restores
local storage explicitly — chosen over "write locally if the folder happens to be writable",
which changes behaviour silently depending on where the user unzipped it.

## Bars are unlabelled

The whole idea is something you glance at, not read. Numbers live in the hover tooltip and the
tray tooltip. Proposals to put text on the widget are proposals to make it a different tool.
