# Security and Privacy

Kaperio is an alpha local desktop application, not a public file-conversion service.
Only open files you own or have explicit permission to recover.
File ownership and permission are separate from the software license.

## Stored data

- Imported source copies, hashes, recovery masks, candidate lists, previews,
  unlocked documents and exports stay in the local data directory. Source runs
  use `../outputs/kaperio/`; native apps use the per-user OS data directory
  listed in [DESKTOP.md](docs/DESKTOP.md). New Unix data directories use mode 0700.
- Candidate lists and masks can contain sensitive password information.
- Recovered passwords are kept in process memory; a temporary Hashcat result
  file is removed after reading. An abrupt process/machine failure may leave it.
- Data is NOT encrypted at rest. Protect the operating-system account and disk.
- Library deletion removes work copies/exports, not the original imported file.
  It is not secure erasure and does not remove browser downloads, backups or caches.
- Do not publish this data directory, launch URLs, screenshots with private
  content, conversion logs, private documents or unreviewed diagnostic output.

## Network boundary

- Default: loopback only, random launch token, HttpOnly SameSite cookie,
  exact Host/Origin validation, POST header checks, no analytics or remote uploads.
- Setup downloads Python packages from the user's configured package index.
  Optional Windows component setup downloads pinned Hashcat/NVRTC packages only
  after individual consent, validates SHA-256, and preserves component notices.
  It is restricted to authenticated loopback clients and does not install drivers,
  request elevation, or change system PATH. See [setup boundaries](docs/SETUP.md).
- Optional private-LAN HTTPS is experimental and not phone-device validated.
  Do not expose the server to the public internet or forward router ports.
- A launch URL grants full app access, including invoking configured local tools.
  Do not share it with an untrusted person. There is no multi-user permission model.
- Document parsing and Office conversion are NOT isolated in a hardened sandbox.
  Avoid untrusted files; keep Python dependencies, Office and GPU drivers updated.
  Disabling macros does not eliminate parser vulnerabilities or active-content risk.

## Reporting

Do not attach real passwords, document hashes or confidential files to public issues.
Use a synthetic reproduction. Submit sensitive security reports through
[GitHub private vulnerability reporting](https://github.com/7011yamazakyuuta-star/Kaperio/security/advisories/new).
Private vulnerability reporting is enabled for this repository.
No independent security audit, malware certification or code-signing is claimed.
