# Resource hardening in 0.4.0-alpha.9

Date: 2026-09-26. This is a targeted fix, not an independent security audit.

## Changes

- Apply Office archive limits before inspecting plain OOXML, and again after
  decryption before CRC validation. Retain the existing ZIP 512 MiB / 10,000-entry
  limits and reject oversized Office manifest/workbook XML before parsing.
- Keep slow recovery preparation and ZIP settings reinspection outside the shared
  library lock. Preparation has its own visible, cancellable `preparing` state.
  Metadata extraction on unlock also runs outside this lock.
- Perform TLS handshakes in bounded connection workers, not the accept loop.
  Limit connections to 32, TLS handshakes to 5 seconds and socket inactivity to
  30 seconds, including JSON requests and request headers.
- Move input inspection, known-password decryption, recovery metadata extraction,
  previews, PDF validation and PDF exports into disposable processes. Only one
  document process may run per library. Hashcat itself is unchanged.
- Supervise process-tree RSS every 50 ms, with a 2 GiB budget, 120-second default
  deadline and 300-second export deadline. Queue waiting counts against deadlines.
  Windows Job Objects also cap committed memory across worker descendants at
  2 GiB and terminate descendants on worker exit. Linux also caps virtual address
  space at 4 GiB. Unix disables core dumps and caps CPU time and file size.
- Stage worker outputs in a private directory and atomically commit only on success.
  Enforce a 1 GiB output-file limit, 16 MiB IPC result limit, 32 MiB preview limit
  and 64 KiB request limit. Passwords use an anonymous pipe; requests are never
  written to disk or included in argv. Crashes, cancellation, timeout and ordinary
  errors remove staging directories and preserve earlier outputs.
- Cancel POSIX converter process groups and bound converter log reads to 8,000
  trailing bytes. Stop runaway conversion logs at an 8 MiB polling threshold.

## Validation

Local Windows source tests: **89 passed**, including 12 new hardening tests.
The Windows frozen executable passed **25 smoke-check groups** and **48 browser
acceptance groups**, including preview-error retry and responsive layouts.
The hardening suite includes a Windows progress-file sharing regression discovered
by exercising the frozen executable, in addition to the initial 10 hardening tests.
The new tests cover plain/encrypted Office expansion, metadata/entry limits,
responsive status/cancel during preparation, worker round trips and exports,
timeout/memory/crash/cancel cleanup, descendant cleanup, shutdown rejection,
TLS handshake isolation, JSON body timeout and connection-slot recovery.

The Office expansion regression lowers the limit to 1 MiB and uses a 2 MiB
synthetic payload; it does not allocate a real oversized archive. Worker failure
tests use short-lived synthetic subprocesses, not malformed private files or GPU
work. Prior alpha.8 native build results are not evidence for this version.

## Limits of the protection

- Process separation is crash/resource containment, not a privilege sandbox.
  A compromised parser still runs as the current OS user and is not network-isolated.
- RSS polling can overshoot between samples; macOS has no hard OS memory cap here.
  GPU memory and externally launched Microsoft Office/LibreOffice memory are not
  included in the document-worker budget. External conversion retains its separate
  120-second supervision and safe ownership checks for existing Office instances.
- Input size alone does not bound parsing cost. Some otherwise valid complex
  files will be rejected by the limits. Imported input remains capped at 200 MiB.
- A power failure or forced app kill can leave temporary files. Local data is not
  encrypted at rest, and deletion is not secure erasure. No malware scan, code
  signing, notarization, complete dependency-vulnerability scan or real Mac/Linux
  GPU performance validation is implied.
- Fresh worker startup adds latency to document operations. No new GPU throughput
  improvement is claimed, and prior large-document measurements are not a new
  benchmark of this implementation.
