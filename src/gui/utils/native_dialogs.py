import sys
import subprocess
import os
from pathlib import Path
from PyQt5.QtWidgets import QFileDialog
from src.gui.utils.path_memory import get_last_dir, save_last_dir
from src.core.subprocess_utils import IS_LINUX, is_frozen

from src.core.logger import get_logger
logger = get_logger(__name__)

class NativeDialogs:
    @staticmethod
    def _is_linux():
        return IS_LINUX

    @staticmethod
    def _get_clean_env():
        # PyInstaller's LD_LIBRARY_PATH points at bundled libs and crashes system GTK apps.
        # Restore the original so zenity etc. find their own libs.
        env = os.environ.copy()
        if is_frozen():
            orig = env.get('LD_LIBRARY_PATH_ORIG')
            if orig is not None:
                env['LD_LIBRARY_PATH'] = orig
            else:
                env.pop('LD_LIBRARY_PATH', None)
        return env

    @staticmethod
    def _zenity_available():

        try:
            subprocess.run(
                ["zenity", "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                env=NativeDialogs._get_clean_env(),
            )
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False
        except Exception as e:
            logger.error(f"Zenity check error: {e}")
            return False

    @staticmethod
    def _run_zenity(args):

        try:
            cmd = ["zenity"] + args
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=NativeDialogs._get_clean_env(),
            )
            if result.returncode == 0:
                return (True, result.stdout.strip())
            return (True, None)
        except Exception as e:
            logger.error(f"Native dialog error: {e}")
            return (False, None)

    @staticmethod
    def _parse_qt_filters(filter_str):


        zenity_args = []
        if not filter_str:
            return zenity_args

        filters = filter_str.split(";;")
        for f in filters:
            f = f.strip()
            if not f:
                continue

            if "(" in f and ")" in f:
                name = f.split("(")[0].strip()
                patterns = f.split("(")[1].split(")")[0]
                zenity_args.append(f"--file-filter={name} | {patterns}")
            else:

                zenity_args.append(f"--file-filter={f} | {f}")

        return zenity_args

    @staticmethod
    def _resolve_start_dir(start_dir, remember_key, default_filename=None):
        if remember_key:
            remembered = get_last_dir(remember_key, fallback=None)
            if remembered:
                if default_filename:
                    return str(Path(remembered) / default_filename)
                return remembered
        return start_dir or ""

    @staticmethod
    def get_open_file(title="Open File", start_dir=None, filter_str="", remember_key=None):
        start_dir = NativeDialogs._resolve_start_dir(start_dir, remember_key)

        if NativeDialogs._is_linux() and NativeDialogs._zenity_available():
            args = ["--file-selection", f"--title={title}"]
            if start_dir:
                args.append(f"--filename={start_dir}/")

            args.extend(NativeDialogs._parse_qt_filters(filter_str))

            success, res = NativeDialogs._run_zenity(args)
            if success:
                path = res if res else ""
                if path and remember_key:
                    save_last_dir(remember_key, path)
                return path

        path, _ = QFileDialog.getOpenFileName(None, title, start_dir or "", filter_str)
        if path and remember_key:
            save_last_dir(remember_key, path)
        return path

    @staticmethod
    def get_open_files(title="Select Files", start_dir=None, filter_str="", remember_key=None):
        start_dir = NativeDialogs._resolve_start_dir(start_dir, remember_key)

        if NativeDialogs._is_linux() and NativeDialogs._zenity_available():
            args = [
                "--file-selection",
                "--multiple",
                "--separator=|",
                f"--title={title}",
            ]
            if start_dir:
                args.append(f"--filename={start_dir}/")

            args.extend(NativeDialogs._parse_qt_filters(filter_str))

            success, res = NativeDialogs._run_zenity(args)
            if success:
                paths = res.split("|") if res else []
                if paths and remember_key:
                    save_last_dir(remember_key, paths[0])
                return paths

        paths, _ = QFileDialog.getOpenFileNames(
            None, title, start_dir or "", filter_str
        )
        if paths and remember_key:
            save_last_dir(remember_key, paths[0])
        return paths

    @staticmethod
    def get_directory(title="Select Directory", start_dir=None, remember_key=None):
        start_dir = NativeDialogs._resolve_start_dir(start_dir, remember_key)

        if NativeDialogs._is_linux() and NativeDialogs._zenity_available():
            args = ["--file-selection", "--directory", f"--title={title}"]
            if start_dir:
                args.append(f"--filename={start_dir}/")

            success, res = NativeDialogs._run_zenity(args)
            if success:
                path = res if res else ""
                if path and remember_key:
                    save_last_dir(remember_key, path)
                return path

        path = QFileDialog.getExistingDirectory(None, title, start_dir or "")
        if path and remember_key:
            save_last_dir(remember_key, path)
        return path

    @staticmethod
    def get_save_file(title="Save File", start_dir=None, filter_str="", remember_key=None, default_filename=None):
        # Save dialogs receive a full path; if remember_key is set, split into remembered dir + filename.
        if remember_key and start_dir and not default_filename:
            try:
                p = Path(start_dir)
                if p.suffix or not p.is_dir():
                    default_filename = p.name
            except Exception:
                pass
        start_dir = NativeDialogs._resolve_start_dir(start_dir, remember_key, default_filename)

        if NativeDialogs._is_linux() and NativeDialogs._zenity_available():
            args = [
                "--file-selection",
                "--save",
                "--confirm-overwrite",
                f"--title={title}",
            ]
            if start_dir:
                args.append(f"--filename={start_dir}")

            args.extend(NativeDialogs._parse_qt_filters(filter_str))

            success, res = NativeDialogs._run_zenity(args)
            if success:
                path = res if res else ""
                if path and remember_key:
                    save_last_dir(remember_key, path)
                return path

        path, _ = QFileDialog.getSaveFileName(None, title, start_dir or "", filter_str)
        if path and remember_key:
            save_last_dir(remember_key, path)
        return path
