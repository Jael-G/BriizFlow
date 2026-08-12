"""UI tests: theme, icons, components, settings page, models page, toasts."""

import os
import tempfile

import pytest
from PySide6.QtCore import QPoint

from app.config.credentials import CredentialStoreError
from app.transcription.models import model_labels


# --------------------------------------------------------------------------
# Theme / icons
# --------------------------------------------------------------------------
def test_apply_theme_sets_stylesheet(qt_app):
    from app.ui.theme import apply_theme

    apply_theme(qt_app)
    assert qt_app.styleSheet()


def test_icons_render(qt_app):
    from app.ui.icons import icon

    for name in ("settings", "cpu", "mic", "key"):
        assert not icon(name, 16).isNull()


def test_toggle_whole_pill_is_clickable(qt_app):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from app.ui.components.toggle import ToggleSwitch

    toggle = ToggleSwitch()
    toggle.setChecked(False)
    # The whole pill must respond, not just the left edge.
    QTest.mouseClick(toggle, Qt.LeftButton, pos=toggle.rect().center())
    assert toggle.isChecked()
    QTest.mouseClick(toggle, Qt.LeftButton, pos=toggle.rect().bottomRight() - QPoint(2, 2))
    assert not toggle.isChecked()
    QTest.mouseClick(toggle, Qt.LeftButton, pos=QPoint(toggle.rect().right() - 1, toggle.rect().center().y()))
    assert toggle.isChecked()
    # Hovering shows a clickable (pointing-hand) cursor.
    assert toggle.cursor().shape() == Qt.PointingHandCursor


def test_toggle_animates_both_directions(qt_app):
    from app.ui.components.toggle import ToggleSwitch

    toggle = ToggleSwitch()
    # Turning ON slides from the OFF position (0 -> 1), not a snap.
    toggle._animate_to(True)
    assert toggle._anim.startValue() == 0.0
    assert toggle._anim.endValue() == 1.0
    # Turning OFF slides from the current ON position (1 -> 0).
    toggle._knob_x = 1.0
    toggle._animate_to(False)
    assert toggle._anim.startValue() == 1.0
    assert toggle._anim.endValue() == 0.0


def test_hotkey_capture_records_combo(qt_app):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from app.ui.components.fields import HotkeyCapture

    field = HotkeyCapture("ctrl+shift+space")
    assert field.combo() == "ctrl+shift+space"
    assert field.text() == "Ctrl+Shift+Space"

    captured = []
    field.captured.connect(captured.append)
    field._begin_capture()

    ctrl = QKeyEvent(QEvent.KeyPress, Qt.Key_Control, Qt.ControlModifier)
    shift = QKeyEvent(QEvent.KeyPress, Qt.Key_Shift, Qt.ControlModifier | Qt.ShiftModifier)
    a = QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.ControlModifier | Qt.ShiftModifier)
    field.keyPressEvent(ctrl)
    field.keyPressEvent(shift)
    field.keyPressEvent(a)

    assert captured == ["ctrl+shift+a"]
    assert field.combo() == "ctrl+shift+a"
    assert field.text() == "Ctrl+Shift+A"


# --------------------------------------------------------------------------
# AppWindow
# --------------------------------------------------------------------------
def test_app_window_builds_and_switches(qt_app, settings):
    from app.ui.components.window import AppWindow

    window = AppWindow(settings)
    assert window.models_page is not None
    assert window.settings_page is not None
    # Sidebar order: Settings on top, Models below.
    assert window.sidebar.items[0].text() == "Settings"
    assert window.sidebar.items[1].text() == "Models"
    window.show_settings()
    assert window.pages.currentWidget() is window.settings_page
    window.show_models()
    assert window.pages.currentWidget() is window.models_page


def test_toast_host_routes_through_window(qt_app, settings):
    from app.ui.components.window import AppWindow

    window = AppWindow(settings)
    window.show_toast("info", "Title", "Message")
    assert not window._toast_host.isHidden()
    assert window._toast_host._layout.count() >= 1


# --------------------------------------------------------------------------
# Settings page
# --------------------------------------------------------------------------
def test_settings_page_standalone(qt_app, settings):
    from app.util import normalize_combo

    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)
    assert normalize_combo(page._hotkey_edit.text()) == settings.get("hotkey")
    assert page._hotkey_edit.combo() == settings.get("hotkey")


