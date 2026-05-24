from __future__ import annotations

try:
    from .ui import run
except ImportError:
    # Supports execution contexts where this module is launched as a script
    # (e.g. some PyInstaller entry modes) and package-relative imports are unavailable.
    from app.ui import run


if __name__ == "__main__":
    run()
