# Third-Party Components

Reviewed 2026-09-24 for the source-only alpha release. This is not an audit of a
bundled executable, installer or every possible future dependency version.
Hiraku's MIT license covers its original application code only.

## Included in the source ZIP

| Component | Source and version | License evidence |
|---|---|---|
| `vendor/office2john.py` | Openwall bleeding-jumbo snapshot, retrieved 2026-09-24 | Permissive notice in the original source and `licenses/office2john.txt` |
| `static/lucide.min.js` | Lucide 1.8.0 UMD distribution | ISC and Feather-derived MIT notices in `licenses/lucide.txt` |
| `static/icon-192.png`, `static/icon-512.png` | App icon derived from Lucide's lock-keyhole-open icon | Same Lucide notices |

The office2john file was retained unchanged. It has its own permissive notice;
this does NOT imply that John the Ripper's complete binary has that same license.
The exact included file contents are identified by the release SHA-256 manifest.

- [office2john source](https://github.com/openwall/john/blob/bleeding-jumbo/run/office2john.py)
- [Lucide license](https://lucide.dev/license)

## External programs, not redistributed in this ZIP

- Hashcat: user-installed CLI, tested with 7.1.2. MIT for the main program;
  upstream `docs/license_libs/` contains additional component notices.
  [Source and license](https://github.com/hashcat/hashcat/blob/v7.1.2/docs/license.txt)
- John the Ripper / zip2john: optional user-installed CLI for ZIP recovery.
  The local development copy of John and its DLLs is excluded from releases.
  The complete John distribution is primarily GPL-2.0-or-later with exceptions
  and component-specific terms. Redistributions require separate compliance,
  including corresponding source obligations where applicable.
  [Official licensing](https://www.openwall.com/john/doc/LICENSE.shtml)
- Microsoft Office or LibreOffice: optional user-installed application for
  Office-to-PDF conversion. Office requires the user's own valid license.
- GPU drivers and SDKs: provided by hardware vendors, not bundled.

Invoking a separate CLI is not a blanket exemption from license obligations.
Do not add these binaries to a release without reviewing their complete terms.
Hiraku is not an official or endorsed Hashcat, Openwall or Microsoft product.

## Python packages installed by the user

`requirements.txt` lists runtime packages. Their source/wheels are obtained at
setup time from the user's package index and are not inside this source ZIP.
`requirements-tested.txt` records the locally observed versions; it is not an
all-platform lockfile. Development tests additionally use openpyxl/python-pptx.

Runtime packages include pypdf, pypdfium2/PDFium, ReportLab, python-docx, Pillow,
cryptography, msoffcrypto-tool, pyzipper and their transitive dependencies.
Their original licenses remain applicable. Before frozen-EXE/offline packaging,
inventory the exact wheels, collect all notices (including PDFium and native
libraries), check required source/relinking provisions and perform a new review.

No external font service, analytics, remote conversion or runtime CDN is used.
