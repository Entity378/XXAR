import sys
import os

block_cipher = None

# Small one-shot helper: onefile is fine here (run once per update, no
# startup-time sensitivity). Keeps deployment to a single artifact in
# Resources/Updater/.

a = Analysis(
    ['XXAR_Updater.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # This helper uses only stdlib — strip everything heavy that
        # PyInstaller hooks might otherwise auto-collect.
        'PyQt6',
        'numpy',
        'scipy',
        'PIL',
        'tkinter',
        'cryptography',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon_file = '../src/gui/assets/XXAR/XXAR-Logo2.ico' if sys.platform.startswith('win') else None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='XXAR Updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)
