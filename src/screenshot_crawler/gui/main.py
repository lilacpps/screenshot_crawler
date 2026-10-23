"""Console-script shim for the optional inventory GUI."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Launch the GUI, keeping PySide6 optional for normal CLI users."""
    try:
        from .main_window import run
    except ImportError as exc:  # pragma: no cover - exercised without Qt
        if "PySide6" in str(exc):
            print("The inventory GUI requires PySide6. Install the gui extra first.", file=sys.stderr)
            return 2
        raise
    return run(argv)

