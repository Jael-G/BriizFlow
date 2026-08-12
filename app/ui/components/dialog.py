"""ConfirmDialog — the modal confirmation used by the Models page delete flow.

Replaces qfluentwidgets' ``MessageBox`` with the same call pattern::

    dlg = ConfirmDialog(title, message, confirm_text="Delete")
    dlg.yesSignal.connect(self._do_delete)
    dlg.exec()

``yesSignal`` fires (then the dialog closes with ``Accepted``) when the
confirm button is clicked; ``rejectSignal`` mirrors it for the cancel path.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

from app.ui.components.button import Button
from app.ui.components.labels import BodyStrong, Caption


class ConfirmDialog(QDialog):
    """A minimal modal confirm/cancel dialog."""

    yesSignal = Signal()
    rejectSignal = Signal()

    def __init__(self, title, message, confirm_text="Delete", cancel_text="Cancel", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)

        layout.addWidget(BodyStrong(title))
        layout.addWidget(Caption(message))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = Button(cancel_text)
        self.confirm_btn = Button(confirm_text, variant="danger")
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.confirm_btn)
        layout.addSpacing(6)
        layout.addLayout(buttons)

        self.cancel_btn.clicked.connect(self._on_cancel)
        self.confirm_btn.clicked.connect(self._on_confirm)

    def _on_cancel(self):
        self.rejectSignal.emit()
        self.reject()

    def _on_confirm(self):
        self.yesSignal.emit()
        self.accept()
