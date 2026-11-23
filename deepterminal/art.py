"""chafa-style inline art for DTinfo.

The DeepTerminal icon is rendered **inside the terminal** as coloured
half-block characters (``▀`` with a truecolour foreground/background per
cell), so DTinfo shows a picture the way tools like ``chafa`` / ``fastfetch``
/sysfetch do — no floating overlay window involved.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter

#: Art grid size in character cells. Each cell shows two pixels via ``▀``.
ART_WIDTH = 28
ART_HEIGHT = 14

_HALF_BLOCK = "▀"


def _sgr(rgb: tuple[int, int, int], bg: tuple[int, int, int]) -> str:
    r, g, b = rgb
    br, bg_, bb = bg
    return f"\x1b[38;2;{r};{g};{b};48;2;{br};{bg_};{bb}m"


def icon_art_rows(
    icon_path: str | Path,
    width: int = ART_WIDTH,
    height: int = ART_HEIGHT,
    background: str = "#121212",
    gain: float = 1.9,
) -> list[str]:
    """Render a square icon as ANSI half-block art rows.

    Pixels that are transparent in the icon are composited over
    ``background`` (the terminal's own background colour), so the rounded
    icon card blends into dark or light themes.
    """
    image = QImage(str(icon_path))
    if image.isNull() or width <= 0 or height <= 0:
        return []

    pixel_w = width
    pixel_h = height * 2
    canvas = QImage(pixel_w, pixel_h, QImage.Format.Format_ARGB32)
    canvas.fill(QColor(background))

    scaled = image.scaled(
        pixel_w,
        pixel_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    # Lift the icon's own contrast (chafa-style): the icon is mostly grey and
    # would otherwise read as a dim smudge at this size. The stretch uses the
    # icon's own luminance percentiles, so it works on dark *and* light
    # terminal backgrounds instead of clamping everything to the theme colour.
    if gain != 1.0:
        luminance: list[int] = []
        for y in range(scaled.height()):
            for x in range(scaled.width()):
                color = scaled.pixelColor(x, y)
                if color.alpha() == 0:
                    continue
                luminance.append(int(0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()))
        if luminance:
            luminance.sort()
            low = luminance[max(0, len(luminance) // 20)]
            high = luminance[min(len(luminance) - 1, len(luminance) * 19 // 20)]
            span = max(1, high - low)

            def stretch(channel: int) -> int:
                return max(0, min(255, int((channel - low) / span * 255)))

            stretched = QImage(scaled.width(), scaled.height(), QImage.Format.Format_ARGB32)
            stretched.fill(0)
            for y in range(scaled.height()):
                for x in range(scaled.width()):
                    color = scaled.pixelColor(x, y)
                    if color.alpha() == 0:
                        continue
                    stretched.setPixelColor(
                        x,
                        y,
                        QColor(stretch(color.red()), stretch(color.green()), stretch(color.blue()), color.alpha()),
                    )
            scaled = stretched

    painter = QPainter(canvas)
    painter.drawImage(
        (pixel_w - scaled.width()) // 2,
        (pixel_h - scaled.height()) // 2,
        scaled,
    )
    painter.end()

    rows: list[str] = []
    for row in range(height):
        parts: list[str] = []
        for column in range(width):
            top = canvas.pixelColor(column, row * 2)
            bottom = canvas.pixelColor(column, row * 2 + 1)
            parts.append(
                _sgr(
                    (top.red(), top.green(), top.blue()),
                    (bottom.red(), bottom.green(), bottom.blue()),
                )
                + _HALF_BLOCK
            )
        parts.append("\x1b[0m")
        rows.append("".join(parts))
    return rows


def compose(art: list[str], info: list[str], gap: str = "   ") -> str:
    """Put the art on the left and the info lines on the right."""
    lines: list[str] = []
    blank_art = " " * ART_WIDTH
    for index in range(max(len(art), len(info))):
        left = art[index] if index < len(art) else blank_art
        right = info[index] if index < len(info) else ""
        # Reset the art colours before the info text so it uses the theme
        # colours instead of the colour of the last icon cell.
        lines.append(left + "\x1b[0m" + gap + right)
    return "\n".join(lines)
