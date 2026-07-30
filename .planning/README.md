# Notes for whoever works on this next

Four documents, written so you don't have to rediscover things the hard way:

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — how one 1,900-line file is organised, and why it is
  one file.
- **[GOTCHAS.md](GOTCHAS.md)** — read this before touching the tray, the window procedure, or
  anything Win32. Every entry cost real debugging time.
- **[DECISIONS.md](DECISIONS.md)** — choices that look arbitrary until you know what was
  rejected and why.
- **[ROADMAP.md](ROADMAP.md)** — what's deliberately not built, and what's worth doing next.

## The one-paragraph version

It shows two bars: Claude's five-hour session limit and weekly limit. It polls one undocumented
endpoint with the OAuth token Claude already stores locally, draws two rectangles on a
borderless always-on-top Tk canvas, and lives in the system tray. It is deliberately small.
Most changes that make it bigger are the wrong changes.

## Guiding constraint

**No third-party packages.** Everything is Python standard library, including the Win32 work via
`ctypes`. This is what lets someone clone the repo and run it immediately, and lets a reader
audit a tool that touches their auth token by reading one file. Adding a dependency to save
twenty lines is not a good trade here; adding one to save two hundred might be, but think hard
first.
