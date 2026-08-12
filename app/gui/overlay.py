"""Floating black-orb overlay shown while dictating.

A frameless, always-on-top, mouse-transparent window anchored to the bottom
edge of the screen. Behind the orb, a soft vertical gradient darkens the
bottom of the screen and fades to transparent by the time it reaches the
orb's top, so the orb reads as floating in an ambient pool of shadow. Three
visual states:

* ``recording``  — a solid black orb with a soft drop shadow at its edges, and
  an ethereal colored wave inside: complete undulating arcs that ripple,
  breathe, and react to mic volume.
* ``processing`` — a calm white loading spinner while whisper converts the
  audio: a thin arc sweeping around the orb, rotating on the phase clock.
* ``success`` / ``error`` / ``pending`` — outcome glyphs drawn inside the orb
  after a dictation attempt: a green checkmark when the transcript was
  inserted, a red X when dictation failed, and dim "…" while the server warms
  up. Each holds briefly then exits. Error details are posted as a system
  notification (``app.notifications``).

The window itself is mapped only while feedback is on screen: it is shown when
a visual state is entered and unmapped again once the exit fade completes. Kept
off-screen while idle, the always-on-top surface never sits over the desktop
and cannot swallow clicks aimed at the application underneath.

The orb is a solid opaque black disc; its feathered edges come from a soft
black drop shadow drawn around it (layered strokes whose alpha fades outward).
The wave is rendered into a low-resolution pixmap and scaled up with smoothing
— the upscale acts as a cheap blur. Mic level scales amplitude/energy while
slow self-animators keep the orb alive at silence.

The gradient backdrop is static, so it is painted once into a cached pixmap
and rebuilt only when the window resizes. The 60 fps repaint during recording
just blits that cache and draws the orb — the overlay costs almost nothing at
runtime.
"""

import logging
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)

ORB_D = 56
ORB_R = ORB_D / 2
ORB_BOTTOM_GAP = 40
BAND_H = 136
SHADOW_STEPS = 10
SHADOW_MIN_W = 4
SHADOW_MAX_W = 38
SHADOW_ALPHA = 190
ORB_TWEEN_FRAMES = 30
ORB_TWEEN_SLIDE = 200
ORB_TWEEN_BACK = 2
MESSAGE_HOLD_MS = 700
WAVE_NX = 96
WAVE_RENDER_SCALE = 0.3
WAVE_A1 = 0.4
WAVE_FREQ = 2.6
WAVE_A2 = 0.44
WAVE_ABER_FREQ = 3
WAVE_AB = 1.1
WAVE_DRIFT_SCALE = 0.22
WAVE_AMP_MIN = 0.45
WAVE_ENERGY_MIN = 0.5
WAVE_ENERGY_MAX = 1.5
AMP_ATTACK = 0.25
AMP_RELEASE = 0.05
WAVE_BAND_HALF = 0.06
WAVE_MAIN_HALF = 0.045
WAVE_SPECTRAL = (QColor(255, 62, 72), QColor(255, 206, 62), QColor(84, 244, 132), QColor(62, 201, 255))
WAVE_MAIN = QColor(232, 248, 255)
SPIN_SWEEP = 270
SPIN_DEG_PER_RAD = 20
SUCCESS_COLOR = QColor(74, 222, 128)
ERROR_COLOR = QColor(248, 113, 113)
PENDING_COLOR = QColor(255, 255, 255, 150)
_SYMBOL_STATES = ("success", "error", "pending")
# Bottom of the screen is darkest; the shadow fades out as it rises.
BAND_STOPS = ((0, 0), (0.25, 18), (0.5, 80), (0.72, 150), (1, 220))


