# Code Signing Policy

Windows release binaries of XXAR are digitally signed.

Free code signing provided by [SignPath.io](https://signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

## Signed artifacts

| Artifact | Description |
|---|---|
| `XXAR-Installer-v<version>.exe` | Per-user Windows installer |
| `XXAR-Uninstall.exe` | Uninstaller, shipped inside the installer payload |
| `XXAR.exe` | Application executable, inside the installer payload and the portable archive |

`XXAR-windows-x64.zip` (portable channel) is not itself a signable format; the executables it contains are signed.

All signed binaries carry `ProductName`, `ProductVersion` and `FileVersion` version resources, generated at build time from `APP_VERSION` in [src/core/app_config.py](src/core/app_config.py).

## Project roles

XXAR is currently maintained by one person, who therefore holds all three roles:

| Role | Holder |
|---|---|
| Author — writes and modifies source code | [@Entity378](https://github.com/Entity378) |
| Reviewer — approves changes to the repository | [@Entity378](https://github.com/Entity378) |
| Approver — authorizes a signing request | [@Entity378](https://github.com/Entity378) |

This document is updated before any additional maintainer is granted a role.

Multi-factor authentication is enforced on the GitHub account that owns the repository and on the SignPath account that submits signing requests.

## Build and signing process

- The full source is public at [github.com/Entity378/XXAR](https://github.com/Entity378/XXAR) under GPL-3.0.
- Every published Windows binary is produced by the public GitHub Actions workflow [.github/workflows/release.yml](.github/workflows/release.yml), which runs [installer/build.ps1](installer/build.ps1) on a tagged commit. Binaries built on a maintainer's machine are never published.
- Signing requests originate from that workflow only, and each one is approved manually by the Approver before the certificate is used.
- Releases are published from the same workflow run that produced and signed the artifacts.

## Third-party components

The signed artifacts contain only code from this repository plus its open-source Python dependencies, listed in [requirements.txt](requirements.txt) and bundled by PyInstaller. No proprietary or closed-source component is included in, or distributed with, any signed binary.

XXAR uses three external audio tools at runtime — Audiokinetic Wwise, FFmpeg and vgmstream. **None of them is redistributed by this project.** They are downloaded by the user, on an explicit action in the application, into `%LOCALAPPDATA%\XXAR\tools\`, by [setup_wwise.py](setup_wwise.py) and [setup_windows_audio_tools.py](setup_windows_audio_tools.py). The repository contains only `src/resources/WAVtoWEM/WAVtoWEM.wproj`, a Wwise project configuration file authored by this project.

## What XXAR changes on the user's system

XXAR installs per-user and requires no administrator rights. It creates no services, no drivers and no scheduled tasks. Its only registry write is `HKCU\Software\XXAR\InstallLocation`, used by the updater to recognize a managed install.

The purpose of the application is to replace audio inside locally installed games. To do so it rewrites Wwise audio archives (`.pck`, `.bnk`, `.wem`) inside the user's own game directory, which the user selects. Specifically, XXAR:

- modifies **data files only** — it never modifies, patches, or injects code into a game executable or a running process;
- does not interact with, disable, or circumvent anti-cheat software or any other security mechanism;
- contains no functionality intended to identify or exploit security vulnerabilities;
- preserves the original audio and can restore it. Every change is reversible from the application, and uninstalling removes the mod library.

## Uninstallation

`XXAR-Uninstall.exe` is installed alongside the application and registered in Windows "Apps & features". It removes the installed files and the registry key.

## Privacy

See [PRIVACY.md](PRIVACY.md). XXAR has no accounts, no analytics and no telemetry.

## Contact

Report abuse or Code of Conduct violations as described in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Report security issues privately through GitHub's security advisory form at [github.com/Entity378/XXAR/security/advisories/new](https://github.com/Entity378/XXAR/security/advisories/new). For anything else, open an issue at [github.com/Entity378/XXAR/issues](https://github.com/Entity378/XXAR/issues).