def test_settings_page_recording_chimes_toggle(qt_app, settings):
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)
    # The first ToggleSwitch in the recording group is the chimes toggle; we
    # flip it through the group's rows instead of assuming order.
    settings.set("recording_chimes", False)
    assert settings.get("recording_chimes") is False
    settings.set("recording_chimes", True)
    assert settings.get("recording_chimes") is True


def test_settings_page_autostart_contents(qt_app, settings, monkeypatch, tmp_path):
    from app.ui.pages import settings_page as page_module

    monkeypatch.setattr(page_module, "xdg_config_home", lambda: str(tmp_path))
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)
    page._apply_autostart(True)
    path = tmp_path / "autostart" / "briizflow.desktop"
    assert path.exists()
    content = path.read_text()
    assert "BriizFlow" in content and "Exec=" in content


def test_settings_page_autostart_writes_entry(qt_app, settings, monkeypatch, tmp_path):
    from app.ui.pages import settings_page as page_module

    monkeypatch.setattr(page_module, "xdg_config_home", lambda: str(tmp_path))
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)
    page._apply_autostart(True)
    assert (tmp_path / "autostart" / "briizflow.desktop").exists()
    page._apply_autostart(False)
    assert not (tmp_path / "autostart" / "briizflow.desktop").exists()


def test_api_key_field_masked_and_empty_on_load(qt_app, settings, _isolated_key_store):
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)
    assert page._key_field.text() == ""
    assert page._key_field.echoMode().name == "Password"


def test_saving_api_key_uses_store_not_settings(qt_app, settings, _isolated_key_store):
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)
    page._key_field.setText("sk-test-1234")
    page._save_key()
    assert _isolated_key_store.get() == "sk-test-1234"
    assert "sk-test-1234" not in settings.as_dict().values()


def test_blank_api_key_never_deletes(qt_app, settings, _isolated_key_store):
    from app.ui.pages.settings_page import SettingsPage

    _isolated_key_store.set("sk-keep-me")
    page = SettingsPage(settings)
    page._key_field.setText("   ")
    page._save_key()
    assert _isolated_key_store.get() == "sk-keep-me"


def test_api_key_field_keeps_masked_key_after_save(qt_app, settings, _isolated_key_store):
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)
    page._key_field.setText("sk-test-1234")
    page._save_key()
    assert page._key_field.text() == ""
    assert page._key_field.placeholderText() == "••••••••"


def test_api_key_store_error_preserves_field(qt_app, settings, _isolated_key_store, monkeypatch):
    from app.ui.pages.settings_page import SettingsPage

    class _BoomStore:
        kind = "session"
        available = True

        def get(self):
            return None

        def set(self, value):
            raise CredentialStoreError("keyring exploded")

        def delete(self):
            pass

    monkeypatch.setattr("app.ui.pages.settings_page.get_default_store", lambda: _BoomStore())
    page = SettingsPage(settings)
    page._key_field.setText("sk-test-1234")
    page._save_key()
    assert page._key_field.text() == "sk-test-1234"  # preserved on error


def test_delete_api_key_clears_store_and_emits(qt_app, settings, _isolated_key_store):
    from app.ui.pages.settings_page import SettingsPage

    _isolated_key_store.set("sk-delete-me")
    page = SettingsPage(settings)
    emitted = []
    page.settings_saved.connect(emitted.append)
    page._do_delete_key()
    assert _isolated_key_store.get() is None
    assert "openai_api_key" in emitted


def test_model_dropdown_is_curated(qt_app, settings, _isolated_key_store):
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)
    labels = [page._model_combo.itemText(i) for i in range(page._model_combo.count())]
    assert labels == model_labels()


def test_model_dropdown_restores_saved_model(qt_app, settings, _isolated_key_store):
    """The OpenAI model dropdown must show the persisted model, not a default."""
    from app.ui.pages.settings_page import SettingsPage

    settings.set("openai_model", "gpt-4o-mini-transcribe")
    page = SettingsPage(settings)
    assert page._model_combo.currentData() == "GPT-4o Mini Transcribe"


