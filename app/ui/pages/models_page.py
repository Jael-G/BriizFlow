"""Models page: curated Whisper models with download / activate / delete.

Downloads stream through the page's own :class:`ModelManager` (real
``QNetworkAccessManager``), one card per curated model. A downloaded model is
auto-activated; deleting the active model clears the selection.
"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.models.manager import (
    CURATED_MODELS,
    ModelManager,
    delete,
    installed_models,
)
from app.ui.components.button import Button
from app.ui.components.card import Badge, ModelCard, format_size
from app.ui.components.dialog import ConfirmDialog
from app.ui.components.labels import Title
from app.ui.components.progress import ProgressBar
from app.ui.components.toast import show_toast
from app.ui.icons import icon
from app.ui.layouts.page_scroll import PageScroll

log = logging.getLogger(__name__)


class ModelsPage(PageScroll):
    """Curated model list with download/activate/delete and auto-activation."""

    settings_saved = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._manager = ModelManager(self)
        self._cards = {}
        self._downloading = set()

        # Header: page title with a refresh button on the right, so the user
        # can re-scan the models folder after changing it outside the app.
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        header_layout.addWidget(Title("Models"))
        header_layout.addStretch(1)
        self.refresh_btn = Button("Refresh")
        self.refresh_btn.setIcon(icon("refresh-cw", 16))
        self.refresh_btn.clicked.connect(self._refresh)
        header_layout.addWidget(self.refresh_btn)
        self.add(header)

        self.add_subtitle(
            "Download and activate a Whisper model. Models are fetched from "
            "the official whisper.cpp repository."
        )

        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self.add(self._list)

        self._manager.download_progress.connect(self._on_progress)
        self._manager.download_finished.connect(self._on_download_finished)
        self._manager.download_failed.connect(self._on_download_failed)

        self._refresh()

    # --- building ----------------------------------------------------------
    def _refresh(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()
        installed = {m["name"]: m for m in installed_models()}
        active = self._settings.get("model_name")
        # If the active model's file was removed outside the app, clear the
        # selection so the UI doesn't point at a model that no longer exists.
        if active and active not in installed:
            log.warning("Active model %r is no longer on disk; clearing selection", active)
            self._settings.set("model_name", "")
            self._settings.save()
            self.settings_saved.emit("model_name")
            active = ""

        # --- Downloaded section -------------------------------------------
        self._list_layout.addWidget(self._make_section_header("Downloaded"))
        downloaded = [info for info in CURATED_MODELS if info["name"] in installed]
        if downloaded:
            for info in downloaded:
                name = info["name"]
                card = ModelCard(name, installed[name]["size_mb"])
                self._list_layout.addWidget(card)
                self._cards[name] = card
                self._wire_installed(card, name, installed[name])
        else:
            empty = QLabel("No models downloaded yet.")
            empty.setObjectName("caption")
            self._list_layout.addWidget(empty)

        # --- Available section ---------------------------------------------
        self._list_layout.addWidget(self._make_section_header("Available"))
        for info in CURATED_MODELS:
            name = info["name"]
            if name in installed:
                continue
            card = ModelCard(name, info["size_mb"])
            self._list_layout.addWidget(card)
            self._cards[name] = card
            self._wire_available(card, name)

        # Re-show any in-flight downloads whose cards were just rebuilt, so a
        # finished sibling download doesn't make a live one disappear.
        for name in list(self._downloading):
            card = self._cards.get(name)
            if card is not None:
                self._show_downloading(card, name)

        if active in self._cards:
            self._mark_active(active)

    @staticmethod
    def _make_section_header(title):
        header = QLabel(title)
        header.setObjectName("groupHeader")
        return header

    def _wire_installed(self, card, name, info):
        card.size_label.setText(format_size(info["size_mb"]))

        set_btn = Button("Set Active", variant="success")
        card.set_active_btn = set_btn
        card.actions.addWidget(set_btn)
        set_btn.clicked.connect(lambda: self._activate(name))

        # The word "Active" replaces the Set Active button in place once this
        # model is activated. It reserves the button's exact width so the
        # right-hand column stays aligned across all model cards.
        badge = Badge("Active")
        badge.hide()
        badge.setMinimumWidth(set_btn.sizeHint().width())
        badge.setAlignment(Qt.AlignCenter)
        card.active_badge = badge
        card.actions.addWidget(badge)

        remove_btn = Button("Remove", variant="danger")
        card.remove_btn = remove_btn
        card.actions.addWidget(remove_btn)
        remove_btn.clicked.connect(lambda: self._confirm_delete(name))

    def _wire_available(self, card, name):
        # Layout: [progress bar][Cancel][Download]. On download the Download
        # button is replaced in place by the red Cancel button, with the green
        # progress bar expanding to its left.
        bar = ProgressBar()
        bar.hide()
        bar.setRange(0, 100)
        bar.setMinimumWidth(150)
        from PySide6.QtWidgets import QSizePolicy

        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.progress_bar = bar
        card.actions.addWidget(bar)

        cancel_btn = Button("Cancel", variant="danger")
        cancel_btn.hide()
        card.cancel_btn = cancel_btn
        card.actions.addWidget(cancel_btn)
        cancel_btn.clicked.connect(lambda: self._cancel_download(name))

        download_btn = Button("Download", variant="primary")
        card.download_btn = download_btn
        card.actions.addWidget(download_btn)
        download_btn.clicked.connect(lambda: self._start_download(name))

    def _mark_active(self, name):
        card = self._cards.get(name)
        if card is None:
            return
        if card.set_active_btn is not None:
            card.set_active_btn.hide()
        if card.active_badge is not None:
            card.active_badge.show()

    # --- actions -----------------------------------------------------------
    def _activate(self, name):
        self._settings.set("model_name", name)
        self._settings.save()
        self._refresh()
        self.settings_saved.emit("model_name")

    def _start_download(self, name):
        if name in self._downloading:
            return  # already downloading — never start a duplicate
        card = self._cards.get(name)
        if card is None or not card.download_btn:
            return
        self._downloading.add(name)
        if not self._manager.download(name):
            # Rejected (e.g. a stale duplicate); keep the card idle.
            self._downloading.discard(name)
            return
        self._show_downloading(card, name)

    def _show_downloading(self, card, name):
        """Switch a card into the downloading state, restoring progress."""
        if card.download_btn is not None:
            card.download_btn.hide()
        if card.cancel_btn is not None:
            card.cancel_btn.show()
        if card.progress_bar is not None:
            card.progress_bar.show()
            progress = self._manager.progress_of(name)
            if progress:
                received, total = progress
                if total > 0:
                    card.progress_bar.setRange(0, total)
                    card.progress_bar.setValue(received)

    def _cancel_download(self, name):
        self._manager.cancel(name)
        self._downloading.discard(name)
        card = self._cards.get(name)
        if card is not None:
            card.progress_bar.hide()
            card.cancel_btn.hide()
            card.download_btn.show()

    def _confirm_delete(self, name):
        card = self._cards.get(name)
        label = card.name_label.text() if card else name
        dlg = ConfirmDialog(
            "Remove model",
            'This deletes "%s" from disk. This cannot be undone.' % label,
            confirm_text="Remove",
        )
        dlg.yesSignal.connect(lambda: self._do_delete(name))
        dlg.exec()

    def _do_delete(self, name):
        was_active = self._settings.get("model_name") == name
        if delete(name):
            if was_active:
                self._settings.set("model_name", "")
                self._settings.save()
                self.settings_saved.emit("model_name")
            self._downloading.discard(name)
            show_toast(self, "info", "Model removed", "%s was deleted." % name)
            self._refresh()
        else:
            show_toast(self, "error", "Could not remove the model", "The file is missing or locked.")

    # --- download events ---------------------------------------------------
    def _on_progress(self, name, received, total):
        card = self._cards.get(name)
        if card is None or card.progress_bar is None:
            return
        if total > 0:
            card.progress_bar.setRange(0, total)
            card.progress_bar.setValue(received)

    def _on_download_finished(self, name, path):
        self._downloading.discard(name)
        card = self._cards.get(name)
        if card is not None:
            if card.progress_bar is not None:
                card.progress_bar.hide()
            if card.cancel_btn is not None:
                card.cancel_btn.hide()
        # Auto-activate the freshly downloaded model.
        self._settings.set("model_name", name)
        self._settings.save()
        self._refresh()
        self.settings_saved.emit("model_name")

    def _on_download_failed(self, name, error):
        self._downloading.discard(name)
        card = self._cards.get(name)
        if card is not None:
            if card.progress_bar is not None:
                card.progress_bar.hide()
            if card.cancel_btn is not None:
                card.cancel_btn.hide()
            if card.download_btn is not None:
                card.download_btn.show()
        show_toast(self, "error", "Download failed", error)
