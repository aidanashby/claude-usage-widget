# Roadmap

Ordered by likely value, not by ease. Nothing here is committed.

## Most likely worth doing

**macOS support.** Probably the single biggest expansion of the audience, since Claude Code
users skew heavily Mac. Also the most expensive thing on this list: tray, monitor geometry,
single-instance and login registration are all Win32 today. It needs a platform layer behind an
interface and a permanently doubled test matrix. Don't start it casually.

**API-key and credit-based accounts.** The usage response already carries `spend` and
`extra_usage` fields that are currently discarded. People on credit billing want money spent,
not a percentage of a subscription limit. Mostly display work, and the data is already arriving.

**Code signing.** Deferred on cost. Azure Trusted Signing is roughly $10/month and signs in CI,
which is far cheaper than a traditional certificate. Worth revisiting if downloads justify it —
SmartScreen warnings are the biggest single drag on conversion for an unsigned Windows tool.

**winget submission.** Reaches people who'd never find a GitHub release. Requires a manifest PR
to `microsoft/winget-pkgs` and is easier to justify once signed.

## Plausible, in scope

- **A history sparkline**, kept to a single line — it was deliberately reduced to one tooltip
  line for 0.10 to avoid changing what the widget is. Anything larger needs a hard look.
- **Configurable alert thresholds.** Fixed at 80% and 95%. Nobody has asked yet; wait until
  someone does.
- **A custom bar colour** beyond the three presets. Common request for desktop widgets, and
  cheap. It was offered and declined once already.
- **Multiple monitors for the position watchdog.** Snapping is per-monitor, but "recall to
  primary" is always the primary. Fine, and someone will eventually want "recall to the monitor
  it was on".
- **Mixed-DPI accuracy.** Tk runs DPI-virtualised, so positions can be a few pixels off on
  mixed-scaling setups. It stays on screen and usable; making it pixel-exact means per-monitor
  DPI awareness and a manifest.

## Deliberately not doing

- **Numbers or labels on the widget.** It's two bars. See DECISIONS.md.
- **Silent self-update.** A tool that reads your auth token should not replace its own binary
  without asking.
- **Telemetry of any kind**, including anonymous. SECURITY.md promises its absence, and that
  promise is worth more than the data.
- **A dashboard, history graphs, or team features.** Different product.
- **Third-party dependencies** for anything the standard library can do.

## Watch items

**The endpoint could break or be blocked.** It's internal and undocumented, and thousands of
clients polling it is a different proposition from one. If this ever gets popular, tell
Anthropic rather than wait to be noticed, and be ready for a version that degrades gracefully
to "usage unavailable" permanently.

**Support burden.** A popular free Windows utility generates issues, and this is one person's
spare time. Issue templates, a FAQ, and a stated scope ("it does two bars") protect the
simplicity better than any technical decision. Worth adding before rather than after any
attention arrives.

**Trademark.** "Claude" is Anthropic's. The non-affiliation notice in the README and
SECURITY.md is deliberate and should stay; avoid their wordmark in icons and branding.
