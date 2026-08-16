"""Settings page: grouped settings with instant apply.

Every row persists immediately through the shared
:class:`app.config.settings.Settings` instance (no Save/Cancel button) and
emits ``settings_saved(key)`` so the controller only re-wires what actually
changed (injector rebuild, hotkey re-registration).
"""

import logging
import os
import shutil

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog

from app.audio.recorder import list_input_devices
from app.config.credentials import CredentialStoreError, get_default_store
from app.config.settings import default_recordings_dir, xdg_config_home
from app.transcription.models import model_id_for_label, model_label_for_id, model_labels
from app.ui.components.button import Button
from app.ui.components.dialog import ConfirmDialog
from app.ui.components.fields import ComboBox, HotkeyCapture, PasswordField, TextField
from app.ui.components.labels import Caption
from app.ui.components.setting_row import SettingGroup, SettingRow
from app.ui.components.toast import show_toast
from app.ui.components.toggle import ToggleSwitch
from app.ui.layouts.page_scroll import PageScroll
from app.util import normalize_combo

log = logging.getLogger(__name__)
LANGUAGES = [
    "auto", "en", "es", "fr", "de", "it", "pt", "ru",
    "nl", "pl", "uk", "ja", "zh", "ko", "ar", "hi",
]
PASTE_BACKENDS = ["auto", "x11", "wayland"]

# Speech Cleanup: persisted value -> (display label, short description). The
# label is what the dropdown shows; the description explains the selected
# level on the row. "none" keeps the transcript exactly as the engine
# returned it; "clean" is the mildest post-processing and the default once
# any cleanup is selected. Keep these one-liners — they render under the
# Cleanup level row, not the full feature spec.
SPEECH_CLEANUP_OPTIONS = [
    ("none", "None", "No post-processing."),
    ("clean", "Clean", "Removes filler words, stutters, and false starts."),
    ("polish", "Polish", "Cleans the text and makes it read naturally."),
    ("compact", "Compact", "Makes the transcript substantially more concise."),
]

CLEANUP_ROW_DESCRIPTION = "Clean up the transcript with a small GPT model before it's pasted (requires API key)."


def cleanup_level_description(value):
    """The row's description text for a cleanup level: the feature blurb plus
    the selected mode's short explanation, with the mode name emboldened."""
    for level, label, description in SPEECH_CLEANUP_OPTIONS:
        if level == value:
            return "%s<br/><b>%s</b>: %s" % (
                CLEANUP_ROW_DESCRIPTION,
                label,
                description,
            )
    return CLEANUP_ROW_DESCRIPTION


