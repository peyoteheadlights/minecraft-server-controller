# What the dashboard knows, and how it knows it

This project has a hard rule: **it never turns an assumption into a fact.**
If a value cannot be measured, it says so, with the reason.

That is why the dashboard sometimes shows "Unknown" where other tools show a
confident number. An unknown you can see is more useful than a plausible
number you cannot trust.

## Source of truth for every value

| Value | Source | When it is Unknown |
| --- | --- | --- |
| Server state | The child process the agent launched, plus the `Done (…)!` line in the console | Before the agent has checked anything, the state is `UNKNOWN` - not `OFFLINE` |
| ONLINE specifically | The startup line actually appearing in the console | A launched process that has not finished starting is `STARTING`, never `ONLINE` |
| Minecraft version | `Loading Minecraft X with Fabric Loader Y` in the console | Until the server has started once. Never guessed from a folder or file name |
| Fabric Loader | The same console line | Same |
| Java version | `java -version` output, parsed | If the executable is missing or the output is unparseable |
| Java compatibility | Detected Java compared with the detected Minecraft version | If either is unknown - then no verdict is given at all |
| Players online | Join/leave lines, `/list` replies, or the server not running | Before any of those. An empty list is not a verified zero |
| TPS | A tick-rate command that actually answered (Carpet, spark, `tick query`) | Whenever nothing answered. **Never 20.0** |
| MSPT | The same reply | Same |
| Minecraft RAM | `psutil` process RSS | When the process is not running. `-Xmx` is an allocation limit and is labelled as such, never as usage |
| CPU, system RAM | `psutil`, operating-system counters | If the OS query fails |
| Disk | A live filesystem query, every time | If the query fails |
| Port 25565 | An actual TCP connection attempt | It is not checked when the server is offline, and says so |
| Tailscale | `tailscale status --json` from the daemon | If the CLI is missing or errors. An assigned `100.x` address is reported as "interface detected", explicitly **not** as connected |
| TLS certificate | Parsing the PEM file on disk | If the file is missing or unparseable - never reported as "valid" |
| Crash cause | Pattern matches against console output and the crash report | When nothing matches, the cause is `Unknown` and no category is claimed |
| Mod version | The `fabric.mod.json` inside the installed jar | If the jar has no readable metadata |
| Mod compatibility | Jar metadata, then the Modrinth listing | Before the Minecraft version is known |
| Mod loaded | The running server reporting it | Always unknown until the server has started with that mod |
| Backup status | Opening the archive and checking it | A backup that fails verification is recorded as `unverified`, not `ok` |

## Crash confidence

Four levels, and they mean different things:

| Level | Meaning |
| --- | --- |
| **confirmed** | The error itself is in the log. `java.lang.OutOfMemoryError` present means it *was* an out-of-memory error. What triggered it is still a separate question. |
| **likely** | Strong evidence, but the printed error is often a symptom. A mixin failure usually means a version mismatch - usually. |
| **possible** | The pattern matched but is frequently incidental. A `SocketException` around a crash is often noise. |
| **unknown** | Nothing matched. No cause is claimed at all. |

Mods that appear in the evidence are listed as "mods mentioned in the log",
with a note that appearing in a stack trace is not evidence of causing the
crash. The category is always the error class, never a mod name.

## Mod compatibility

| Verdict | Meaning |
| --- | --- |
| `verified_metadata` | The jar's own `fabric.mod.json` declares this Minecraft version. Metadata, not a test. |
| `likely` | Modrinth lists this build for your version, but the jar did not confirm it. That is the publisher's claim. |
| `unknown` | The server's Minecraft version has not been observed, so nothing can be compared. |
| `incompatible` | A declared requirement is definitely not met. |

Nothing ever returns "compatible, tested". Only running it tells you that.

## Conflict detection

The mods page says **"No declared conflicts detected"**, never "no conflicts".
The difference is the whole point: only metadata was read, nothing was
executed. Two mods can corrupt each other's chunk data with nothing in either
manifest to warn you.

## Operations

A request is not an outcome:

| The agent says | It means |
| --- | --- |
| Start: `REQUESTED` | The process was launched. Startup has not completed. |
| `server_started` event | The startup line appeared. It is genuinely up. |
| Stop: `VERIFIED` | The process exited and the agent saw it happen. |
| Backup: `verified` | The archive was opened, integrity-tested and hash-checked. |
| Mod installed | The file is in place. `loaded_by_minecraft: not verified`. |
| `server_recovered` | The server restarted **and completed startup**, not merely relaunched. |

## Health

There is no single green light. The overall status is one of:

- **ALL CHECKS VERIFIED** - everything was measured and is within threshold
- **PARTIALLY VERIFIED** - some values could not be measured; they are listed
- **ATTENTION NEEDED** - something measured is outside its threshold

Unknown checks are never counted as passing. A server with no TPS provider
shows PARTIALLY VERIFIED forever, and that is correct.

## Tested

`tests/test_no_fabrication.py` removes each data source in turn and asserts the
system reports unknown rather than a default: no TPS provider, no player
evidence, undetectable Java, unobserved Minecraft version, unmatched crash,
failed backup verification, unverifiable Tailscale, unreadable certificate, and
a launched-but-not-started server.
