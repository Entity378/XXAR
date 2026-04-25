#!/bin/bash
# XXAR Flatpak wrapper.
# The PyInstaller onefolder bundle lives at /app/share/xxar/. This script
# sets up the runtime environment so the bundled binary can find ffmpeg,
# vgmstream-cli, GStreamer plugins, and the system Wayland/EGL stack.

set -e

APPDIR="/app/share/xxar"

# ── FFmpeg extension (mounted at /app/lib/ffmpeg) ──
if [ -d "/app/lib/ffmpeg/bin" ]; then
    export PATH="/app/lib/ffmpeg/bin:$PATH"
fi

# ── vgmstream-cli (built by the manifest into /app/bin) ──
export PATH="/app/bin:$PATH"

# ── GStreamer ──
# Use the runtime's GStreamer, not anything PyInstaller might have bundled.
export GST_PLUGIN_SYSTEM_PATH="/usr/lib/x86_64-linux-gnu/gstreamer-1.0"
unset GST_PLUGIN_PATH

# ── Qt platform ──
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"

# ── Library paths ──
# Prepend runtime libs so system libwayland/libssl/libcrypto take priority over
# anything PyInstaller bundled — bundled libwayland from the build distro
# breaks EGL on the user's compositor.
export LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/app/lib/ffmpeg/lib:${LD_LIBRARY_PATH}"

# ── Flatpak flag ──
# Tells the app it is running in a Flatpak (gates self-update path,
# subprocess spawning, tool install locations).
export XXAR_FLATPAK=1

# ── Launch ──
cd "$APPDIR"
exec "$APPDIR/XXAR" "$@"
