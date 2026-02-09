"""
Centralized IconManager for rendering Lucide SVG icons as high-DPI QIcons.

https://lucide.dev/icons/

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

import tempfile
from pathlib import Path

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
        True:  "#E1E1E6",   # dark-mode  text_main
        False: "#333333",   # light-mode text_main
    },
    "primary": {
        True:  "#7AA2FF",   # Slate Blue (dark – desaturated, lighter)
        False: "#4A67AD",   # Slate Blue (light)
    },
    "secondary": {
        True:  "#8E8E93",   # dark-mode  text_sec
        False: "#636366",   # light-mode text_sec
    },
    "success": {
        True:  "#81C784",
        False: "#388E3C",
    },
    "danger": {
        True:  "#E57373",
        False: "#C62828",
    },
    "warning": {
        True:  "#F0B400",   # dark-mode  Vibrant Amber
        False: "#B78B00",   # light-mode Deep Gold
    },
    "danger_fill": {
        True:  "#E57373",   # dark-mode  soft red on dark bg
        False: "#C62828",   # light-mode deep red on light bg
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
    "copy": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>'
        '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>'
    ),
    "download": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 17V3"/><path d="m6 11 6 6 6-6"/>'
        '<path d="M19 21H5"/></svg>'
    ),
    "save": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5'
        'a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
        '<path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/>'
        '<path d="M7 3v4a1 1 0 0 0 1 1h7"/></svg>'
    ),
    "folder_open": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6'
        'a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9'
        'l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/></svg>'
    ),
    "refresh": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>'
        '<path d="M21 3v5h-5"/>'
        '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>'
        '<path d="M8 16H3v5"/></svg>'
    ),
    "chevron_down": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m6 9 6 6 6-6"/></svg>'
    ),
    "pencil": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83'
        'l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>'
        '<path d="m15 5 4 4"/></svg>'
    ),
    "pencil_off": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m10 10-6.157 6.162a2 2 0 0 0-.5.833l-1.322 4.36a.5.5 0 0 0 '
        '.622.624l4.358-1.323a2 2 0 0 0 .83-.5L14 13.982"/>'
        '<path d="m12.829 7.172 4.359-4.346a1 1 0 1 1 3.986 3.986l-4.353 4.353"/>'
        '<path d="m15 5 4 4"/><path d="m2 2 20 20"/></svg>'
    ),
    "hand": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2"/>'
        '<path d="M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v2"/>'
        '<path d="M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8"/>'
        '<path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34'
        'l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>'
    ),
    "person_standing": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="5" r="1"/>'
        '<path d="m9 20 3-6 3 6"/>'
        '<path d="m6 8 6 2 6-2"/>'
        '<path d="M12 10v4"/></svg>'
    ),
    "circle_alert": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="12" x2="12" y1="8" y2="12"/>'
        '<line x1="12" x2="12.01" y1="16" y2="16"/></svg>'
    ),
    "circle_x": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="m15 9-6 6"/>'
        '<path d="m9 9 6 6"/></svg>'
    ),
    "circle_check": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21.801 10A10 10 0 1 1 17 3.335"/>'
        '<path d="m9 11 3 3L22 4"/></svg>'
    ),
    "circle_help": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
        '<path d="M12 17h.01"/></svg>'
    ),
    "search": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="8"/>'
        '<path d="m21 21-4.3-4.3"/></svg>'
    ),
    "scan_eye": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 7V5a2 2 0 0 1 2-2h2"/>'
        '<path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
        '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
        '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
        '<circle cx="12" cy="12" r="1"/>'
        '<path d="M18.944 12.33a1 1 0 0 0 0-.66 7.5 7.5 0 0 0-13.888 0 1 1 0 0 0 0 .66 '
        '7.5 7.5 0 0 0 13.888 0"/></svg>'
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
    def get_pixmap(
        cls,
        name: str,
        *,
        is_dark: bool = False,
        tint: str = "default",
        size: int = 24,
    ) -> QPixmap:
        """Return a high-DPI QPixmap for the named icon (no QIcon wrapper)."""
        svg_str = cls._tinted_svg(name, is_dark, tint)

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

        target = QRectF(0, 0, size, size)
        painter = QPainter(pixmap)
        renderer.render(painter, target)
        painter.end()
        return pixmap

    @classmethod
    def available_icons(cls) -> list[str]:
        """Return the names of all registered SVG icons."""
        return list(_SVG_SOURCES.keys())

    @classmethod
    def render_to_file(
        cls,
        name: str,
        *,
        is_dark: bool = False,
        tint: str = "default",
        size: int = 12,
    ) -> str:
        """Render an icon to a temporary PNG file and return its absolute path.

        Useful for QSS ``image: url(...)`` rules that require a file path.
        The rendered pixmap honours the screen's ``devicePixelRatio`` for
        Retina sharpness, identical to :meth:`_render`.
        """
        svg_str = cls._tinted_svg(name, is_dark, tint)

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

        target = QRectF(0, 0, size, size)
        painter = QPainter(pixmap)
        renderer.render(painter, target)
        painter.end()

        # Write to a stable temp directory so the path can be reused
        cache_dir = Path(tempfile.gettempdir()) / "TranscriptRecorder_icons"
        cache_dir.mkdir(exist_ok=True)
        tag = "dark" if is_dark else "light"
        out_path = cache_dir / f"{name}_{tint}_{size}_{tag}.png"
        pixmap.save(str(out_path), "PNG")
        return str(out_path)

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
