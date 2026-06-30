"""OP ETERNAL Launcher - OPERATION ETERNAL LIBERATION."""
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.paths import APP_ICON, _IS_WIN
from app.window import ACILauncher


def _set_taskbar_identity():
    """Give Windows an explicit AppUserModelID so the taskbar shows our icon
    and groups under us, not the bundled pythonw.exe."""
    if not _IS_WIN:
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("oel.launcher")
    except Exception:
        pass


def main():
    _set_taskbar_identity()
    app = QApplication(sys.argv)
    app.setApplicationName("OPERATION ETERNAL LIBERATION")
    if APP_ICON.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    window = ACILauncher()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
