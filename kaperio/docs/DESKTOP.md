# Kaperio Desktop 0.2.0-alpha.1

## Downloads

Native bundles are published on [GitHub Releases](https://github.com/7011yamazakyuuta-star/kaperio/releases).
An operating-system build is only published after its frozen executable smoke test passes.
The source ZIP is independent of the native bundles. No app store is required.

| Platform | Package | Launch | Status boundary |
|---|---|---|---|
| Windows x86-64 | ZIP | `Kaperio.exe` | Local Windows 11 testing; GPU tested separately |
| macOS Apple Silicon | ZIP containing `.app` | `Kaperio.app` | Native hosted build/smoke, not physical GPU validation |
| macOS Intel | ZIP containing `.app` | `Kaperio.app` | Native hosted build/smoke, not physical GPU validation |
| Linux x86-64 | tar.gz | `Kaperio/Kaperio` | Ubuntu 22.04 build; glibc >= 2.35, not every distro |

These are portable application bundles, not a single standalone executable and not installers.
Keep all files together. The app starts a local HTTP service and opens the default browser.
Python and application libraries are included; the browser, GPU driver, Hashcat, zip2john,
and Office/LibreOffice are not included. Known-password decryption does not require Hashcat.
PDF raster export and image-based Word export work without Office. Office-to-PDF needs
an installed Microsoft Office (Windows) or LibreOffice (all supported desktop systems).

Windows executables are unsigned. macOS bundles have only build-tool ad-hoc signing,
not an Apple Developer ID signature and not notarization. OS reputation/Gatekeeper
warnings are expected. Do not disable security software or system-wide security checks.
For managed machines follow the administrator's policy. Signing requires the owner's
certificates/account and is outside this alpha release.

## Local data

- Windows: `%LOCALAPPDATA%/Kaperio`
- macOS: `~/Library/Application Support/Kaperio`
- Linux: `$XDG_DATA_HOME/kaperio`, or `~/.local/share/kaperio`
- Override with `--data DIRECTORY`; source launches retain `outputs/kaperio`.

The application retains imported copies, recovery inputs, checkpoints, and plaintext outputs.
Protect this directory. It is never included in release bundles. Renaming Hiraku does not
automatically move or delete old user data; use `--data` explicitly to reuse an old library.
The original documents are not modified. Use the app's power button to stop its service.

## Hashcat and optimization

The official latest stable release verified on 2026-09-24 is
[Hashcat 7.1.2](https://github.com/hashcat/hashcat/releases/tag/v7.1.2), published 2025-08-23.
The official `hashcat-7.1.2.7z` SHA-256 is
`80db0316387794ce9d14ed376da75b8a7742972485b45db790f5f8260307ff98`.
Set the executable in Settings, or use `KAPERIO_HASHCAT`. Use a native executable and
the complete upstream installation for your OS, not another OS's binary.
On macOS Hashcat support still depends on the OS/GPU/backend supported by upstream.

Kaperio uses upstream kernels unchanged. Auto mode requests `-O` for supported PDF
modes only when every candidate is at most 16 UTF-8 bytes. A longer dictionary keeps
the pure kernel for the entire list; no candidate is silently removed to improve speed.
The pure option allows comparison. Office and ZIP retain their normal kernels.
Default workload 1 and temperature abort at 80 C remain in place. No `--force`,
overclocking, driver replacement, or thermal-protection bypass is used.

`tests/benchmark.py` compares pure CLI, identically configured optimized CLI, and the
Kaperio runner using equal candidate sets. Each profile runs three times in rotated
order, using the same device, mode, workload, and thermal limit. Initial samples are
discarded. Thermal warnings are retained. This distinguishes upstream optimization
benefits from application overhead; it does not prove superiority over tuned Hashcat.

## Build and verify

Run these commands from `kaperio` on the target OS in a clean Python 3.13 environment.
CI uses 3.13.15, whose native builds are available on all four targets. Local Windows
development also tests 3.12.14. Runtime versions are listed inside each artifact.

```text
python -m pip install -r requirements-dev.txt -c requirements-tested.txt pyinstaller==6.22.3
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/build_desktop.py
python tests/frozen_smoke.py PATH_TO_BUILT_EXECUTABLE
```

PyInstaller is not a cross-compiler. The GitHub Actions matrix builds on native runners.
The smoke test launches the packaged executable from an unrelated working directory and
checks authentication, notices, PDF preview, four PDF export formats, the frozen Office
hash helper, byte-preserving DOCX/XLSX/PPTX unlock, ZIP unlock, single instance, and deletion.
Hosted runners do not prove GPU performance, Office automation, or desktop-browser behavior.

Bundles include the exact installed runtime package license/notice files, PDFium native
notices, the Python license, and an inventory. See `licenses/runtime` inside the bundle
and Settings > licenses. External tools retain their own licenses and are not redistributed.