class SettingsPage(PageScroll):
    """Grouped settings with instant apply; emits ``settings_saved(key)``."""

    settings_saved = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._key_field = None
        self.add_title("Settings")
        self.add_subtitle("Changes apply instantly.")

        self._build_general()
        self._build_input()
        self._build_recording()
        self._build_online()
        self._build_startup()
        # Breathe at the bottom so the last group doesn't hug the window edge.
        self.add_spacing(56)

    # --- helpers -----------------------------------------------------------
    def _persist(self, key, value):
        self._settings.set(key, value)
        self._settings.save()
        self.settings_saved.emit(key)

    def _add_group(self, title):
        group = SettingGroup(title)
        self.add(group)
        return group

    def _add_row(self, group, title, description=None, icon=None):
        row = SettingRow(title, description, icon_name=icon)
        group.add_row(row)
        return row

    # --- sections ----------------------------------------------------------
    def _build_general(self):
        group = self._add_group("General")

        row = self._add_row(group, "Dictation hotkey", "Press this anywhere to start/stop dictation.", "keyboard")
        self._hotkey_edit = HotkeyCapture(self._settings.get("hotkey") or "ctrl+shift+space")
        self._hotkey_edit.setFixedWidth(180)
        self._hotkey_edit.captured.connect(self._on_hotkey_captured)
        row.add_widget(self._hotkey_edit)

        row = self._add_row(group, "Microphone", "Leave as default to use the system input.", "mic")
        self._mic_combo = ComboBox()
        self._mic_combo.addItem("Default (system input)", None)
        for dev in list_input_devices() or []:
            self._mic_combo.addItem(dev["name"], dev["name"])
        current = self._settings.get("mic_device")
        idx = self._mic_combo.findData(current)
        if idx >= 0:
            self._mic_combo.setCurrentIndex(idx)
        self._mic_combo.currentIndexChanged.connect(self._on_mic_changed)
        row.add_widget(self._mic_combo)

        row = self._add_row(group, "Language", "The spoken language of your dictations.", "languages")
        self._lang_combo = ComboBox()
        for lang in LANGUAGES:
            self._lang_combo.addItem(lang, lang)
        lang = (self._settings.get("whisper_language") or "auto").lower()
        idx = self._lang_combo.findData(lang)
        self._lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        row.add_widget(self._lang_combo)

    def _build_input(self):
        group = self._add_group("Text input")

        row = self._add_row(group, "Paste backend", "Auto picks X11 or Wayland for your session.", "clipboard")
        self._paste_combo = ComboBox()
        for backend in PASTE_BACKENDS:
            self._paste_combo.addItem(backend, backend)
        backend = (self._settings.get("paste_backend") or "auto").lower()
        idx = self._paste_combo.findData(backend)
        self._paste_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._paste_combo.currentIndexChanged.connect(self._on_paste_backend_changed)
        row.add_widget(self._paste_combo)

        row = self._add_row(group, "Paste shortcut", "Terminals often need Ctrl+Shift+V.", "clipboard-paste")
        self._paste_edit = HotkeyCapture(self._settings.get("paste_shortcut") or "ctrl+v")
        self._paste_edit.setFixedWidth(160)
        self._paste_edit.captured.connect(self._on_paste_shortcut_captured)
        row.add_widget(self._paste_edit)

        row = self._add_row(group, "Restore clipboard", "Put the previous clipboard content back after pasting.", "rotate-ccw-clock")
        toggle = ToggleSwitch()
        toggle.setChecked(bool(self._settings.get("restore_clipboard")))
        toggle.checkedChanged.connect(lambda v: self._persist("restore_clipboard", v))
        row.add_widget(toggle)

    def _build_recording(self):
        group = self._add_group("Recording")

        row = self._add_row(group, "Recording chimes", "Play a sound when recording starts and stops.", "bell")
        toggle = ToggleSwitch()
        toggle.setChecked(bool(self._settings.get("recording_chimes")))
        toggle.checkedChanged.connect(lambda v: self._persist("recording_chimes", v))
        row.add_widget(toggle)

        row = self._add_row(group, "Save recordings", "Keep a copy of each dictation on disk.", "save")
        toggle = ToggleSwitch()
        toggle.setChecked(bool(self._settings.get("save_recordings")))
        toggle.checkedChanged.connect(self._on_save_recordings_changed)
        row.add_widget(toggle)

        row = self._add_row(group, "Recordings folder", "Where saved recordings are written.", "folder")
        current_dir = self._settings.get("recordings_dir") or default_recordings_dir()
        self._recordings_edit = TextField(current_dir)
        self._recordings_edit.setFixedWidth(260)
        self._recordings_browse_btn = Button("Browse…")
        self._recordings_browse_btn.clicked.connect(self._on_browse_recordings)
        row.add_widget(self._recordings_edit)
        row.add_widget(self._recordings_browse_btn)

    def _build_online(self):
        group = self._add_group("OpenAI features")

        row = self._add_row(
            group,
            "Online transcription",
            "Transcribe audio with OpenAI's online models (requires API key).",
            "cloud",
        )
        self._online_toggle = ToggleSwitch()
        self._online_toggle.setChecked(bool(self._settings.get("online_transcription_enabled")))
        self._online_toggle.checkedChanged.connect(self._on_online_toggled)
        row.add_widget(self._online_toggle)

        row = self._add_row(group, "Transcription model", "The OpenAI transcription model to use.", "zap")
        self._model_combo = ComboBox()
        for label in model_labels():
            self._model_combo.addItem(label, label)
        # Select the persisted model rather than defaulting to the first entry.
        saved = self._settings.get("openai_model")
        label = model_label_for_id(saved) if saved else None
        idx = self._model_combo.findData(label) if label else -1
        self._model_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        row.add_widget(self._model_combo)

        # The row shows the feature blurb plus whichever level is selected;
        # the description updates as the user changes the dropdown.
        row = self._add_row(
            group,
            "Cleanup level",
            icon="brush-cleaning",
        )
        self._cleanup_combo = ComboBox()
        for value, label, _description in SPEECH_CLEANUP_OPTIONS:
            self._cleanup_combo.addItem(label, value)
        current = (self._settings.get("speech_cleanup") or "none").lower()
        idx = self._cleanup_combo.findData(current)
        self._cleanup_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._cleanup_combo.currentIndexChanged.connect(self._on_cleanup_changed)
        row.add_widget(self._cleanup_combo)

        self._cleanup_row = row
        self._update_cleanup_description(self._cleanup_combo.currentData() or "none")

        row = self._add_row(group, "API key", "Stored in your system keyring, never in settings.", "key")
        self._key_field = PasswordField("", "••••••••")
        self._key_field.setFixedWidth(220)
        self._save_btn = Button("Save", variant="primary")
        self._delete_btn = Button("Delete", variant="danger")
        self._save_btn.clicked.connect(self._save_key)
        self._delete_btn.clicked.connect(self._delete_key)
        row.add_widget(self._key_field)
        row.add_widget(self._save_btn)
        row.add_widget(self._delete_btn)

    def _build_startup(self):
        group = self._add_group("Startup")
        row = self._add_row(group, "Start on login", "Launch BriizFlow when you sign in.", "power")
        toggle = ToggleSwitch()
        toggle.setChecked(bool(self._settings.get("start_on_login")))
        toggle.checkedChanged.connect(self._on_startup_toggled)
        row.add_widget(toggle)

    # --- handlers ----------------------------------------------------------
    def _on_hotkey_captured(self, combo):
        self._persist("hotkey", combo)

    def _on_mic_changed(self, _index):
        self._persist("mic_device", self._mic_combo.currentData() or "")

    def _on_lang_changed(self, _index):
        self._persist("whisper_language", self._lang_combo.currentData() or "auto")

    def _on_paste_backend_changed(self, _index):
        self._persist("paste_backend", self._paste_combo.currentData() or "auto")

    def _on_paste_shortcut_captured(self, combo):
        self._persist("paste_shortcut", combo)

    def _on_save_recordings_changed(self, value):
        self._persist("save_recordings", value)

    def _on_browse_recordings(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Choose recordings folder", self._recordings_edit.text() or os.path.expanduser("~")
        )
        if directory:
            self._recordings_edit.setText(directory)
            self._persist("recordings_dir", directory)

    def _on_online_toggled(self, value):
        # Toggling online never touches the stored API key; it only persists
        # the setting.
        self._persist("online_transcription_enabled", value)

    def _on_model_changed(self, _index):
        label = self._model_combo.currentData()
        model_id = model_id_for_label(label)
        if model_id:
            self._persist("openai_model", model_id)

    def _on_cleanup_changed(self, _index):
        value = self._cleanup_combo.currentData() or "none"
        self._persist("speech_cleanup", value)
        self._update_cleanup_description(value)

    def _update_cleanup_description(self, value):
        """Show which cleanup level is selected, under the row's feature blurb."""
        self._cleanup_row.set_description(cleanup_level_description(value))

    def _on_startup_toggled(self, value):
        self._persist("start_on_login", value)
        self._apply_autostart(value)

    # --- API key -----------------------------------------------------------
    def _save_key(self):
        value = self._key_field.text().strip()
        if not value:
            return  # blank input never saves or deletes
        try:
            get_default_store().set(value)
            self._key_field.clear()
            self._key_field.setPlaceholderText("••••••••")
            show_toast(self, "success", "API key saved", "Stored in your keyring.")
            self.settings_saved.emit("openai_api_key")
        except CredentialStoreError as exc:
            show_toast(self, "error", "Could not save the key", str(exc))

    def _delete_key(self):
        # Deleting is destructive and only happens on explicit confirmation.
        dlg = ConfirmDialog(
            "Delete API key",
            "This removes the key from your system keyring.",
            confirm_text="Delete",
        )
        dlg.yesSignal.connect(self._do_delete_key)
        dlg.exec()

    def _do_delete_key(self):
        try:
            get_default_store().delete()
            self._key_field.clear()
            show_toast(self, "info", "API key deleted", "Removed from your keyring.")
            self.settings_saved.emit("openai_api_key")
        except CredentialStoreError as exc:
            show_toast(self, "error", "Could not delete the key", str(exc))

    # --- autostart ---------------------------------------------------------
    def _apply_autostart(self, enabled):
        autostart_dir = os.path.join(xdg_config_home(), "autostart")
        os.makedirs(autostart_dir, exist_ok=True)
        path = os.path.join(autostart_dir, "briizflow.desktop")
        if enabled:
            exec_path = shutil.which("briizflow") or os.path.abspath(
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "briizflow")
            )
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=BriizFlow\n"
                "Comment=Voice-to-text dictation\n"
                "Exec=%s\n"
                "X-GNOME-Autostart-enabled=true\n"
                "Terminal=false\n" % exec_path
            )
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
            except OSError as exc:
                log.warning("Could not write autostart entry: %s", exc)
                show_toast(self, "error", "Could not enable autostart", str(exc))
        else:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                log.warning("Could not remove autostart entry: %s", exc)
