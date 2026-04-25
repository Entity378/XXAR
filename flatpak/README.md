# XXAR Flatpak

This directory contains the Flatpak packaging for XXAR. The bundle wraps the
PyInstaller onefolder output (`dist/XXAR/`) with a small set of system
dependencies (vgmstream-cli, the freedesktop FFmpeg extension) and the KDE
Platform 5.15 runtime.

## Files

| File                                     | Purpose                                       |
| ---------------------------------------- | --------------------------------------------- |
| `io.github.Entity378.XXAR.yml`           | flatpak-builder manifest                      |
| `io.github.Entity378.XXAR.desktop`       | Desktop entry                                 |
| `io.github.Entity378.XXAR.metainfo.xml`  | AppStream metadata                            |
| `xxar-wrapper.sh`                        | Launcher (sets `XXAR_FLATPAK=1`, env vars)    |

## Build (locally)

```bash
# 1. Build the PyInstaller bundle. The XXAR_FLATPAK_BUILD=1 flag tells the
#    spec to skip GStreamer/Qt plugin bundling — the runtime supplies them.
XXAR_FLATPAK_BUILD=1 pyinstaller --noconfirm --clean XXAR.spec

# 2. Install the runtime + SDK once.
flatpak install --user -y flathub \
    org.kde.Platform//5.15-24.08 \
    org.kde.Sdk//5.15-24.08 \
    org.freedesktop.Platform.ffmpeg-full//24.08

# 3. Build + install the Flatpak.
flatpak-builder --user --install --force-clean \
    build-dir flatpak/io.github.Entity378.XXAR.yml

# 4. Run.
flatpak run io.github.Entity378.XXAR
```

## Build a redistributable single-file bundle

```bash
flatpak-builder --force-clean --repo=repo \
    build-dir flatpak/io.github.Entity378.XXAR.yml

flatpak build-bundle repo \
    XXAR-linux-x86_64.flatpak \
    io.github.Entity378.XXAR
```

The resulting `XXAR-linux-x86_64.flatpak` is the file the auto-updater looks
for in GitHub releases (see `src/gui/backend/update_manager_bridge.py`).

## Auto-update

When XXAR runs inside the Flatpak sandbox, the in-app update flow:

1. Polls `https://api.github.com/repos/Entity378/XXAR/releases/latest` for a
   newer version.
2. Downloads the `XXAR-linux-x86_64.flatpak` release asset to
   `~/.var/app/io.github.Entity378.XXAR/cache/updates/`.
3. Spawns `flatpak-spawn --host flatpak install --user --bundle --assumeyes
   <file>` to reinstall in place. The host `flatpak` rewrites the OSTree ref
   while the running app keeps using the old commit.
4. Asks the user to restart. The next `flatpak run` picks up the new commit.

The `--talk-name=org.freedesktop.Flatpak` finish-arg in the manifest is what
allows the in-sandbox process to invoke `flatpak install` on the host.
