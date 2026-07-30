# Security

This tool reads an authentication token from your disk, so you're right to want to know what it
does with it. Here is everything, and how to check for yourself.

**Not affiliated with Anthropic.** This is an unofficial personal project, not made, endorsed,
or supported by them.

## What it reads

One thing: the OAuth access token that Claude already stores on your machine, from whichever of
these exists —

1. `%CLAUDE_CONFIG_DIR%\.credentials.json`
2. `%USERPROFILE%\.claude\.credentials.json`
3. Windows Credential Manager

It reads the token, uses it, and holds it in memory only for the duration of the request. It is
never written to disk, never logged, and never shown in the interface.

## Where it connects

Two addresses, and no others.

**1. Your usage figures — `api.anthropic.com`**

```
GET https://api.anthropic.com/api/oauth/usage
```

Authenticated with the token above. Returns your two usage percentages and their reset times.
Polled every five minutes at most, backing off when rate limited.

**2. The update check — `api.github.com`**

```
GET https://api.github.com/repos/aidanashby/claude-usage-widget/releases/latest
```

Once a day, to see whether a newer version exists. It sends **no token, no account
information, and nothing identifying you** — only a `User-Agent` naming the program and its
version, which GitHub requires. It never downloads or installs anything; if there's an update
it tells you, and opening the page is your decision.

Turn it off with **Check GitHub for updates** in settings, and this address is never contacted.

Nothing else leaves your machine. There is no analytics, no telemetry, no crash reporting, and
no server operated by this project.

## What it writes

Two files, neither containing anything sensitive, in `%APPDATA%\ClaudeUsageWidget`:

- `settings.json` — your preferences, window position, and last known usage percentages
- `widget.log` — errors only, and usually empty

For a portable install, put a file named `portable.txt` next to the program and both stay
beside it instead.

## Checking this yourself

The whole program is a single readable Python file, `widget.pyw`. You don't have to take any of
this on trust:

```bash
grep -n "urlopen\|https://" widget.pyw
```

Every URL in the program appears in that output. At the time of writing there are three, and
two `urlopen` calls — one per address above. The third URL is the releases *page*: the widget
never fetches it, it only hands it to your browser if you choose to open it.

## Verifying a downloaded build

Released builds are **unsigned**, so Windows SmartScreen will warn you the first time. Rather
than ask you to ignore that, each release is built by GitHub Actions from a tagged commit and
carries a provenance attestation, so you can confirm the zip came from this source:

```bash
gh attestation verify ClaudeUsageWidget-v1.0.0-win64.zip --repo aidanashby/claude-usage-widget
```

Each release also publishes a `.sha256` alongside the zip.

If you'd rather not run a binary at all, run the source directly — it's one file and needs only
Python.

## Reporting a problem

Open an issue at <https://github.com/aidanashby/claude-usage-widget/issues>. If it's something
you'd rather not post publicly, say so in the issue without the details and we'll find another
way.

This is a personal project maintained by one person in their spare time, so please don't expect
a commercial response time.

## A note on the usage endpoint

`/api/oauth/usage` is an internal endpoint used by Claude's own tooling, not a documented public
API. It could change or stop working without warning. The widget polls it conservatively, backs
off when rate limited, and shows grey bars rather than wrong numbers when it can't get an
answer.