def test_model_dropdown_defaults_to_first_entry(qt_app, settings, _isolated_key_store):
    """With no model saved the dropdown falls back to the first curated entry."""
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)  # openai_model unset
    assert page._model_combo.currentData() == "GPT Transcribe"


def test_dependent_controls_stay_enabled(qt_app, settings, _isolated_key_store):
    """Toggling a parent option never disables the related controls (the
    disable/dim feature was removed by design)."""
    from app.ui.pages.settings_page import SettingsPage

    page = SettingsPage(settings)
    # Online on/off does not disable the model or API key controls.
    page._on_online_toggled(True)
    assert page._model_combo.isEnabled()
    assert page._key_field.isEnabled()
    assert page._save_btn.isEnabled()
    assert page._delete_btn.isEnabled()
    page._on_online_toggled(False)
    assert page._model_combo.isEnabled()
    assert page._key_field.isEnabled()
    assert page._save_btn.isEnabled()
    assert page._delete_btn.isEnabled()
    # Save-recordings on/off does not disable the recordings folder.
    page._on_save_recordings_changed(False)
    assert page._recordings_edit.isEnabled()
    assert page._recordings_browse_btn.isEnabled()


# --------------------------------------------------------------------------
# Models page
# --------------------------------------------------------------------------
def test_models_page_has_downloaded_and_available_sections(qt_app, settings, models_dir):
    (models_dir / "ggml-base.bin").write_bytes(b"base")
    from app.ui.pages.models_page import ModelsPage

    page = ModelsPage(settings)
    headers = [
        page._list_layout.itemAt(i).widget()
        for i in range(page._list_layout.count())
        if page._list_layout.itemAt(i).widget() is not None
        and page._list_layout.itemAt(i).widget().objectName() == "groupHeader"
    ]
    assert [h.text() for h in headers] == ["Downloaded", "Available"]
    # The downloaded model lives in the first section (before "Available").
    downloaded_index = page._list_layout.indexOf(page._cards["ggml-base.bin"])
    available_header_index = page._list_layout.indexOf(headers[1])
    assert downloaded_index < available_header_index


def test_models_page_refresh_rescans_and_clears_missing_active(qt_app, settings, models_dir):
    from app.ui.pages.models_page import ModelsPage

    (models_dir / "ggml-base.bin").write_bytes(b"base")
    settings.set("model_name", "ggml-base.bin")
    page = ModelsPage(settings)
    assert not page._cards["ggml-base.bin"].active_badge.isHidden()
    assert page.refresh_btn.text() == "Refresh"

    # Simulate deleting the file outside the app, then refresh.
    (models_dir / "ggml-base.bin").unlink()
    page._refresh()
    assert settings.get("model_name") == ""  # active selection cleared
    assert page._cards["ggml-base.bin"].download_btn is not None  # now Available
    assert page._cards["ggml-base.bin"].active_badge is None


def test_models_page_owns_a_real_qnam(qt_app, settings, models_dir):
    from PySide6.QtNetwork import QNetworkAccessManager

    from app.ui.pages.models_page import ModelsPage

    page = ModelsPage(settings)
    assert isinstance(page._manager._qnam, QNetworkAccessManager)


def test_models_page_button_states(qt_app, settings, models_dir):
    (models_dir / "ggml-base.bin").write_bytes(b"base")
    (models_dir / "ggml-tiny.bin").write_bytes(b"tiny")
    settings.set("model_name", "ggml-base.bin")
    from app.ui.pages.models_page import ModelsPage

    page = ModelsPage(settings)
    active = page._cards["ggml-base.bin"]
    assert not active.active_badge.isHidden()
    assert active.set_active_btn is None or active.set_active_btn.isHidden()


def test_models_page_auto_activates_after_download(qt_app, settings, models_dir):
    from app.ui.pages.models_page import ModelsPage

    page = ModelsPage(settings)
    # The manager writes the file before emitting download_finished.
    (models_dir / "ggml-tiny.bin").write_bytes(b"tiny")
    page._on_download_finished("ggml-tiny.bin", str(models_dir / "ggml-tiny.bin"))
    assert settings.get("model_name") == "ggml-tiny.bin"
    assert not page._cards["ggml-tiny.bin"].active_badge.isHidden()
