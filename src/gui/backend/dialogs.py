# Content for every modal dialog raised through alertDialogRequested.
# Each function returns the (title, message, sticker_path) triple that signal expects.

from PyQt6.QtCore import QCoreApplication

import src.core.app_config as app_config
from src.core.app_config import APP_NAME

_MAX_LISTED_PCKS = 8


def permission_denied():
    return (
        QCoreApplication.translate("Application", "Permission Denied"),
        QCoreApplication.translate("Application", "%1 does not have permission to write to the game folder.\n\nTry one of the following:\n* Run %1 as Administrator\n* Repair your game files in the launcher").replace("%1", APP_NAME),
        "",
    )


def game_files_in_use():
    return (
        QCoreApplication.translate("Application", "Game Files In Use"),
        QCoreApplication.translate("Application", "%1 is holding its audio files open, so they cannot be written.\n\nClose the game completely, then try again.").replace("%1", app_config.GAME_NAME),
        "",
    )


def original_audio_missing(pck_names):
    listing = "\n".join(f"* {name}" for name in pck_names[:_MAX_LISTED_PCKS])
    if len(pck_names) > _MAX_LISTED_PCKS:
        listing += f"\n* ... +{len(pck_names) - _MAX_LISTED_PCKS}"
    return (
        QCoreApplication.translate("Application", "Original Audio Missing"),
        QCoreApplication.translate(
            "Application",
            "These mod targets do not exist in your game installation:\n%1\n\nThe game downloads content on demand, so this audio may simply not be downloaded yet.\n Download the missing content via the game itself upon logging in, or by using the game repair function in the launcher, then apply mods again."
        ).replace("%1", listing),
        "",
    )


def no_changes_to_show():
    return (
        QCoreApplication.translate("Application", "No Changes found"),
        QCoreApplication.translate("Application", "No audio replacements found.\n\nDid you even replace anything?"),
        f"../assets/{app_config.ASSETS_DIR}/EllenSleep.png",
    )


def no_manual_changes_to_show():
    return (
        QCoreApplication.translate("Application", "No Changes found"),
        QCoreApplication.translate("Application", "No manual audio replacements found.\n\nChanges from installed mods are managed in the Mod Manager."),
        f"../assets/{app_config.ASSETS_DIR}/EllenSleep.png",
    )


def no_streamed_pcks():
    return (
        QCoreApplication.translate("Application", "Missing Streaming Audio Files"),
        QCoreApplication.translate("Application", "No streamed PCK files were found in the game's audio folder.\n\n"
        "This means your game installation is incomplete or corrupted. "
        "Audio mods may not work correctly without these files.\n\n"
        "Please repair your game files through the game launcher."),
        "",
    )


def damaged_streamed_pcks(problem_details):
    return (
        QCoreApplication.translate("Application", "Missing Streaming Audio Files"),
        problem_details + "\n\n" +
        QCoreApplication.translate("Application", "Your game installation may be incomplete or corrupted. "
        "Some audio mods may not work correctly without these files.\n\n"
        "Please repair your game files through the game launcher."),
        "",
    )


def write_in_progress():
    return (
        QCoreApplication.translate("Application", "Operation In Progress"),
        QCoreApplication.translate("Application", "%1 is still writing game files.\n\nWait for the current operation to finish, then try again.").replace("%1", APP_NAME),
        "",
    )
