"""Console helpers for the command-line entry points."""

from __future__ import annotations

import sys


def use_utf8_output() -> None:
    """Make stdout accept non-cp1252 characters.

    Windows consoles default to cp1252, which can't encode the emoji the CLIs
    print (⚠ 🛒 💰) or the ones a generated Instagram caption will contain —
    printing one raises UnicodeEncodeError and kills the process. Switch stdout
    to UTF-8 and degrade to a replacement character if the terminal still can't
    render something.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # not a real console, or already fine
        pass
