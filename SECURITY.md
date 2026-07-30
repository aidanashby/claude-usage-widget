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

## What it sends, and where

One request, to one address:

```
GET https://api.anthropic.com/api/oauth/usage
```

That returns your two usage percentages and their reset times. Nothing else leaves your
machine, ever. There is no analytics, no telemetry, no crash reporting, no update ping to any
server run by this project, no third-party network access of any kind.

## What it writes

Two files, both local, neither containing anything sensitive:

- `settings.json` — your preferences, window position, and last known usage percentages
- `widget.log` — errors only, and usually empty

## Checking this yourself

The whole program is a single readable Python file, `widget.pyw`. You don't have to take any of
this on trust:

```bash
grep -n "urlopen\|Request(\|http" widget.pyw
```

Every network call in the program will appear in that output. At the time of writing there is
exactly one, to the address above.

If a packaged build is ever published, it will be built in public CI from a tagged commit, with
published SHA-256 checksums and build provenance, so the binary can be verified against the
source it came from.

## Reporting a problem

Open an issue at
<https://github.com/aidanashby/claude-usage-widget/issues>. If it's something you'd rather not
post publicly, say so in the issue without the details and we'll find another way.

This is a personal project maintained by one person in their spare time, so please don't expect
a commercial response time.

## A note on the endpoint

`/api/oauth/usage` is an internal endpoint used by Claude's own tooling, not a documented public
API. It could change or stop working without warning. The widget polls it every five minutes at
most, backs off when rate limited, and shows grey bars rather than wrong numbers when it can't
get an answer.
