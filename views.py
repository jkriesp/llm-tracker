"""Custom AppKit views for the menu bar dropdown."""

from __future__ import annotations

import objc
from AppKit import (
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSString,
    NSView,
)
from Foundation import NSMakeRect

MENU_WIDTH = 280
METRIC_HEIGHT = 38
HEADER_HEIGHT = 26
PADDING = 16
BAR_HEIGHT = 4
BAR_RADIUS = 2


def _bar_color(pct: float) -> NSColor:
    """Color for progress bar fill — green / yellow / red."""
    if pct >= 90:
        return NSColor.systemRedColor()
    if pct >= 70:
        return NSColor.systemOrangeColor()
    return NSColor.systemGreenColor()


def _draw_text(text: str, x: float, y: float, font: NSFont, color: NSColor) -> None:
    attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: color}
    NSString.stringWithString_(text).drawAtPoint_withAttributes_((x, y), attrs)


def _text_width(text: str, font: NSFont) -> float:
    attrs = {NSFontAttributeName: font}
    return NSString.stringWithString_(text).sizeWithAttributes_(attrs).width


# ── Metric row view ───────────────────────────────────────────────────────────


class MetricView(NSView):
    """Renders one usage metric: label, colored progress bar, %, reset time."""

    def initWithFrame_(self, frame):
        self = objc.super(MetricView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._label = ""
        self._pct = 0.0
        self._reset = ""
        self._visible = False
        return self

    def isFlipped(self):
        return True

    @objc.python_method
    def update(self, label: str, pct: float, reset_text: str) -> None:
        self._label = label
        self._pct = pct
        self._reset = reset_text
        self._visible = True
        self.setNeedsDisplay_(True)

    @objc.python_method
    def clear(self) -> None:
        self._visible = False
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirtyRect):
        if not self._visible:
            return

        w = self.bounds().size.width
        color = _bar_color(self._pct)

        # ── Row 1: label  ·····  reset time  pct ──
        y_text = 6

        # Label (left)
        _draw_text(
            self._label, PADDING, y_text,
            NSFont.systemFontOfSize_(12),
            NSColor.labelColor(),
        )

        # Percentage (right, colored, monospaced digits)
        pct_str = f"{self._pct:.0f}%"
        pct_font = NSFont.monospacedDigitSystemFontOfSize_weight_(12, 0.3)
        pct_w = _text_width(pct_str, pct_font)
        _draw_text(pct_str, w - PADDING - pct_w, y_text, pct_font, color)

        # Reset time (secondary, left of percentage)
        if self._reset:
            reset_font = NSFont.systemFontOfSize_(10)
            reset_w = _text_width(self._reset, reset_font)
            _draw_text(
                self._reset,
                w - PADDING - pct_w - reset_w - 8, y_text + 2,
                reset_font,
                NSColor.secondaryLabelColor(),
            )

        # ── Row 2: progress bar ──
        bar_y = 26
        bar_w = w - PADDING * 2

        # Track (background)
        track = NSMakeRect(PADDING, bar_y, bar_w, BAR_HEIGHT)
        track_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            track, BAR_RADIUS, BAR_RADIUS
        )
        NSColor.quaternaryLabelColor().setFill()
        track_path.fill()

        # Fill
        fill_w = bar_w * min(self._pct / 100.0, 1.0)
        if fill_w > 0:
            fill = NSMakeRect(PADDING, bar_y, fill_w, BAR_HEIGHT)
            fill_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                fill, BAR_RADIUS, BAR_RADIUS
            )
            color.setFill()
            fill_path.fill()


# ── Section header view ───────────────────────────────────────────────────────


class HeaderView(NSView):
    """Centered section header, e.g. '── Claude ──'."""

    def initWithTitle_(self, title: str):
        frame = NSMakeRect(0, 0, MENU_WIDTH, HEADER_HEIGHT)
        self = objc.super(HeaderView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._title = title
        return self

    def isFlipped(self):
        return True

    def drawRect_(self, dirtyRect):
        w = self.bounds().size.width
        h = self.bounds().size.height

        font = NSFont.systemFontOfSize_weight_(11, 0.2)
        color = NSColor.secondaryLabelColor()
        title_w = _text_width(self._title, font)
        x = (w - title_w) / 2
        y = (h - 14) / 2  # rough vertical center

        _draw_text(self._title, x, y, font, color)

        # Decorative lines on either side
        line_y = h / 2
        line_color = NSColor.separatorColor()
        line_color.setStroke()

        left_end = x - 8
        if left_end > PADDING:
            left = NSBezierPath.bezierPath()
            left.moveToPoint_((PADDING, line_y))
            left.lineToPoint_((left_end, line_y))
            left.setLineWidth_(0.5)
            left.stroke()

        right_start = x + title_w + 8
        if right_start < w - PADDING:
            right = NSBezierPath.bezierPath()
            right.moveToPoint_((right_start, line_y))
            right.lineToPoint_((w - PADDING, line_y))
            right.setLineWidth_(0.5)
            right.stroke()


# ── Error view ────────────────────────────────────────────────────────────────


class ErrorView(NSView):
    """Shows an error/status message."""

    def initWithFrame_(self, frame):
        self = objc.super(ErrorView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._message = ""
        self._visible = False
        return self

    def isFlipped(self):
        return True

    @objc.python_method
    def update(self, message: str) -> None:
        self._message = message
        self._visible = True
        self.setNeedsDisplay_(True)

    @objc.python_method
    def clear(self) -> None:
        self._visible = False
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirtyRect):
        if not self._visible:
            return
        _draw_text(
            f"\u26a0  {self._message}", PADDING, 6,
            NSFont.systemFontOfSize_(11),
            NSColor.systemOrangeColor(),
        )
