"""ToggleSwitch — a small animated pill switch.

A ``QCheckBox`` subclass so ``setChecked()/isChecked()/toggled`` come for
free; the pill is fully custom-painted (QSS can't draw smooth toggles). The
knob position tweens through a QVariantAnimation, but **correctness never
depends on the animation**: when the animation is not running (which is always
the case in tests that don't spin an event loop) the paint snaps straight to
``isChecked()``.

Emits ``checkedChanged(bool)`` in addition to Qt's own ``toggled``.
"""

from PySide6.QtCore import QEasingCurve, QPointF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox

from app.ui.theme import colors, dimensions

_TRACK_OFF = QColor(colors.BORDER)
_TRACK_ON = QColor(colors.ACCENT)
_TRACK_HOVER = QColor("#2A3038")
_KNOB = QColor("#FFFFFF")


class ToggleSwitch(QCheckBox):
    """A custom-painted animated pill toggle."""

    checkedChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(dimensions.TOGGLE_W, dimensions.TOGGLE_H)
        self.setCursor(Qt.PointingHandCursor)
        self._knob_x = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)
        self.toggled.connect(self._on_toggled)

    def hitButton(self, pos):
        # A QCheckBox's default click rect wraps its indicator (the left edge);
        # the whole pill is the click target here.
        return self.rect().contains(pos)

    def _on_toggled(self, checked):
        self._animate_to(checked)
        self.checkedChanged.emit(checked)

    def _on_anim_value(self, value):
        self._knob_x = float(value)
        self.update()

    def _animate_to(self, checked):
        # Always animate from the current knob position, so toggling ON slides
        # the knob in just like toggling OFF slides it out.
        start = self._knob_x
        end = 1.0 if checked else 0.0
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def _knob_pos(self):
        """Knob horizontal offset (0 = off, track_w - knob_d = on)."""
        w = dimensions.TOGGLE_W
        h = dimensions.TOGGLE_H
        pad = 3
        knob_d = h - pad * 2
        travel = w - pad * 2 - knob_d
        if self._anim.state() != self._anim.State.Running:
            return travel if self.isChecked() else 0.0
        return travel * self._knob_x

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = dimensions.TOGGLE_W
        h = dimensions.TOGGLE_H
        pad = 3
        knob_d = h - pad * 2

        track = _TRACK_ON if self.isChecked() else _TRACK_OFF
        if self.underMouse() and not self.isChecked():
            track = _TRACK_HOVER
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(0, 0, w, h, h / 2, h / 2)

        x = pad + self._knob_pos()
        painter.setBrush(_KNOB)
        painter.drawEllipse(QPointF(x + knob_d / 2, h / 2), knob_d / 2, knob_d / 2)
        painter.end()
