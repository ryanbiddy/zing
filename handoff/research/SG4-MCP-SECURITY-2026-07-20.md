# SG-4 scan: local-MCP security practice vs zing's actual surface

Scope: I shipped lease consumption last cycle — zing now reads a
WRITABLE file to decide where it connects. That is the most
attacker-controllable input this lane has ever taken, so the scan
audits zing against current local-MCP security guidance rather than
surveying it. Every verdict below was tested against the running code,
not reasoned from the docs.

## Guidance scanned (primary where it matters)

OWASP's MCP Security Cheat Sheet, plus the 2026 practitioner writeups
on tool poisoning and confused-deputy patterns. The controls that
apply to a local stdio server that reads local files and calls a
loopback peer:

1. loopback-only binding and strict URL validation
2. restricted, validated local file/config trust
3. credential handling that keeps secrets out of logs and URLs
4. strict tool schemas (`additionalProperties: false`)
5. tool-definition pinning against rug-pulls

## Audit result, per control

| Control | zing's state | How verified |
|---|---|---|
| Loopback-only URLs | HOLDS — `_validate_url` requires loopback host, explicit port, and rejects userinfo/query/fragment; applies to explicit config AND every lease URL | existing parametrized tests + hostile-lease test |
| Writable-file trust | HOLDS, now HARDENED — exact-key validation, relative-only `ui` paths, positive pid, liveness check; **gap found and fixed:** the read was unbounded | new `test_oversized_lease_is_refused_without_reading_it` |
| Credential hygiene | HOLDS — token read from env only, sent as a header, never written, never in a URL | new `test_configured_token_never_appears_in_any_surface` |
| Strict tool schemas | DISPOSITIONED, not a defect (below) | live stdio probe |
| Tool-definition pinning | N/A by architecture — tools are defined in this package's own code, not fetched from a remote server; a rug-pull requires compromising the package itself, which pinning inside the package cannot defend | — |

## The gap found and fixed

`read_lease` called `read_text()` with no size cap. `shot_list` already
caps its import at 2 MiB — and that input is USER-CHOSEN, therefore
less hostile than a file any local process can drop. The lease being
unbounded was an inconsistency, not a considered decision. Now capped
at 64 KiB (a conformant lease is well under a kilobyte) and refused by
`stat()` before any read, reported as `invalid_lease`.

## Considered and dispositioned: `additionalProperties: false`

OWASP recommends strict tool schemas. Ours are FastMCP-generated from
handler signatures and do NOT set `additionalProperties: false`.
Probed live against the real stdio server: an undeclared extra argument
is **silently dropped by the SDK before the handler is called** — the
tool answered normally with no error and no extra data reaching my
code. So for zing the control is inert: there is no injection path to
close, and the honest options are to accept it or to fight the SDK's
schema generation for no behavioural gain.

Recorded so a future scan does not re-derive it. If the SDK ever starts
FORWARDING unknown keys, this becomes a real finding — that is the
trigger.

## Not claimed

Sandboxing (containers/chroot) is an install-time decision for the
user's client, not something a stdio server can impose on itself.
OS-native credential storage (Keychain/Credential Manager) is a
documented tension: INTEGRATION-CONTRACT §3.2 MANDATES explicit env-var
configuration for peer credentials, so zing follows the contract. Worth
naming as a posture with a reason rather than pretending the two agree.

## Sources

- https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html
- https://techcommunity.microsoft.com/blog/microsoft-security-blog/the-state-of-mcp-security-in-2026/4531327
- https://generalanalysis.com/guides/mcp-server-security
- live probes against this repo's server and `suite_peer` (this cycle)
