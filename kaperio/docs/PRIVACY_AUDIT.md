# Privacy and dependency checks in alpha.10

Date: 2026-09-26. This is a targeted follow-up to alpha.9, not an independent audit.

## Temporary data

- Remove the transient, plaintext-equivalent `found.hex` result in a `finally`
  block, including malformed output, process startup failure and wait failure.
  Limit reading to 64 KiB and use fixed error messages that do not include secrets.
- Document workers use their supervised private directory as the working
  directory and as Python/native helper temp storage (`TMP`, `TEMP`, `TMPDIR`).
  Python's cached temp directory is also set before document libraries are loaded.
- Count nested temporary files as well as top-level output, with a 1 GiB total
  and 10,000-entry limit. Reject links, Windows reparse points and special files.
  Check again after the worker exits before accepting its result.
- Ordinary cancellation/failure cleanup remains in place. Hard app termination,
  power failure or removal failure can leave data. No startup sweep deletes old
  data or recovery checkpoints, and deletion is not secure erasure.
- This does not constrain helpers that ignore temp variables or use absolute
  paths. External Office conversion is still separate. No privilege sandbox or
  encrypted storage is provided. The aggregate limit can reject large exports
  with intermediate files even when the final output alone would fit.

## Dependency audit

`scripts/audit_dependencies.py` inventories the actual installed versions in the
same declared runtime package list used by the desktop license collector. It
checks the active, non-extra dependency declarations for missing packages and
version conflicts before auditing. This is not binary import discovery or an SBOM.

The script runs pip-audit 2.10.1 in a separate virtual environment. The audit uses
fully pinned names/versions with `--disable-pip --no-deps --strict`, so scanning
does not install or resolve document libraries. It verifies full report coverage,
including versions, before recording success. The tool's own transitive
dependencies are not a fully hashed lockfile.

Each OS's CI runs the audit before building/uploading its native package. Network
failure, missing records, skipped packages or a vulnerability stop the build;
there are no ignored vulnerability IDs. Public package versions go to PyPI's
advisory service. User documents, hashes, passwords and recovery hints do not.

Evidence is retained as a separate `Dependency-audit-*` Actions artifact for 14
days, including the exact package list, raw report and timestamped success summary.
The summary is removed before each run so a failed retry cannot retain old success.

Local Windows validation found no known advisories for the 16 declared Python
runtime distributions. This is a dated database result, not a safety guarantee.
The source suite passed 95 tests before native CI; release notes record fresh
platform results. No prior release's native results are used as proof for this one.

Excluded: Python, embedded native libraries (including PDFium/OpenSSL), Hashcat,
CUDA/driver components, Office, OS components, build tools, malicious packages and
unknown vulnerabilities. Package-level results do not prove those components safe.

References: [pip-audit documentation](https://github.com/pypa/pip-audit),
[PyPI vulnerability information](https://docs.pypi.org/api/json/#known-vulnerabilities).
