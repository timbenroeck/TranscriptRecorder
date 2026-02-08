"""
Centralized IconManager for rendering Lucide SVG icons as high-DPI QIcons.

Icons are dynamically tinted to match the macOS semantic theme defined in
gui/styles.py.  Renders via QSvgRenderer onto a QPixmap, accounting for
devicePixelRatioF() so that icons stay sharp on Retina displays.

Usage
-----
    from gui.icons import IconManager

    # Apply an icon to a button
    btn.setIcon(IconManager.get_icon("maximize", is_dark=True))

    # Use the primary (Apple Blue) tint
    btn.setIcon(IconManager.get_icon("arrow_up", is_dark=False, tint="primary"))

    # After a theme toggle, clear the cache so new colours are picked up
    IconManager.refresh()
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Colour constants – mirror the palette in gui/styles.py
# ---------------------------------------------------------------------------
_TINTS: dict[str, dict[bool, str]] = {
    # tint_name -> {is_dark: hex_colour}
    "default": {
        True:  "#FFFFFF",   # dark-mode  text_main
        False: "#1D1D1F",   # light-mode text_main
    },
    "primary": {
        True:  "#007AFF",   # Apple Blue (same in both modes)
        False: "#007AFF",
    },
    "secondary": {
        True:  "#98989D",   # dark-mode  text_sec
        False: "#86868B",   # light-mode text_sec
    },
    "success": {
        True:  "#34C759",
        False: "#34C759",
    },
    "danger": {
        True:  "#FF3B30",
        False: "#FF3B30",
    },
}


# ---------------------------------------------------------------------------
# Raw Lucide SVG sources – stroke="currentColor" is replaced at render time
# ---------------------------------------------------------------------------
_SVG_SOURCES: dict[str, str] = {
    "maximize": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M15 3h6v6"/><path d="m21 3-7 7"/>'
        '<path d="m3 21 7-7"/><path d="M9 21H3v-6"/></svg>'
    ),
    "minimize": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m14 10 7-7"/><path d="M20 10h-6V4"/>'
        '<path d="m3 21 7-7"/><path d="M4 14h6v6"/></svg>'
    ),
    "shrink": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m15 15 6 6m-6-6v4.8m0-4.8h4.8"/>'
        '<path d="M9 19.8V15m0 0H4.2M9 15l-6 6"/>'
        '<path d="M15 4.2V9m0 0h4.8M15 9l6-6"/>'
        '<path d="M9 4.2V9m0 0H4.2M9 9 3 3"/></svg>'
    ),
    "expand": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m15 15 6 6"/><path d="m15 9 6-6"/>'
        '<path d="M21 16v5h-5"/><path d="M21 8V3h-5"/>'
        '<path d="M3 16v5h5"/><path d="m3 21 6-6"/>'
        '<path d="M3 8V3h5"/><path d="M9 9 3 3"/></svg>'
    ),
    "chevrons_up": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m17 11-5-5-5 5"/><path d="m17 18-5-5-5 5"/></svg>'
    ),
    "chevrons_down": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m7 6 5 5 5-5"/><path d="m7 13 5 5 5-5"/></svg>'
    ),
    "arrow_up": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M9 13a1 1 0 0 0-1-1H5.061a1 1 0 0 1-.75-1.811l6.836-6.835'
        'a1.207 1.207 0 0 1 1.707 0l6.835 6.835a1 1 0 0 1-.75 1.811H16a1 1 0 '
        '0 0-1 1v6a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1z"/></svg>'
    ),
    "arrow_down": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M15 11a1 1 0 0 0 1 1h2.939a1 1 0 0 1 .75 1.811l-6.835 6.836'
        'a1.207 1.207 0 0 1-1.707 0L4.31 13.81a1 1 0 0 1 .75-1.811H8a1 1 0 0 '
        '0 1-1V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1z"/></svg>'
    ),
}


class IconManager:
    """Render Lucide SVG icons as theme-aware, Retina-ready QIcons.

    All public methods are class-level so you never need to instantiate.

    Rendered pixmaps are cached by ``(name, is_dark, tint, size)``; call
    :meth:`refresh` after a theme toggle to flush the cache.
    """

    # (name, is_dark, tint, logical_size) -> QIcon
    _cache: dict[tuple[str, bool, str, int], QIcon] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def get_icon(
        cls,
        name: str,
        *,
        is_dark: bool = False,
        tint: str = "default",
        size: int = 24,
    ) -> QIcon:
        """Return a QIcon for the named Lucide icon.

        Parameters
        ----------
        name:
            Key into the SVG dictionary (e.g. ``"maximize"``).
        is_dark:
            Current theme mode.
        tint:
            Colour variant — ``"default"``, ``"primary"``, ``"secondary"``,
            ``"success"``, or ``"danger"``.
        size:
            Logical pixel size (default 24).  The physical pixmap will be
            scaled by the screen's ``devicePixelRatioF()``.
        """
        key = (name, is_dark, tint, size)
        if key not in cls._cache:
            cls._cache[key] = cls._render(name, is_dark, tint, size)
        return cls._cache[key]

    @classmethod
    def refresh(cls) -> None:
        """Flush the icon cache.

        Call this whenever ``is_dark`` changes so that subsequent
        :meth:`get_icon` calls re-render with the correct tint.
        """
        cls._cache.clear()

    @classmethod
    def available_icons(cls) -> list[str]:
        """Return the names of all registered SVG icons."""
        return list(_SVG_SOURCES.keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _tinted_svg(cls, name: str, is_dark: bool, tint: str) -> str:
        """Return the SVG source for *name* with ``currentColor`` replaced."""
        svg = _SVG_SOURCES[name]
        colour = _TINTS[tint][is_dark]
        return svg.replace('stroke="currentColor"', f'stroke="{colour}"')

    @classmethod
    def _render(
        cls,
        name: str,
        is_dark: bool,
        tint: str,
        size: int,
    ) -> QIcon:
        """Rasterise an SVG to a high-DPI QIcon.

        The SVG is rendered into an explicit QRectF that fills the full
        logical coordinate space, with KeepAspectRatio so the icon stays
        centred and proportional.  The physical pixmap is scaled by the
        screen's devicePixelRatioF() for Retina sharpness.
        """
        svg_str = cls._tinted_svg(name, is_dark, tint)

        # Determine the display's scale factor for Retina sharpness
        dpr = 1.0
        app = QApplication.instance()
        if app is not None:
            screen = app.primaryScreen()
            if screen is not None:
                dpr = screen.devicePixelRatio()

        physical = int(size * dpr)

        renderer = QSvgRenderer(QByteArray(svg_str.encode("utf-8")))
        renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)

        pixmap = QPixmap(physical, physical)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(dpr)

        # Paint the SVG into the full logical rect so it scales to fill
        # the pixmap rather than using the SVG's internal viewBox size.
        target = QRectF(0, 0, size, size)
        painter = QPainter(pixmap)
        renderer.render(painter, target)
        painter.end()

        icon = QIcon(pixmap)
        return icon
