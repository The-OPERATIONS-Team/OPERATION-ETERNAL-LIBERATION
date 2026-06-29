"""Detailed per-file game verification report dialog."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTreeWidget, QTreeWidgetItem, QDialogButtonBox, QStyle,
)


def _fmt_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"


_STATUS_LABEL = {
    "ok": "OK",
    "mismatch": "MISMATCH",
    "missing": "MISSING",
    "unexpected": "unexpected file",
    "unconfigured": "not verified",
    "error": "read error",
}


class GameVerifyDialog(QDialog):
    """Detailed per-file hash / version / size report for the installed game."""

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Game file verification")
        self.resize(700, 460)
        lay = QVBoxLayout(self)

        title = result.title_id + (f" ({result.region})" if result.region else "")
        lay.addWidget(QLabel(f"Game: {title}"))
        found = ", ".join(f"{k} {v}" for k, v in result.version_found.items()) or "unknown"
        ver_line = QLabel(f"Game version (PARAM.SFO): {found}   |   expected {result.version_expected}")
        size_txt = _fmt_size(result.size_bytes)
        if result.size_expected:
            size_txt += f"   |   expected ~{_fmt_size(result.size_expected)}"
        size_line = QLabel(f"Approximate game size: {size_txt}")
        lay.addWidget(ver_line)
        lay.addWidget(size_line)

        warn_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("monospace")

        tree = QTreeWidget()
        tree.setColumnCount(4)
        tree.setHeaderLabels(["File", "Size", "SHA-256", "Status"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        for fr in result.files:
            item = QTreeWidgetItem([
                fr.rel,
                _fmt_size(fr.size) if fr.size else "",
                fr.sha256,
                _STATUS_LABEL.get(fr.status, fr.status),
            ])
            item.setFont(2, mono)
            if fr.status in ("mismatch", "missing", "error"):
                item.setIcon(3, warn_icon)
            tree.addTopLevelItem(item)
        tree.resizeColumnToContents(0)
        tree.resizeColumnToContents(1)
        lay.addWidget(tree, 1)

        if result.ok:
            summary = "All checks passed."
        else:
            summary = ("One or more checks failed. Reinstall the base game and every "
                       "update, in order, then verify again.")
        summary_line = QLabel(summary)
        summary_line.setWordWrap(True)
        if not result.ok:
            sw = QLabel()
            sw.setPixmap(warn_icon.pixmap(16, 16))
            srow = QHBoxLayout()
            srow.addWidget(sw)
            srow.addWidget(summary_line, 1)
            lay.addLayout(srow)
        else:
            lay.addWidget(summary_line)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)
