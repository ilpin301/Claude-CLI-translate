"""Start with Windows: a value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run (no admin needed)."""
import logging
import ntpath
import os
import sys

log = logging.getLogger("cct.autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ClaudeCliTranslate"


def build_command(executable: str, project_dir: str) -> str:
    """Quoted command line that starts the app without a console window.

    python.exe is swapped for pythonw.exe; the app is started via run.pyw in the project folder.
    """
    folder, name = ntpath.split(executable)
    if name.lower() == "python.exe":
        name = "pythonw.exe"
    exe = ntpath.join(folder, name)
    return '"%s" "%s"' % (exe, ntpath.join(project_dir, "run.pyw"))


def _project_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("autostart state unreadable (%s)", type(exc).__name__)
        return False


def set_enabled(enabled: bool) -> bool:
    """Returns True when the registry now matches the request."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ,
                                  build_command(sys.executable, _project_dir()))
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        log.info("autostart %s", "enabled" if enabled else "disabled")
        return True
    except OSError as exc:
        log.warning("autostart change failed (%s)", type(exc).__name__)
        return False
