"""OP ETERNAL Launcher - OPERATION ETERNAL LIBERATION."""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.window import ACILauncher


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OPERATION ETERNAL LIBERATION")
    window = ACILauncher()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
