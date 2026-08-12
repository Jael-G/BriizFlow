"""ProgressBar — styled progress with a custom indeterminate mode.

Determinate and indeterminate modes are both custom-painted here. Qt's native
``QProgressBar::chunk`` can't round a chunk narrower than its radius (a small
value renders as a square sliver), so the determinate fill is drawn inside a
pill-shaped clip: the fill's edges always follow the rounded groove and never
"snap" between square and rounded. Indeterminate mode is a green pill sliding
back and forth, keeping ``self.text()`` (the format string) centered.
"""

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QProgressBar

from app.ui.theme import colors


class ProgressBar(QProgressBar):
    """Styled progress bar with a custom indeterminate ("busy") mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def setRange(self, minimum, maximum):
        super().setRange(minimum, maximum)
        self._busy = maximum <= minimum
        if self._busy:
            self._timer.start(30)
        else:
            self._timer.stop()

    def _tick(self):
        self._phase += 0.05
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            rect = QRect(0, 0, self.width(), self.height()).adjusted(1, 1, -1, -1)
            if self._busy:
                self._paint_busy(painter, rect)
            else:
                self._paint_determinate(painter, rect)
        finally:
            painter.end()

    def _paint_determinate(self, painter, rect):
        radius = rect.height() / 2.0
        # Groove.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors.SURFACE_2))
        painter.drawRoundedRect(rect, radius, radius)

        # Fill, clipped to the pill so its edges always follow the groove.
        span = max(1, self.maximum() - self.minimum())
        fraction = (self.value() - self.minimum()) / span
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.save()
        painter.setClipPath(path)
        fill = QRect(rect.left(), rect.top(), int(rect.width() * fraction), rect.height())
        painter.setBrush(QColor(colors.SUCCESS))
        painter.drawRect(fill)
        painter.restore()

        if self.text():
            painter.setPen(QColor(colors.TEXT))
            painter.drawText(rect, Qt.AlignCenter, self.text())

    def _paint_busy(self, painter, rect):
        radius = rect.height() / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors.SURFACE_2))
        painter.drawRoundedRect(rect, radius, radius)

        # A pill sliding back and forth.
        travel = max(20, rect.width() - 40)
        pos = (self._phase % 1.0) * travel
        pill = QRect(rect.left() + int(pos), rect.top(), 40, rect.height())
        painter.setBrush(QColor(colors.SUCCESS))
        painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)

        if self.text():
            painter.setPen(QColor(colors.TEXT_MUTED))
            painter.drawText(rect, Qt.AlignCenter, self.text())