class Overlay(QWidget):
    """Floating black-orb feedback window (see module docstring)."""

    def __init__(self, settings, parent=None):
        super().__init__(
            parent,
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._settings = settings
        self._state = "idle"
        self._level = 0.0
        self._amp = 0.0
        self._phase = 0.0
        self._message_until = 0.0
        self._backdrop = None
        # Reveal tween: 0 = fully transparent (orb below screen), 1 = settled.
        # The content fades via painter opacity, so no window show/hide
        # animation plays when a state changes.
        self._reveal = 0.0
        self._reveal_target = 0.0
        screen = QApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else QRectF(0, 0, 1920, 1080)
        self._screen_geom = geom
        # A compact window anchored to the bottom edge (not full-screen): the
        # backdrop band plus room for the orb and its shadow.
        self._window_h = BAND_H
        self.setGeometry(
            int(geom.x()),
            int(geom.bottom()) - self._window_h,
            int(geom.width()),
            self._window_h,
        )
        self._build_backdrop()
        # The window starts unmapped. It is only shown while feedback is on
        # screen and hidden again once the exit fade completes; kept off-screen
        # when idle, the always-on-top surface can never swallow clicks aimed
        # at the application underneath.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # --- public API ---------------------------------------------------------
    def set_state(self, state):
        """Drive the overlay into one of the visual states."""
        self._state = state
        if state == "idle":
            # Fade + slide out, then unmap once the fade completes.
            self._reveal_target = 0.0
            return
        if state in _SYMBOL_STATES:
            self._message_until = time.monotonic() + MESSAGE_HOLD_MS / 1000.0
        if state == "recording":
            self._amp = 0.0
        # Make sure the surface is mapped before the content fades in.
        if not self.isVisible():
            self.show()
        # Fade the content in; the orb slides up.
        self._reveal_target = 1.0

    def set_level(self, level):
        """Feed the current mic level (0..1) while recording."""
        self._level = max(0.0, min(1.0, float(level)))

    # --- internals ----------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self._anchor_to_bottom()
        self.raise_()

    def _anchor_to_bottom(self):
        self.setGeometry(
            int(self._screen_geom.x()),
            int(self._screen_geom.bottom()) - self._window_h,
            int(self._screen_geom.width()),
            self._window_h,
        )

    def _build_backdrop(self):
        band = QPixmap(int(self._screen_geom.width()), BAND_H)
        band.fill(Qt.transparent)
        painter = QPainter(band)
        grad = QLinearGradient(0, 0, 0, BAND_H)
        for stop, alpha in BAND_STOPS:
            grad.setColorAt(stop, QColor(0, 0, 0, alpha))
        painter.fillRect(band.rect(), grad)
        painter.end()
        self._backdrop = band

    def _tick(self):
        self._phase += 0.06
        # Reveal tween: ease the content fade + orb slide toward the target.
        if self._reveal_target > 0.5:
            if self._reveal < 1.0:
                self._reveal += (1.0 - self._reveal) * 0.10
                if self._reveal > 0.999:
                    self._reveal = 1.0
                self.update()
        else:
            if self._reveal > 0.0:
                # Fade the backdrop out over roughly the enter duration
                # (~0.04/tick at 16 ms ≈ 400 ms). The orb's slide curve in
                # paintEvent supplies the tween feel.
                self._reveal = max(0.0, self._reveal - 0.04)
                self.update()
            elif self.isVisible():
                # Fade finished and nothing left to show: unmap the window so
                # the always-on-top surface stops intercepting clicks while
                # idle (the content is fully transparent by this point).
                self.hide()
        if self._state == "recording":
            target = self._level
            rate = AMP_ATTACK if target > self._amp else AMP_RELEASE
            self._amp += (target - self._amp) * rate
            self.update()
        elif self._state == "processing":
            self.update()
        elif self._state in _SYMBOL_STATES:
            if time.monotonic() >= self._message_until:
                self.set_state("idle")
            else:
                self.update()

    @staticmethod
    def _ease_out_back(x):
        """Ease-out with a pronounced overshoot (the orb pops up past its rest
        position, then settles)."""
        x = max(0.0, min(1.0, x))
        c1 = 1.8
        c3 = c1 + 1.0
        return 1.0 + c3 * (x - 1.0) ** 3 + c1 * (x - 1.0) ** 2

    @staticmethod
    def _ease_in_back(x):
        """Ease-in with a brief anticipation, the mirror of :meth:`_ease_out_back`.

        The value first dips slightly negative (the orb nudges up past its rest
        position), then sweeps to 1.0 — so on the way out it gathers, then
        accelerates back down instead of gliding away at constant speed.
        """
        x = max(0.0, min(1.0, x))
        c1 = 1.8
        c3 = c1 + 1.0
        return c3 * x ** 3 - c1 * x ** 2

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            # The screen shadow fades in/out with the reveal.
            painter.setOpacity(self._reveal)
            # The whole window IS the bottom band (window-local coordinates).
            painter.drawPixmap(0, 0, self._backdrop)
            # The orb stays opaque and visibly tweens up from below the screen.
            painter.setOpacity(1.0)

            cx = self.width() / 2.0
            bottom = self.height() - ORB_BOTTOM_GAP
            if self._reveal_target < 0.5:
                # Exiting: a brief upward nudge, then an accelerated glide back
                # down out of the screen — the mirror of the enter's pop.
                slide = self._ease_in_back(1.0 - self._reveal) * ORB_TWEEN_SLIDE
            else:
                # Entering: slide up from below with an ease-out-back pop.
                slide = (1.0 - self._ease_out_back(self._reveal)) * ORB_TWEEN_SLIDE
            center = QPointF(cx, bottom - ORB_R + slide)

            if self._state == "recording":
                self._draw_orb(painter, center)
                self._draw_wave(painter, center)
            elif self._state == "processing":
                self._draw_orb(painter, center)
                self._draw_spinner(painter, center)
            elif self._state in _SYMBOL_STATES:
                self._draw_orb(painter, center)
                self._draw_symbol(painter, center)
            elif self._reveal > 0.0:
                # Exiting (idle): the backdrop is fading out, but keep drawing
                # the orb so it visibly glides back down out of the screen
                # instead of vanishing on the very first exit frame.
                self._draw_orb(painter, center)
        except Exception:
            # A paint error must never leave Qt with an active painter.
            log.exception("Overlay paint failed")
        finally:
            painter.end()

    def _draw_orb(self, painter, center):
        """One solid black disc with a soft, feathered edge (no ring banding).

        A single smooth radial gradient: opaque black across the solid disc,
        then a gentle low-contrast falloff to transparent, so the circle reads
        as *fading out* into the screen rather than casting a hard shadow.
        """
        halo = ORB_R * 0.5
        total_r = ORB_R + halo
        grad = QRadialGradient(center.x(), center.y(), total_r)
        grad.setColorAt(0.0, QColor(0, 0, 0, 255))
        grad.setColorAt(ORB_R / total_r, QColor(0, 0, 0, 255))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawEllipse(center, total_r, total_r)

    def _draw_wave(self, painter, center):
        """Siri-style chromatic wave inside the orb.

        A numpy port of the WebGL "wave" shader: a single smooth undulating
        line with four chromatic fringes (phase-shifted sine arcs) and a
        bright near-white core. Each arc contributes the shader's Lorentzian
        glow plus a band fill between it and the main line; the whole wave
        fades toward the horizontal edges (Gaussian envelope) and slides
        sideways as the phase drifts. The (attack/release-smoothed) mic level
        drives amplitude and brightness, so the wave visibly swells and glows
        as the person speaks; the shader's self-animators keep it alive at
        silence. Rendered at the orb's pixel resolution for smooth lines.
        """
        import numpy as np

        t = self._phase / 3.75  # tick rate (0.06 per 16 ms) -> approximate seconds
        voice = float(max(0.0, min(1.0, self._amp)))

        # --- self-animating bands (from the shader) -------------------------
        low = float(np.clip(0.45 + 0.45 * np.sin(t * 0.8) * np.sin(t * 0.37 + 1.0), 0, 1))
        mid = float(np.clip(0.40 + 0.40 * np.sin(t * 1.7 + 2.0) * np.sin(t * 0.53), 0, 1))
        high = float(np.clip(0.30 + 0.30 * np.sin(t * 2.9 + 4.0) * np.sin(t * 0.71 + 2.0), 0, 1))
        # Voice pushes amplitude and brightness on top of the self-animation.
        # The shader's den-normalization dilutes intensity, so we keep a solid
        # baseline to stay visible, then let voice add a strong reaction.
        # Subtle at rest, but a big swing when the mic level rises: a strong
        # visual "voice is being received" reaction rather than constant glow.
        A1 = 0.24 + 0.38 * voice
        A2 = A1 + mid * 0.04 + high * 0.05
        inten = 0.05 + 0.12 * voice
        AB = 2.6 + 2.0 * voice
        # Slow, wavy drift (was 2.4, which whooshed).
        drift = np.mod(t, 20.0 * np.pi) * 1.1

        # --- render target at (near) orb resolution: smooth, not stretched --
        lw = max(56, ORB_D + 8)
        lh = lw

        x = np.linspace(-1.0, 1.0, lw)
        env = np.cos(np.pi * 0.5 * np.minimum(np.abs(0.9 * x), 1.0)) ** 2

        y_main = A1 * env * np.sin(x * 1.1 + drift)
        arc_ys = []
        for s in range(4):
            ab = -AB + (2.0 * AB * s) / 3.0
            arc_ys.append(A2 * env * np.sin(x * 1.0 + drift + ab))

        py = np.linspace(1.0, -1.0, lh)[:, None]  # +1 top -> -1 bottom
        # A soft glow that radiates from the line without saturating into a
        # solid white band.
        th = 0.04
        soft = 0.02
        band_th = 0.08
        band_amt = 0.22 * inten

        num = np.zeros((lh, lw, 3), dtype=np.float64)
        den = np.zeros(3, dtype=np.float64)
        for s, yL in enumerate(arc_ys):
            hue = np.array(WAVE_SPECTRAL[s].getRgbF()[:3])
            den += hue
            d = np.abs(py - yL[None, :])
            line = inten / (np.sqrt(d * d + soft * soft) + th)
            lo = np.minimum(y_main[None, :], yL[None, :])
            hi = np.maximum(y_main[None, :], yL[None, :])
            dBand = np.maximum(0.0, np.maximum(py - hi, lo - py))
            band = band_amt / (dBand + band_th)
            num += hue[None, None, :] * (line + band)[..., None]

        # Bright near-white main line.
        dM = np.abs(py - y_main[None, :])
        lineM = 1.3 * inten / (np.sqrt(dM * dM + soft * soft) + th)
        num += lineM[..., None] * np.array([0.95, 0.98, 1.0])

        col = num / (den[None, None, :] + 1e-6)
        col = np.power(np.maximum(col, 0.0), 1.5)
        # Gaussian edge fade so the wave tapers at the orb's sides, but keeps
        # reaching most of the way to the edges.
        col *= np.exp(-np.power(x * 1.2, 2.0))[None, :, None]
        col = np.clip(col, 0.0, 1.0)
        alpha = np.clip(np.max(col, axis=2) * 1.5, 0.0, 1.0)

        rgba = np.dstack([col, alpha[..., None]])
        rgba = (rgba * 255.0).astype(np.uint8)
        img = QImage(rgba.tobytes(), lw, lh, lw * 4, QImage.Format_RGBA8888)
        pm = QPixmap.fromImage(img)

        # Draw inside the orb, upscaled smoothly.
        path = QPainterPath()
        path.addEllipse(center, ORB_R, ORB_R)
        painter.save()
        painter.setClipPath(path)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(
            QRectF(center.x() - ORB_R, center.y() - ORB_R, ORB_D, ORB_D),
            pm,
            QRectF(0, 0, lw, lh),
        )
        painter.restore()

    def _draw_spinner(self, painter, center):
        # A small, thin sweeping arc (no glow — the user asked for a slimmer
        # spinner).
        rect = QRectF(
            center.x() - ORB_R * 0.5,
            center.y() - ORB_R * 0.5,
            ORB_D * 0.5,
            ORB_D * 0.5,
        )
        start = int(self._phase * SPIN_DEG_PER_RAD * 16) % 5760
        span = SPIN_SWEEP * 16
        pen = QPen(WAVE_MAIN)
        pen.setWidthF(3.5)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(rect, start, span)

    def _draw_symbol(self, painter, center):
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.NoBrush)
        if self._state == "success":
            path = QPainterPath()
            path.moveTo(center.x() - ORB_R * 0.4, center.y())
            path.lineTo(center.x() - ORB_R * 0.1, center.y() + ORB_R * 0.32)
            path.lineTo(center.x() + ORB_R * 0.45, center.y() - ORB_R * 0.3)
            pen = QPen(SUCCESS_COLOR)
            pen.setWidthF(4)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)
        elif self._state == "error":
            d = ORB_R * 0.4
            pen = QPen(ERROR_COLOR)
            pen.setWidthF(4)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(center.x() - d, center.y() - d, center.x() + d, center.y() + d)
            painter.drawLine(center.x() - d, center.y() + d, center.x() + d, center.y() - d)
        else:  # pending
            painter.setPen(PENDING_COLOR)
            f = painter.font()
            f.setPixelSize(int(ORB_R * 1.2))
            painter.setFont(f)
            painter.drawText(
                QRectF(center.x() - ORB_R, center.y() - ORB_R, ORB_D, ORB_D),
                Qt.AlignCenter,
                "…",
            )
