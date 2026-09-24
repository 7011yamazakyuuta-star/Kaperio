# Validation Record

Date: 2026-09-24. Scope: local Windows, CPython 3.12.14, source alpha.
This is a development validation record, not a certification or independent audit.

## Confirmed

- 16 unit/HTTP/release tests passed: generated PDF revisions, decryption checks,
  image exports, OOXML byte preservation, AES ZIP, traversal rejection,
  API authentication/Origin, license endpoint, instance lock, deletion,
  converter cancellation/timeout, external settings and release allowlist checks.
- Real Hashcat 7.1.2 on RTX 4060 Laptop GPU/OpenCL: fixed prefix/suffix mask,
  pause, existing restore checkpoint, resume and cancel passed.
- Real generated-document integration passed for 9 cases: Office .docx/.xlsx/.pptx,
  WinZip AES and PDF RC4-40, RC4-128, AES-128, AES-256-R5, AES-256-R6.
  The R5/R6 parser was fixed to include both encrypted key fields.
  Each job was bounded to 1 minute; cold initialization was included.
- Microsoft Word, Excel and PowerPoint PDF exports passed on this Windows PC.
  A prior Excel timeout was not reproducible; its exact cause is not established.
  Converter supervision now bounds runtime and only cleans up identified owned
  Office processes, not arbitrary user Office processes.
- Earlier browser smoke covered 1440px desktop and 390px narrow layouts,
  import, known-password handling, preview, export and API rejection cases.
- Source ZIP extracted to a separate local folder: setup.ps1 created an isolated
  virtual environment and installed packages without using the development venv.
  All 16 unit/HTTP/release tests passed again without Hashcat or John in the package.
  This is a clean-folder test on the same Windows machine, not a clean OS VM.
  Package-index resolution selected pypdf 6.19.0, ReportLab 4.5.1 and lxml 6.1.3;
  the development environment used 6.10.0, 4.4.9 and 6.1.1 respectively.
- Fresh-package Edge headless smoke passed: no-engine settings, MIT/third-party
  notices, wrong/correct password, nonblank PDF preview, image-PDF output,
  390px settings layout, library deletion preserving the original and duplicate
  instance prevention. Desktop and mobile screenshots were inspected locally.

## Limits

- macOS/Linux and physical mobile devices are not validated.
- Classic ZipCrypto, macro-enabled Office and old Office formats are not
  covered by the generated-file acceptance test. Do not advertise universal support.
- No comparative speed benchmark, recovery-success guarantee, OCR,
  signed executable, installer certification or independent security audit.
- Source packages exclude all user documents and generated test outputs.
- Fresh-machine installation, public hosting and download provenance are separate
  checks; local success alone is not hosted CI or a publicly published release.
