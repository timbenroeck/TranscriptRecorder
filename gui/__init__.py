"""
Transcript Recorder GUI package.

Provides the PyQt6-based graphical interface for the Transcript Recorder
application, split into focused modules by responsibility.
"""


def main():
    """Convenience entry point — delegates to gui.main_window.main()."""
    from gui.main_window import main as _main
    _main()


__all__ = ["main"]
