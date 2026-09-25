# Loxmit design verification

## Accepted direction

The user-approved light three-column dashboard and yellow-work-cap locksmith
pixel artwork are the visual references. The selected character is preserved in
`static/brand-source.png`; `scripts/build_icons.py` only normalizes transparent
margins and produces PNG, ICO, and ICNS sizes. It does not redraw the character.
The generated artwork is included under this project's MIT license.

- Neutral file library, unframed work area, right-side run inspector.
- Active blue `#2563eb`; paused and completed states neutral `#5b616a`.
- File accents: Word `#185abd`, Excel `#107c41`, PowerPoint `#c43e1c`.
- PDF uses a red Lucide document icon. No third-party product logo is copied.
- Determinate progress keeps its true width. Its directional highlight is clipped
  to that width and stops on pause, cancellation, completion, lost connection,
  hidden tab, or telemetry older than eight seconds. Reduced motion removes it.
- No success-probability meter, speculative ETA, or placeholder execution log.
- Event history is bounded to 80 entries; public summaries exclude password hints.
- File-list DOM rows remain stable during polling to preserve keyboard focus.
- Existing decryption, six recovery methods, preview and export remain connected
  to the actual backend. Private documents are not used for acceptance tests.

## Intentional differences from the reference

The current stage is the real candidate-preparation/search/open lifecycle, not
the mock's fabricated pipeline. The summary omits remembered password fragments.
Actual throughput uses Hashcat's H/s units. Forms are editable before execution;
a read-only summary replaces them while running. An unlocked document has its
real preview, whereas a locked document does not reserve an empty preview panel.
Small-screen columns stack and the library becomes a horizontal file list.

## Verification

Verified locally on Windows 11 on 2026-09-25:

- 36 unit/HTTP tests passed, including elapsed-time pause/restart accounting,
  event-history limits, secret-free summaries, old-library compatibility on
  mocked Windows/macOS/Linux paths, and icon sizes/transparency.
- Packaged Windows EXE passed 18 frozen checks: authentication, notices, assets,
  guided estimation, four PDF encryption revisions, preview, four PDF export
  formats, DOCX/XLSX/PPTX byte-preserving decryption, ZIP, single instance and
  original-preserving deletion.
- Edge browser acceptance passed against the final EXE. Six recovery methods,
  known-password unlock, preview, export, settings and deletion were exercised.
- Screenshots reviewed at 1586x992 and 320x900; automated no-horizontal-overflow
  checks passed at 320, 390, 768, 1024, 1440 and 1920 pixels. Long Japanese
  filenames were also checked at 320 and 1440 pixels.
- Browser assertions verify Office colours, neutral completed/paused colours,
  actual changing animation transforms, exact determinate progress width,
  pause/resume, stale telemetry, disconnect, reduced motion, stable focused
  rows across polls and arrow-key tab navigation. No page JavaScript errors.
- PNG, Windows ICO and macOS ICNS artwork generated and inspected; the Windows
  executable includes the ICO. macOS/Linux native execution is not locally
  verified by these Windows tests. Their existing build matrix uses Loxmit names.

Screenshots from `tests/release-smoke.cjs` use synthetic documents and explicit
browser-only state fixtures. They are UI evidence, not GPU performance evidence.
Previous Kaperio benchmarks remain historical and the engine is unchanged.
