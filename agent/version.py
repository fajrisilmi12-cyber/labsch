"""LabSCH agent version — single source of truth.

The canonical version lives in the ``VERSION`` file next to this module.
Every installer, upgrade script, heartbeat, and health report must import
from here instead of hard-coding a version string::

    from version import AGENT_VERSION
"""
from pathlib import Path

_FALLBACK = "0.4.0"


def get_version() -> str:
    try:
        text = (Path(__file__).resolve().parent / "VERSION").read_text(
            encoding="utf-8-sig"
        ).strip()
        return text or _FALLBACK
    except OSError:
        return _FALLBACK


__version__ = get_version()
AGENT_VERSION = __version__
