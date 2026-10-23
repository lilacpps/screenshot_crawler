"""Optional, read-only PySide6 inventory GUI.

The package deliberately keeps the Qt import out of the management and CLI
packages.  Installing the base project therefore does not require PySide6.
"""

from __future__ import annotations

from .main import main

__all__ = ["main"]

